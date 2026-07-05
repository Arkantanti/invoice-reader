import argparse
import sys

from pipeline import process_invoice


def display_result(validated) -> None:
    print("\n--- Extracted Data ---")
    print(validated.data.model_dump_json(indent=2))

    print("\n--- Validation Result ---")
    print(f"Flagged for review: {validated.flagged_for_review}")

    if validated.issues:
        print("\nIssues:")
        for issue in validated.issues:
            print(f"  [{issue.severity}] {issue.field}: {issue.message}")
    else:
        print("\nNo issues found.")


def main():
    parser = argparse.ArgumentParser(description="Extract and validate a single invoice PDF.")
    parser.add_argument("pdf_path", help="Path to the invoice PDF file")
    args = parser.parse_args()

    try:
        validated = process_invoice(args.pdf_path)
        display_result(validated)
    except FileNotFoundError:
        print(f"Error: file not found: {args.pdf_path}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error processing invoice: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()