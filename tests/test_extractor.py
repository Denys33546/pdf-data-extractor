from datetime import date
from decimal import Decimal

import pytest

from pdf_extractor import extractor
from pdf_extractor.extractor import (
    extract_folder,
    extract_invoice,
    parse_invoice,
    parse_items,
    parse_money,
)
from pdf_extractor.sample_data import generate_samples

GOOD_TEXT = """Acme Parts
INVOICE
Invoice No: INV-9
Date: 2026-02-01
Bill To: Buyer Ltd
Subtotal $20.00
Tax (13%) $2.60
Total $22.60"""
HEADER = ["Description", "Qty", "Unit Price", "Amount"]
GOOD_TABLE = [HEADER, ["Widget", "2", "$10.00", "$20.00"]]


# ---------- the real thing: PDFs we generated, read back, compared with the truth ----------


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    folder = tmp_path_factory.mktemp("invoices")
    return folder, generate_samples(folder, count=5)


def as_rows(items):
    return [(i.description, i.quantity, i.unit_price, i.amount) for i in items]


def test_round_trip_matches_ground_truth(generated):
    folder, invoices = generated
    results = extract_folder(folder)
    assert len(results) == 5
    for result, truth in zip(results, invoices, strict=True):
        assert result.warnings == ()
        assert result.is_valid
        assert result.number == truth.number
        assert result.issue_date == truth.issue_date
        assert result.vendor == truth.vendor
        assert result.customer == truth.customer
        assert as_rows(result.items) == as_rows(truth.items)
        assert (result.subtotal, result.tax, result.total) == (
            truth.subtotal,
            truth.tax,
            truth.total,
        )


def test_extract_invoice_single_file(generated):
    folder, invoices = generated
    result = extract_invoice(folder / "invoice_0001.pdf")
    assert result.source == "invoice_0001.pdf"
    assert result.total == invoices[0].total


# ---------- parse_money ----------


def test_parse_money():
    assert parse_money("$1,234.50") == Decimal("1234.50")
    assert parse_money(" 7 ") == Decimal("7.00")


@pytest.mark.parametrize("text", ["", "abc", "NaN", "$"])
def test_parse_money_rejects_garbage(text):
    with pytest.raises(ValueError):
        parse_money(text)


# ---------- parse_invoice on hand-made input ----------


def test_good_input_has_no_warnings():
    result = parse_invoice(GOOD_TEXT, [GOOD_TABLE], "x.pdf")
    assert result.warnings == ()
    assert result.vendor == "Acme Parts"
    assert result.issue_date == date(2026, 2, 1)
    assert result.total == Decimal("22.60")


def test_missing_fields_are_reported():
    result = parse_invoice("Some Vendor\nhello", [GOOD_TABLE], "x.pdf")
    assert not result.is_valid
    joined = " | ".join(result.warnings)
    assert "Invoice number not found" in joined
    assert "Date not found" in joined
    assert "Total not found" in joined


def test_invalid_date_is_reported():
    text = GOOD_TEXT.replace("2026-02-01", "01/02/2026")
    result = parse_invoice(text, [GOOD_TABLE], "x.pdf")
    assert result.issue_date is None
    assert any("YYYY-MM-DD" in w for w in result.warnings)


def test_wrong_total_is_reported():
    text = GOOD_TEXT.replace("Total $22.60", "Total $99.00")
    result = parse_invoice(text, [GOOD_TABLE], "x.pdf")
    assert any("Subtotal + tax" in w for w in result.warnings)


def test_wrong_subtotal_is_reported():
    text = GOOD_TEXT.replace("Subtotal $20.00", "Subtotal $25.00")
    result = parse_invoice(text, [GOOD_TABLE], "x.pdf")
    assert any("Items add up" in w for w in result.warnings)


def test_wrong_line_amount_is_reported():
    table = [HEADER, ["Widget", "2", "$10.00", "$21.00"]]
    result = parse_invoice(GOOD_TEXT, [table], "x.pdf")
    assert any("Line 'Widget'" in w for w in result.warnings)


def test_unreadable_table_row_is_skipped_with_warning():
    table = [HEADER, ["Widget", "2", "$10.00", "$20.00"], ["Broken", "many", "?", "?"], [None] * 4]
    items, warnings = parse_items([table])
    assert len(items) == 1
    assert len(warnings) == 1 and "row 3" in warnings[0]


def test_wrapped_description_cells_are_cleaned():
    table = [HEADER, ["Printer\npaper  (500 sheets)", "1", "$7.80", "$7.80"]]
    items, _ = parse_items([table])
    assert items[0].description == "Printer paper (500 sheets)"


def test_missing_item_table_is_reported():
    items, warnings = parse_items([[["Other", "table"]], []])
    assert items == ()
    assert warnings == ["Item table not found"]


def test_scanned_pdf_without_text_is_explained():
    result = parse_invoice("   \n", [], "scan.pdf")
    assert result.warnings == (
        "No text found. This looks like a scanned PDF (OCR is not supported)",
    )


# ---------- files and folders ----------


def test_broken_pdf_does_not_crash(tmp_path):
    bad = tmp_path / "broken.pdf"
    bad.write_bytes(b"this is not a pdf")
    result = extract_invoice(bad)
    assert result.warnings and result.warnings[0].startswith("Could not read PDF")


def test_pdf_without_pages(tmp_path, monkeypatch):
    class EmptyPdf:
        pages = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(extractor.pdfplumber, "open", lambda path: EmptyPdf())
    assert extract_invoice(tmp_path / "x.pdf").warnings == ("PDF has no pages",)


def test_folder_skips_non_pdf_and_keeps_going_after_a_bad_file(tmp_path):
    generate_samples(tmp_path, count=2)
    (tmp_path / "notes.txt").write_text("not an invoice")
    (tmp_path / "broken.pdf").write_bytes(b"garbage")
    results = extract_folder(tmp_path)
    assert [r.source for r in results] == ["broken.pdf", "invoice_0001.pdf", "invoice_0002.pdf"]
    assert [r.is_valid for r in results] == [False, True, True]


def test_folder_must_exist(tmp_path):
    with pytest.raises(NotADirectoryError):
        extract_folder(tmp_path / "missing")


def test_vendor_is_none_when_text_has_only_the_word_invoice():
    assert parse_invoice("INVOICE", [], "x.pdf").vendor is None
