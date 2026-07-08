"""Tkinter desktop app for batch-reviewing invoice extractions.

Workflow: choose a folder of PDF invoices (or a single PDF) -> process them ->
page through the results, seeing the extracted fields (with flagged ones
highlighted), the list of validation issues, and the rendered PDF page side by
side.

Threading note: Tkinter is single-threaded and not thread-safe. The slow work
(LLM pipeline per PDF, and page rasterization) runs on background threads that
only ever communicate back by putting messages on ``queue.Queue``s; the Tk main
loop drains those queues via ``after()`` and is the only thing that touches
widgets.
"""
import queue
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from PIL import ImageTk

from . import render
from .processing import InvoiceResult, find_pdfs, process_pdf

STATUS_GLYPH = {"ok": "✓", "flagged": "⚠", "error": "✗"}

# ValidationIssue.field values line up with InvoiceData field names except for a
# couple that validate.py reports under a different name; map those back so the
# right table row lights up. The raw field is still shown in the issues list.
FIELD_ALIASES = {"bank_account_number": "iban"}

SEVERITY_BG = {"error": "#f8d7da", "warning": "#fff3cd"}


class InvoiceReviewApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Invoice Reader — Review")
        self.geometry("1200x760")

        self._folder: str | None = None
        self._results: list[InvoiceResult] = []
        self._processing = False

        self._proc_queue: queue.Queue = queue.Queue()
        self._render_queue: queue.Queue = queue.Queue()
        self._render_token = 0
        self._preview_image: ImageTk.PhotoImage | None = None

        self._build_toolbar()
        self._build_body()

        # Perpetual poller for rendered pages (cheap; runs for the app's life).
        self.after(80, self._poll_render_queue)

    # ------------------------------------------------------------------ layout
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=8)
        bar.pack(side=tk.TOP, fill=tk.X)

        self.file_btn = ttk.Button(bar, text="Choose PDF…", command=self._choose_file)
        self.file_btn.pack(side=tk.LEFT)

        self.choose_btn = ttk.Button(bar, text="Choose folder…", command=self._choose_folder)
        self.choose_btn.pack(side=tk.LEFT, padx=(6, 0))

        self.folder_var = tk.StringVar(value="No folder selected")
        ttk.Label(bar, textvariable=self.folder_var).pack(side=tk.LEFT, padx=8)

        self.process_btn = ttk.Button(bar, text="Process", command=self._start_processing, state=tk.DISABLED)
        self.process_btn.pack(side=tk.LEFT)

        self.progress_var = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.progress_var).pack(side=tk.LEFT, padx=12)

    def _build_body(self) -> None:
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        paned.add(self._build_list_pane(paned), weight=1)
        paned.add(self._build_detail_pane(paned), weight=2)
        paned.add(self._build_preview_pane(paned), weight=3)

    def _build_list_pane(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, width=240)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL)
        self.listbox = tk.Listbox(frame, exportselection=False, yscrollcommand=scroll.set)
        scroll.configure(command=self.listbox.yview)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.listbox.bind("<<ListboxSelect>>", self._on_select)
        return frame

    def _build_detail_pane(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=6)

        self.header_var = tk.StringVar(value="Select an invoice")
        ttk.Label(frame, textvariable=self.header_var, font=("", 11, "bold")).pack(anchor=tk.W, pady=(0, 6))

        self.fields_tree = ttk.Treeview(frame, columns=("field", "value"), show="headings", height=12)
        self.fields_tree.heading("field", text="Field")
        self.fields_tree.heading("value", text="Value")
        self.fields_tree.column("field", width=170, anchor=tk.W, stretch=False)
        self.fields_tree.column("value", width=300, anchor=tk.W)
        self.fields_tree.tag_configure("error", background=SEVERITY_BG["error"])
        self.fields_tree.tag_configure("warning", background=SEVERITY_BG["warning"])
        self.fields_tree.pack(fill=tk.X)

        ttk.Label(frame, text="Issues", font=("", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))

        self.issues_tree = ttk.Treeview(frame, columns=("sev", "field", "msg"), show="headings", height=8)
        self.issues_tree.heading("sev", text="Severity")
        self.issues_tree.heading("field", text="Field")
        self.issues_tree.heading("msg", text="Message")
        self.issues_tree.column("sev", width=70, anchor=tk.W, stretch=False)
        self.issues_tree.column("field", width=120, anchor=tk.W, stretch=False)
        self.issues_tree.column("msg", width=320, anchor=tk.W)
        self.issues_tree.tag_configure("error", background=SEVERITY_BG["error"])
        self.issues_tree.tag_configure("warning", background=SEVERITY_BG["warning"])
        self.issues_tree.pack(fill=tk.BOTH, expand=True)

        return frame

    def _build_preview_pane(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=(0, 6))

        self.preview_status = tk.StringVar(value="")
        ttk.Label(frame, textvariable=self.preview_status, padding=(6, 0)).pack(anchor=tk.W)

        canvas_frame = ttk.Frame(frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(canvas_frame, background="#525659", highlightthickness=0)
        vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        hbar = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        return frame

    # --------------------------------------------------------------- toolbar actions
    def _choose_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a folder of PDF invoices")
        if not path:
            return
        self._folder = path
        self.folder_var.set(path)
        count = len(find_pdfs(path))
        self.progress_var.set(f"{count} PDF(s) found")
        self.process_btn.configure(state=(tk.NORMAL if count and not self._processing else tk.DISABLED))

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a PDF invoice",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return
        pdf = Path(path)
        # Single-file mode: there's no folder, and processing starts immediately.
        self._folder = None
        self.folder_var.set(pdf.name)
        self._run_processing([pdf])

    def _start_processing(self) -> None:
        if not self._folder:
            return
        self._run_processing(find_pdfs(self._folder))

    def _run_processing(self, pdfs) -> None:
        """Process a list of PDFs (one file or a whole folder) on a worker thread."""
        pdfs = list(pdfs)
        if self._processing or not pdfs:
            return

        self._processing = True
        self._results = []
        self.listbox.delete(0, tk.END)
        self._clear_detail()
        self._set_inputs_enabled(False)

        threading.Thread(target=self._process_worker, args=(pdfs,), daemon=True).start()
        self.after(100, self._drain_proc_queue)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Enable/disable the toolbar inputs (all disabled while a run is in flight)."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.file_btn.configure(state=state)
        self.choose_btn.configure(state=state)
        # "Process" is only meaningful when a folder with PDFs is selected.
        has_folder_pdfs = enabled and bool(self._folder) and bool(find_pdfs(self._folder))
        self.process_btn.configure(state=(tk.NORMAL if has_folder_pdfs else tk.DISABLED))

    # ------------------------------------------------------------- background workers
    def _process_worker(self, pdfs) -> None:
        total = len(pdfs)
        for i, pdf in enumerate(pdfs, start=1):
            self._proc_queue.put(("progress", i, total, pdf.name))
            self._proc_queue.put(("result", process_pdf(pdf)))
        self._proc_queue.put(("done", total))

    def _drain_proc_queue(self) -> None:
        try:
            while True:
                msg = self._proc_queue.get_nowait()
                if msg[0] == "progress":
                    _, i, total, name = msg
                    self.progress_var.set(f"Processing {i}/{total} — {name}")
                elif msg[0] == "result":
                    self._append_result(msg[1])
                elif msg[0] == "done":
                    self._finish_processing(msg[1])
                    return
        except queue.Empty:
            pass
        self.after(100, self._drain_proc_queue)

    def _append_result(self, result: InvoiceResult) -> None:
        self._results.append(result)
        self.listbox.insert(tk.END, f"{STATUS_GLYPH[result.status]}  {result.name}")
        if len(self._results) == 1:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            self._show_result(0)

    def _finish_processing(self, total: int) -> None:
        self._processing = False
        flagged = sum(1 for r in self._results if r.status == "flagged")
        errors = sum(1 for r in self._results if r.status == "error")
        self.progress_var.set(f"Done — {total} processed, {flagged} flagged, {errors} error(s)")
        self._set_inputs_enabled(True)

    # ----------------------------------------------------------------- detail display
    def _on_select(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if selection:
            self._show_result(selection[0])

    def _show_result(self, index: int) -> None:
        result = self._results[index]
        self.header_var.set(f"{STATUS_GLYPH[result.status]}  {result.name}   [{result.status}]")
        self._populate_fields(result)
        self._populate_issues(result)
        self._request_preview(result)

    def _populate_fields(self, result: InvoiceResult) -> None:
        self._clear_tree(self.fields_tree)
        if result.validated is None:
            self.fields_tree.insert("", tk.END, values=("(error)", result.error or "Processing failed"), tags=("error",))
            return

        severities = self._field_severities(result.validated)
        data = result.validated.data
        dumped = data.model_dump()
        for field_name in type(data).model_fields:
            value = dumped.get(field_name)
            display = "—" if value is None else str(value)
            sev = severities.get(field_name)
            tags = (sev,) if sev else ()
            self.fields_tree.insert("", tk.END, values=(field_name, display), tags=tags)

    @staticmethod
    def _field_severities(validated) -> dict[str, str]:
        """Map each flagged InvoiceData field to its worst severity (error > warning)."""
        worst: dict[str, str] = {}
        for issue in validated.issues:
            field = FIELD_ALIASES.get(issue.field, issue.field)
            if issue.severity == "error" or worst.get(field) != "error":
                worst[field] = issue.severity
        return worst

    def _populate_issues(self, result: InvoiceResult) -> None:
        self._clear_tree(self.issues_tree)
        if result.validated is None:
            self.issues_tree.insert("", tk.END, values=("error", "—", result.error or "Processing failed"), tags=("error",))
            return
        if not result.validated.issues:
            self.issues_tree.insert("", tk.END, values=("", "", "No issues found."))
            return
        for issue in result.validated.issues:
            self.issues_tree.insert("", tk.END, values=(issue.severity, issue.field, issue.message), tags=(issue.severity,))

    # ---------------------------------------------------------------- preview rendering
    def _request_preview(self, result: InvoiceResult) -> None:
        # Bump the token so a slow render for a previously-selected invoice is
        # ignored when it finally arrives.
        self._render_token += 1
        token = self._render_token
        self.canvas.delete("all")
        self._preview_image = None

        if not render.RENDER_AVAILABLE:
            self.preview_status.set("Preview unavailable (install pypdfium2)")
            return

        self.preview_status.set("Rendering…")
        path = str(result.path)
        threading.Thread(target=self._render_worker, args=(token, path), daemon=True).start()

    def _render_worker(self, token: int, path: str) -> None:
        self._render_queue.put((token, render.render_page(path, 0)))

    def _poll_render_queue(self) -> None:
        try:
            while True:
                token, image = self._render_queue.get_nowait()
                if token == self._render_token:  # ignore superseded renders
                    self._display_preview(image)
        except queue.Empty:
            pass
        self.after(80, self._poll_render_queue)

    def _display_preview(self, image) -> None:
        self.canvas.delete("all")
        if image is None:
            self._preview_image = None
            self.preview_status.set("Preview unavailable for this file")
            return
        photo = ImageTk.PhotoImage(image)
        self._preview_image = photo  # keep a reference or Tk garbage-collects it
        self.canvas.create_image(0, 0, anchor=tk.NW, image=photo)
        self.canvas.configure(scrollregion=(0, 0, image.width, image.height))
        self.preview_status.set(f"Page 1  ({image.width}×{image.height}px)")

    # ------------------------------------------------------------------------- helpers
    @staticmethod
    def _clear_tree(tree: ttk.Treeview) -> None:
        for row in tree.get_children():
            tree.delete(row)

    def _clear_detail(self) -> None:
        self.header_var.set("Select an invoice")
        self._clear_tree(self.fields_tree)
        self._clear_tree(self.issues_tree)
        self.canvas.delete("all")
        self._preview_image = None
        self.preview_status.set("")


def main() -> None:
    InvoiceReviewApp().mainloop()
