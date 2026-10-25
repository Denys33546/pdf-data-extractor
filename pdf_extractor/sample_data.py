"""Generate fictional sample invoices (PDF) for demos and tests.

All vendors, customers and prices are made up. The PDFs are text-based
(not scans), like invoices exported from accounting software.
"""

import argparse
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

VENDORS = [
    "Northwind Supplies Ltd",
    "Blue Harbor Trading",
    "Maple Leaf Office Goods",
    "Summit Tech Parts",
    "Greenfield Packaging",
]
CUSTOMER = "Sample Customer Inc."
CATALOG = [
    ("USB-C cable 1 m", Decimal("4.99")),
    ("Wireless mouse", Decimal("18.50")),
    ("Notebook A5", Decimal("3.25")),
    ("Desk lamp", Decimal("27.90")),
    ("Printer paper (500 sheets)", Decimal("7.80")),
    ("HDMI adapter", Decimal("12.40")),
    ("Laptop stand", Decimal("34.00")),
    ("Whiteboard markers (4 pack)", Decimal("6.15")),
]
TAX_RATE = Decimal("0.13")
CENT = Decimal("0.01")
TABLE_HEADER = ["Description", "Qty", "Unit Price", "Amount"]


@dataclass(frozen=True)
class LineItem:
    description: str
    quantity: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return (self.unit_price * self.quantity).quantize(CENT, ROUND_HALF_UP)


@dataclass(frozen=True)
class Invoice:
    number: str
    issue_date: date
    vendor: str
    customer: str
    items: tuple[LineItem, ...]

    @property
    def subtotal(self) -> Decimal:
        return sum((item.amount for item in self.items), Decimal("0.00"))

    @property
    def tax(self) -> Decimal:
        return (self.subtotal * TAX_RATE).quantize(CENT, ROUND_HALF_UP)

    @property
    def total(self) -> Decimal:
        return self.subtotal + self.tax


def money(value: Decimal) -> str:
    return f"${value:,.2f}"


def make_invoice(rng: random.Random, index: int) -> Invoice:
    """Build one random but reproducible invoice."""
    picked = rng.sample(CATALOG, k=rng.randint(2, 6))
    items = tuple(LineItem(name, rng.randint(1, 10), price) for name, price in picked)
    return Invoice(
        number=f"INV-2026-{index:04d}",
        issue_date=date(2026, 1, 5) + timedelta(days=rng.randint(0, 150)),
        vendor=rng.choice(VENDORS),
        customer=CUSTOMER,
        items=items,
    )


def render_invoice_pdf(invoice: Invoice, path: Path) -> None:
    """Write the invoice as a text-based PDF with a ruled item table."""
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=A4, title=f"Invoice {invoice.number}")

    story = [
        Paragraph(invoice.vendor, styles["Title"]),
        Paragraph("INVOICE", styles["Heading2"]),
        Paragraph(f"Invoice No: {invoice.number}", styles["Normal"]),
        Paragraph(f"Date: {invoice.issue_date.isoformat()}", styles["Normal"]),
        Paragraph(f"Bill To: {invoice.customer}", styles["Normal"]),
        Spacer(1, 8 * mm),
    ]

    rows = [TABLE_HEADER]
    for item in invoice.items:
        rows.append(
            [
                item.description,
                str(item.quantity),
                money(item.unit_price),
                money(item.amount),
            ]
        )
    table = Table(rows, colWidths=[85 * mm, 20 * mm, 35 * mm, 35 * mm])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]
        )
    )
    story += [table, Spacer(1, 6 * mm)]

    totals = Table(
        [
            ["Subtotal", money(invoice.subtotal)],
            [f"Tax ({TAX_RATE * 100:.0f}%)", money(invoice.tax)],
            ["Total", money(invoice.total)],
        ],
        colWidths=[40 * mm, 35 * mm],
        hAlign="RIGHT",
    )
    totals.setStyle(TableStyle([("ALIGN", (1, 0), (1, -1), "RIGHT")]))
    story.append(totals)
    doc.build(story)


def generate_samples(out_dir: Path, count: int = 5, seed: int = 42) -> list[Invoice]:
    """Create `count` sample invoice PDFs in `out_dir`. Returns the invoice data."""
    if count < 1:
        raise ValueError("count must be at least 1")
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    invoices = []
    for index in range(1, count + 1):
        invoice = make_invoice(rng, index)
        render_invoice_pdf(invoice, out_dir / f"invoice_{index:04d}.pdf")
        invoices.append(invoice)
    return invoices


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Generate fictional sample invoices (PDF).")
    parser.add_argument("out_dir", type=Path, help="folder for the generated PDFs")
    parser.add_argument("--count", type=int, default=5, help="number of invoices (default: 5)")
    parser.add_argument("--seed", type=int, default=42, help="random seed (default: 42)")
    args = parser.parse_args(argv)
    invoices = generate_samples(args.out_dir, args.count, args.seed)
    print(f"Created {len(invoices)} sample invoice(s) in {args.out_dir}")


if __name__ == "__main__":
    main()
