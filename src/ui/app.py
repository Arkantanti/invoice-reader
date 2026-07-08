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
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import ImageTk

from . import render
from .processing import InvoiceResult, find_pdfs, process_pdf


def open_in_default_app(path: Path) -> None:
    """Open a file with the OS default application (PDF reader for a .pdf)."""
    if sys.platform == "win32":
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


def enable_dpi_awareness() -> None:
    """Declare this process DPI-aware so Windows renders it at the monitor's true
    pixel density instead of bitmap-stretching (blurring) a low-res window.

    Must be called *before* the first Tk window is created. No-op off Windows,
    and best-effort — if it can't be set (e.g. already set), the app still runs.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # per-monitor aware
        except Exception:  # noqa: BLE001 - older Windows: fall back to system-aware
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:  # noqa: BLE001
        pass

STATUS_GLYPH = {"ok": "✓", "flagged": "⚠", "error": "✗"}

# ValidationIssue.field values line up with InvoiceData field names except for a
# couple that validate.py reports under a different name; map those back so the
# right table row lights up. The raw field is still shown in the issues list.
FIELD_ALIASES = {"bank_account_number": "iban"}

SEVERITY_BG = {"error": "#f8d7da", "warning": "#fff3cd"}

PREVIEW_MARGIN = 8   # px around the page(s) in the preview canvas
PREVIEW_GAP = 10     # px between stacked pages


class InvoiceReviewApp(tk.Tk):
    def __init__(self) -> None:
        enable_dpi_awareness()  # must precede Tk root creation
        super().__init__()
        self.title("Invoice Reader — Review")

        # With DPI awareness on, Windows no longer magnifies the UI, so we scale
        # pixel-sized dimensions ourselves by the display's DPI factor (1.0 at
        # 96 DPI / 100%). Fonts scale via Tk's own point→pixel scaling.
        dpi = self.winfo_fpixels("1i")
        self._ui_scale = dpi / 96.0
        self.tk.call("tk", "scaling", dpi / 72.0)
        self.geometry(f"{self._px(1200)}x{self._px(760)}")

        self._folder: str | None = None
        self._pending_pdfs: list[Path] = []   # selection awaiting a "Process" click
        self._results: list[InvoiceResult] = []
        self._run_start_index = 0             # index in _results where the current run began
        self._current_result: InvoiceResult | None = None
        self._processing = False

        self._proc_queue: queue.Queue = queue.Queue()
        self._render_queue: queue.Queue = queue.Queue()
        self._render_token = 0
        self._preview_photos: list = []          # ImageTk refs (kept so Tk doesn't GC them)
        self._fitted_width: int | None = None    # pane width the pages were last rendered for
        self._pending_render_width = 0           # pane width of the in-flight render
        self._preserve_scroll_next = False       # keep scroll position on the next draw (resize)
        self._preview_resize_job = None

        self._build_toolbar()
        self._build_body()

        # Perpetual poller for rendered pages (cheap; runs for the app's life).
        self.after(80, self._poll_render_queue)

    def _px(self, n: int) -> int:
        """Scale a pixel dimension by the display's DPI factor (1.0 at 96 DPI)."""
        return round(n * self._ui_scale)

    # ------------------------------------------------------------------ layout
    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=8)
        bar.pack(side=tk.TOP, fill=tk.X)

        self.file_btn = ttk.Button(bar, text="Choose PDF", command=self._choose_file)
        self.file_btn.pack(side=tk.LEFT)

        self.choose_btn = ttk.Button(bar, text="Choose folder", command=self._choose_folder)
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
        frame = ttk.Frame(parent, width=self._px(240))
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
        self.fields_tree.column("field", width=self._px(170), anchor=tk.W, stretch=False)
        self.fields_tree.column("value", width=self._px(300), anchor=tk.W)
        self.fields_tree.tag_configure("error", background=SEVERITY_BG["error"])
        self.fields_tree.tag_configure("warning", background=SEVERITY_BG["warning"])
        self.fields_tree.pack(fill=tk.X)

        ttk.Label(frame, text="Issues", font=("", 10, "bold")).pack(anchor=tk.W, pady=(10, 2))

        self.issues_tree = ttk.Treeview(frame, columns=("sev", "field", "msg"), show="headings", height=8)
        self.issues_tree.heading("sev", text="Severity")
        self.issues_tree.heading("field", text="Field")
        self.issues_tree.heading("msg", text="Message")
        self.issues_tree.column("sev", width=self._px(70), anchor=tk.W, stretch=False)
        self.issues_tree.column("field", width=self._px(120), anchor=tk.W, stretch=False)
        self.issues_tree.column("msg", width=self._px(320), anchor=tk.W)
        self.issues_tree.tag_configure("error", background=SEVERITY_BG["error"])
        self.issues_tree.tag_configure("warning", background=SEVERITY_BG["warning"])
        self.issues_tree.pack(fill=tk.BOTH, expand=True)

        return frame

    def _build_preview_pane(self, parent) -> ttk.Frame:
        frame = ttk.Frame(parent, padding=(0, 6))

        header = ttk.Frame(frame)
        header.pack(fill=tk.X)
        self.preview_status = tk.StringVar(value="")
        ttk.Label(header, textvariable=self.preview_status, padding=(6, 0)).pack(side=tk.LEFT)
        self.open_pdf_btn = ttk.Button(
            header, text="Open in PDF reader", command=self._open_in_system_viewer, state=tk.DISABLED
        )
        self.open_pdf_btn.pack(side=tk.RIGHT, padx=6)

        canvas_frame = ttk.Frame(frame)
        canvas_frame.pack(fill=tk.BOTH, expand=True)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        # Pages are always fitted to the pane width, so only a vertical scrollbar
        # is needed (for page height / multi-page documents).
        self.canvas = tk.Canvas(canvas_frame, background="#525659", highlightthickness=0)
        vbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")

        # Re-fit on resize (debounced), and allow mouse-wheel scrolling.
        self.canvas.bind("<Configure>", self._on_preview_configure)
        self.canvas.bind("<MouseWheel>", self._on_preview_mousewheel)      # Windows / macOS
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-1, "units"))  # Linux
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(1, "units"))

        return frame

    # --------------------------------------------------------------- toolbar actions
    def _choose_folder(self) -> None:
        path = filedialog.askdirectory(title="Choose a folder of PDF invoices")
        if not path:
            return
        self._folder = path
        pdfs = find_pdfs(path)
        self._pending_pdfs = pdfs
        self.folder_var.set(path)
        self.progress_var.set(f"{len(pdfs)} PDF(s) selected — press Process")
        self.process_btn.configure(state=(tk.NORMAL if pdfs else tk.DISABLED))

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Choose a PDF invoice",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")],
        )
        if not path:
            return
        pdf = Path(path)
        # Consistent with batch mode: stage the selection, then wait for "Process".
        self._folder = None
        self._pending_pdfs = [pdf]
        self.folder_var.set(pdf.name)
        self.progress_var.set("1 PDF selected — press Process")
        self.process_btn.configure(state=tk.NORMAL)

    def _start_processing(self) -> None:
        self._run_processing(self._pending_pdfs)

    def _run_processing(self, pdfs) -> None:
        """Process the staged PDFs on a worker thread, appending to any prior results."""
        pdfs = list(pdfs)
        if self._processing or not pdfs:
            return

        self._pending_pdfs = []             # consumed by this run
        self._processing = True
        self._run_start_index = len(self._results)   # append; keep previous results
        self._set_inputs_enabled(False)

        threading.Thread(target=self._process_worker, args=(pdfs,), daemon=True).start()
        self.after(100, self._drain_proc_queue)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        """Enable/disable the toolbar inputs (all disabled while a run is in flight)."""
        state = tk.NORMAL if enabled else tk.DISABLED
        self.file_btn.configure(state=state)
        self.choose_btn.configure(state=state)
        # "Process" is enabled only when there's a staged selection to run.
        has_pending = enabled and bool(self._pending_pdfs)
        self.process_btn.configure(state=(tk.NORMAL if has_pending else tk.DISABLED))

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
        index = len(self._results)
        self._results.append(result)
        self.listbox.insert(tk.END, f"{STATUS_GLYPH[result.status]}  {result.name}")
        if index == self._run_start_index:  # first result of the current run
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(index)
            self.listbox.see(index)
            self._show_result(index)

    def _finish_processing(self, total: int) -> None:
        self._processing = False
        flagged = sum(1 for r in self._results if r.status == "flagged")
        errors = sum(1 for r in self._results if r.status == "error")
        self.progress_var.set(f"Done — {total} processed; {len(self._results)} loaded, {flagged} flagged, {errors} error(s)")
        self._set_inputs_enabled(True)

    # ----------------------------------------------------------------- detail display
    def _on_select(self, _event=None) -> None:
        selection = self.listbox.curselection()
        if selection:
            self._show_result(selection[0])

    def _show_result(self, index: int) -> None:
        result = self._results[index]
        self._current_result = result
        self.header_var.set(f"{STATUS_GLYPH[result.status]}  {result.name}   [{result.status}]")
        self._populate_fields(result)
        self._populate_issues(result)
        self._start_preview_render(clear=True)
        # Only offer "open" when the source file is actually on disk.
        self.open_pdf_btn.configure(state=(tk.NORMAL if result.path.exists() else tk.DISABLED))

    def _open_in_system_viewer(self) -> None:
        result = self._current_result
        if result is None:
            return
        if not result.path.exists():
            messagebox.showerror("Open PDF", f"File not found:\n{result.path}")
            return
        try:
            open_in_default_app(result.path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("Open PDF", f"Could not open the PDF:\n{result.path}\n\n{exc}")

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
    def _start_preview_render(self, clear: bool) -> None:
        """Rasterize the current invoice's pages to the pane width on a worker thread.

        ``clear=True`` for a new selection (blank the canvas and reset scroll);
        ``clear=False`` for a resize re-render (keep the old image visible until
        the new one is ready, and preserve the scroll position). Each render goes
        straight to the current pane width via pypdfium2 — sharp at any size.
        """
        result = self._current_result
        if result is None:
            return
        if not render.RENDER_AVAILABLE:
            self.canvas.delete("all")
            self._preview_photos = []
            self.preview_status.set("Preview unavailable (install pypdfium2)")
            return

        width = self.canvas.winfo_width()
        if width <= 1:  # canvas not laid out yet — retry shortly
            self.after(50, lambda: self._start_preview_render(clear))
            return

        target_w = max(width - 2 * PREVIEW_MARGIN, 1)
        self._render_token += 1        # supersede any in-flight render
        token = self._render_token
        self._pending_render_width = width
        self._preserve_scroll_next = not clear
        if clear:
            self.canvas.delete("all")
            self._preview_photos = []
        self.preview_status.set("Rendering…")

        path = str(result.path)
        threading.Thread(
            target=self._render_worker, args=(token, path, target_w), daemon=True
        ).start()

    def _render_worker(self, token: int, path: str, width: int) -> None:
        self._render_queue.put((token, render.render_pages_to_width(path, width)))

    def _poll_render_queue(self) -> None:
        try:
            while True:
                token, pages = self._render_queue.get_nowait()
                if token == self._render_token:  # ignore superseded renders
                    self._draw_pages(pages)
        except queue.Empty:
            pass
        self.after(80, self._poll_render_queue)

    def _draw_pages(self, pages) -> None:
        prev_scroll = self.canvas.yview()[0]
        self.canvas.delete("all")
        self._preview_photos = []
        if not pages:
            self.preview_status.set("Preview unavailable for this file")
            self._fitted_width = None
            return

        y = PREVIEW_MARGIN
        max_w = 0
        for img in pages:
            photo = ImageTk.PhotoImage(img)
            self._preview_photos.append(photo)  # keep refs so Tk doesn't GC them
            self.canvas.create_image(PREVIEW_MARGIN, y, anchor=tk.NW, image=photo)
            y += img.height + PREVIEW_GAP
            max_w = max(max_w, img.width)

        content_w = max(self.canvas.winfo_width(), max_w + 2 * PREVIEW_MARGIN)
        self.canvas.configure(scrollregion=(0, 0, content_w, y - PREVIEW_GAP + PREVIEW_MARGIN))
        self.canvas.yview_moveto(prev_scroll if self._preserve_scroll_next else 0.0)
        self._fitted_width = self._pending_render_width

        n = len(pages)
        self.preview_status.set(f"{n} page{'s' if n != 1 else ''} — {pages[0].width}px wide")

    def _on_preview_configure(self, _event=None) -> None:
        # Debounce: re-render at the new width only after resizing settles.
        if self._preview_resize_job is not None:
            self.after_cancel(self._preview_resize_job)
        self._preview_resize_job = self.after(150, self._rerender_if_width_changed)

    def _rerender_if_width_changed(self) -> None:
        self._preview_resize_job = None
        width = self.canvas.winfo_width()
        if width <= 1 or width == self._fitted_width:  # unchanged / height-only resize
            return
        if self._current_result is None or not render.RENDER_AVAILABLE:
            return
        self._start_preview_render(clear=False)

    def _on_preview_mousewheel(self, event) -> None:
        self.canvas.yview_scroll(-int(event.delta / 120), "units")

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
        self._preview_photos = []
        self._fitted_width = None
        self.preview_status.set("")
        self._current_result = None
        self.open_pdf_btn.configure(state=tk.DISABLED)


def main() -> None:
    InvoiceReviewApp().mainloop()
