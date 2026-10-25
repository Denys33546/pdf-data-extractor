import random
from datetime import date
from decimal import Decimal

import pdfplumber
import pytest

from pdf_extractor.sample_data import (
    TABLE_HEADER,
    Invoice,
    LineItem,
    generate_samples,
    main,
    make_invoice,
    money,
)


def test_totals_use_exact_decimal_math():
    invoice = Invoice(
        number="INV-1",
        issue_date=date(2026, 1, 1),
        vendor="V",
        customer="C",
        items=(
            LineItem("A", 3, Decimal("4.99")),  # 14.97
            LineItem("B", 2, Decimal("18.50")),  # 37.00
        ),
    )
    assert invoice.subtotal == Decimal("51.97")
    assert invoice.tax == Decimal("6.76")  # 6.7561 rounded half up
    assert invoice.total == Decimal("58.73")


def test_money_format():
    assert money(Decimal("1234.5")) == "$1,234.50"


def test_make_invoice_is_reproducible_for_same_seed():
    first = make_invoice(random.Random(7), 1)
    second = make_invoice(random.Random(7), 1)
    assert first == second


def test_generate_samples_creates_pdf_files(tmp_path):
    invoices = generate_samples(tmp_path, count=3)
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == ["invoice_0001.pdf", "invoice_0002.pdf", "invoice_0003.pdf"]
    assert len(invoices) == 3
    assert all(p.read_bytes().startswith(b"%PDF") for p in tmp_path.iterdir())


def test_generated_pdf_has_extractable_text(tmp_path):
    invoice = generate_samples(tmp_path, count=1)[0]
    with pdfplumber.open(tmp_path / "invoice_0001.pdf") as pdf:
        text = pdf.pages[0].extract_text()
    assert invoice.number in text
    assert invoice.vendor in text
    assert f"Date: {invoice.issue_date.isoformat()}" in text
    assert money(invoice.total) in text


def test_generated_pdf_contains_a_detectable_table(tmp_path):
    invoice = generate_samples(tmp_path, count=1)[0]
    with pdfplumber.open(tmp_path / "invoice_0001.pdf") as pdf:
        table = pdf.pages[0].extract_table()
    assert table[0] == TABLE_HEADER
    assert len(table) == len(invoice.items) + 1
    assert table[1][0] == invoice.items[0].description


def test_count_must_be_positive(tmp_path):
    with pytest.raises(ValueError):
        generate_samples(tmp_path, count=0)


def test_cli_creates_files_and_reports(tmp_path, capsys):
    main([str(tmp_path / "out"), "--count", "2"])
    assert len(list((tmp_path / "out").glob("*.pdf"))) == 2
    assert "Created 2 sample invoice(s)" in capsys.readouterr().out
