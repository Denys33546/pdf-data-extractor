"""Extract invoice fields and line items from text-based PDF invoices."""

import re
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

CENT = Decimal("0.01")
EXPECTED_HEADER = ["description", "qty", "unit price", "amount"]

MONEY = r"\$?\s*(-?[\d,]+\.\d{2})"
NUMBER_RE = re.compile(
    r"Invoice\s*(?:No\.?|Number|#)\s*[:#]?\s*([A-Za-z0-9][A-Za-z0-9\-/]*)", re.IGNORECASE
)
DATE_RE = re.compile(r"^(?:Invoice\s+)?Date:\s*(\S+)\s*$", re.IGNORECASE | re.MULTILINE)
CUSTOMER_RE = re.compile(r"^Bill To:\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
SUBTOTAL_RE = re.compile(rf"^Subtotal\s+{MONEY}\s*$", re.IGNORECASE | re.MULTILINE)
TAX_RE = re.compile(rf"^Tax\b.*?\s+{MONEY}\s*$", re.IGNORECASE | re.MULTILINE)
TOTAL_RE = re.compile(rf"^Total\s+{MONEY}\s*$", re.IGNORECASE | re.MULTILINE)

Table = list[list[str | None]]


@dataclass(frozen=True)
class ExtractedLine:
    description: str
    quantity: int
    unit_price: Decimal
    amount: Decimal


@dataclass(frozen=True)
class ExtractedInvoice:
    source: str
    number: str | None
    issue_date: date | None
    vendor: str | None
    customer: str | None
    items: tuple[ExtractedLine, ...]
    subtotal: Decimal | None
    tax: Decimal | None
    total: Decimal | None
    warnings: tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        """True when every field was found and all the numbers add up."""
        return not self.warnings


def parse_money(text: str) -> Decimal:
    """'$1,234.50' -> Decimal('1234.50')."""
    cleaned = text.replace("$", "").replace(",", "").strip()
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Not a money amount: {text!r}") from None
    if not value.is_finite():
        raise ValueError(f"Not a money amount: {text!r}")
    return value.quantize(CENT, ROUND_HALF_UP)


def _search(regex: re.Pattern[str], text: str) -> str | None:
    match = regex.search(text)
    return match.group(1).strip() if match else None


def _search_money(regex: re.Pattern[str], text: str) -> Decimal | None:
    value = _search(regex, text)
    return parse_money(value) if value else None


def _find_vendor(text: str) -> str | None:
    """The vendor name is the first line that is not the word INVOICE."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and stripped.lower() != "invoice":
            return stripped
    return None


def parse_items(tables: list[Table]) -> tuple[tuple[ExtractedLine, ...], list[str]]:
    """Find the item table by its header row and convert its rows."""
    for table in tables:
        header = [" ".join((cell or "").split()).lower() for cell in table[0]] if table else []
        if header != EXPECTED_HEADER:
            continue
        items: list[ExtractedLine] = []
        warnings: list[str] = []
        for row_number, row in enumerate(table[1:], start=2):
            cells = [" ".join((cell or "").split()) for cell in row]
            if not any(cells):
                continue
            try:
                description, quantity, unit_price, amount = cells
                items.append(
                    ExtractedLine(
                        description, int(quantity), parse_money(unit_price), parse_money(amount)
                    )
                )
            except ValueError:
                warnings.append(f"Skipped unreadable table row {row_number}: {cells}")
        return tuple(items), warnings
    return (), ["Item table not found"]


def check_numbers(
    items: tuple[ExtractedLine, ...],
    subtotal: Decimal | None,
    tax: Decimal | None,
    total: Decimal | None,
) -> list[str]:
    """Verify that quantities, prices, subtotal, tax and total are consistent."""
    warnings = []
    for item in items:
        expected = (item.unit_price * item.quantity).quantize(CENT, ROUND_HALF_UP)
        if expected != item.amount:
            warnings.append(
                f"Line '{item.description}': {item.quantity} x {item.unit_price} "
                f"is {expected}, but the invoice says {item.amount}"
            )
    items_sum = sum((item.amount for item in items), Decimal("0.00"))
    if items and subtotal is not None and items_sum != subtotal:
        warnings.append(f"Items add up to {items_sum}, but the subtotal is {subtotal}")
    if subtotal is not None and tax is not None and total is not None and subtotal + tax != total:
        warnings.append(f"Subtotal + tax is {subtotal + tax}, but the total is {total}")
    return warnings


def parse_invoice(text: str, tables: list[Table], source: str) -> ExtractedInvoice:
    """Turn the text and tables of one PDF into an ExtractedInvoice."""
    if not text.strip():
        return _failed(
            source, "No text found. This looks like a scanned PDF (OCR is not supported)"
        )

    warnings: list[str] = []
    number = _search(NUMBER_RE, text)
    if number is None:
        warnings.append("Invoice number not found")

    issue_date = None
    raw_date = _search(DATE_RE, text)
    if raw_date is None:
        warnings.append("Date not found")
    else:
        try:
            issue_date = date.fromisoformat(raw_date)
        except ValueError:
            warnings.append(f"Date '{raw_date}' is not in YYYY-MM-DD format")

    subtotal = _search_money(SUBTOTAL_RE, text)
    tax = _search_money(TAX_RE, text)
    total = _search_money(TOTAL_RE, text)
    if total is None:
        warnings.append("Total not found")

    items, item_warnings = parse_items(tables)
    warnings += item_warnings
    warnings += check_numbers(items, subtotal, tax, total)

    return ExtractedInvoice(
        source=source,
        number=number,
        issue_date=issue_date,
        vendor=_find_vendor(text),
        customer=_search(CUSTOMER_RE, text),
        items=items,
        subtotal=subtotal,
        tax=tax,
        total=total,
        warnings=tuple(warnings),
    )


def _failed(source: str, message: str) -> ExtractedInvoice:
    return ExtractedInvoice(source, None, None, None, None, (), None, None, None, (message,))


def extract_invoice(path: Path) -> ExtractedInvoice:
    """Read one PDF file. Problems are reported in `warnings`, never raised."""
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return _failed(path.name, "PDF has no pages")
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            tables = [table for page in pdf.pages for table in page.extract_tables()]
    except Exception as exc:  # pdfminer raises many different error types
        return _failed(path.name, f"Could not read PDF: {exc}")
    return parse_invoice(text, tables, path.name)


def extract_folder(folder: Path) -> list[ExtractedInvoice]:
    """Extract every PDF in a folder (sorted by file name). One bad file does not stop the rest."""
    if not folder.is_dir():
        raise NotADirectoryError(f"Not a folder: {folder}")
    pdf_files = [p for p in sorted(folder.iterdir()) if p.suffix.lower() == ".pdf"]
    return [extract_invoice(path) for path in pdf_files]
