"""Command line interface: PDF invoices in, Excel or CSV report out."""

import argparse
import sys
from pathlib import Path

from pdf_extractor import __version__
from pdf_extractor.exporters import summary_metrics, write_csv, write_excel
from pdf_extractor.extractor import ExtractedInvoice, extract_folder, extract_invoice

DEFAULT_OUTPUT = Path("output/report.xlsx")
SUPPORTED_SUFFIXES = (".xlsx", ".csv")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pdf_extractor",
        description="Extract invoice data from PDF files into an Excel or CSV report.",
    )
    parser.add_argument("input", type=Path, help="a PDF file or a folder with PDF files")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="report file, .xlsx or .csv (default: output/report.xlsx)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit with code 1 if any invoice needs review",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def collect_invoices(path: Path) -> list[ExtractedInvoice]:
    """Read one PDF file or every PDF in a folder."""
    if path.is_dir():
        return extract_folder(path)
    return [extract_invoice(path)]


def format_summary(invoices: list[ExtractedInvoice], written: list[Path]) -> str:
    """The text printed after a run: counts, total, problems and output files."""
    metrics = dict(summary_metrics(invoices))
    lines = [
        f"Processed {metrics['Invoices processed']} invoice(s): "
        f"{metrics['All checks passed']} OK, {metrics['Need review']} need review",
        f"Total of all invoices: {metrics['Total of all invoices']:,.2f}",
    ]
    problems = [invoice for invoice in invoices if not invoice.is_valid]
    if problems:
        lines.append("Needs review:")
        for invoice in problems:
            lines.append(f"  {invoice.source}")
            lines.extend(f"    - {warning}" for warning in invoice.warnings)
    lines.extend(f"Report written to: {path}" for path in written)
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    suffix = args.output.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        parser.error("the output file must end with .xlsx or .csv")
    if not args.input.exists():
        parser.error(f"input not found: {args.input}")

    invoices = collect_invoices(args.input)
    if not invoices:
        print(f"No PDF files found in {args.input}", file=sys.stderr)
        return 1

    try:
        if suffix == ".xlsx":
            written = [write_excel(invoices, args.output)]
        else:
            written = write_csv(invoices, args.output)
    except OSError as exc:
        print(f"Could not write the report: {exc}", file=sys.stderr)
        return 1

    print(format_summary(invoices, written))
    needs_review = any(not invoice.is_valid for invoice in invoices)
    return 1 if args.strict and needs_review else 0
