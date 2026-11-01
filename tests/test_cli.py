import runpy
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import load_workbook

from pdf_extractor import __version__
from pdf_extractor.cli import format_summary, main
from pdf_extractor.extractor import ExtractedInvoice
from pdf_extractor.sample_data import generate_samples

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def pdf_folder(tmp_path):
    folder = tmp_path / "invoices"
    generate_samples(folder, count=3)
    return folder


def add_broken_pdf(folder):
    (folder / "broken.pdf").write_bytes(b"this is not a pdf")


# ---------- happy paths ----------


def test_folder_to_excel(pdf_folder, tmp_path, capsys):
    output = tmp_path / "reports" / "report.xlsx"
    assert main([str(pdf_folder), "-o", str(output)]) == 0

    workbook = load_workbook(output)
    assert workbook["Invoices"].max_row == 4  # header + 3 invoices
    text = capsys.readouterr().out
    assert "Processed 3 invoice(s): 3 OK, 0 need review" in text
    assert f"Report written to: {output}" in text


def test_single_file_input(pdf_folder, tmp_path, capsys):
    output = tmp_path / "one.xlsx"
    assert main([str(pdf_folder / "invoice_0002.pdf"), "-o", str(output)]) == 0
    assert load_workbook(output)["Invoices"].max_row == 2
    assert "Processed 1 invoice(s)" in capsys.readouterr().out


def test_csv_output_creates_two_files(pdf_folder, tmp_path, capsys):
    output = tmp_path / "data.csv"
    assert main([str(pdf_folder), "-o", str(output)]) == 0
    assert (tmp_path / "data_invoices.csv").exists()
    assert (tmp_path / "data_items.csv").exists()
    text = capsys.readouterr().out
    assert "data_invoices.csv" in text and "data_items.csv" in text


def test_default_output_path(pdf_folder, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main([str(pdf_folder)]) == 0
    assert (tmp_path / "output" / "report.xlsx").exists()


def test_uppercase_extension_is_accepted(pdf_folder, tmp_path):
    assert main([str(pdf_folder), "-o", str(tmp_path / "REPORT.XLSX")]) == 0


# ---------- problems in the data ----------


def test_problem_files_are_listed_and_exit_code_stays_zero(pdf_folder, tmp_path, capsys):
    add_broken_pdf(pdf_folder)
    assert main([str(pdf_folder), "-o", str(tmp_path / "r.xlsx")]) == 0
    text = capsys.readouterr().out
    assert "3 OK, 1 need review" in text
    assert "Needs review:" in text
    assert "broken.pdf" in text
    assert "Could not read PDF" in text


def test_strict_mode_fails_when_something_needs_review(pdf_folder, tmp_path):
    add_broken_pdf(pdf_folder)
    assert main([str(pdf_folder), "-o", str(tmp_path / "r.xlsx"), "--strict"]) == 1


def test_strict_mode_passes_when_everything_is_fine(pdf_folder, tmp_path):
    assert main([str(pdf_folder), "-o", str(tmp_path / "r.xlsx"), "--strict"]) == 0


def test_report_is_still_written_when_some_files_are_bad(pdf_folder, tmp_path):
    add_broken_pdf(pdf_folder)
    output = tmp_path / "r.xlsx"
    main([str(pdf_folder), "-o", str(output)])
    sheet = load_workbook(output)["Invoices"]
    assert sheet.max_row == 5
    statuses = {sheet.cell(row=row, column=9).value for row in range(2, 6)}
    assert statuses == {"OK", "CHECK"}


# ---------- errors ----------


def test_unsupported_output_extension(pdf_folder, tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([str(pdf_folder), "-o", str(tmp_path / "report.txt")])
    assert exit_info.value.code == 2
    assert ".xlsx or .csv" in capsys.readouterr().err


def test_missing_input(tmp_path, capsys):
    with pytest.raises(SystemExit) as exit_info:
        main([str(tmp_path / "nope"), "-o", str(tmp_path / "r.xlsx")])
    assert exit_info.value.code == 2
    assert "input not found" in capsys.readouterr().err


def test_folder_without_pdfs(tmp_path, capsys):
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main([str(empty), "-o", str(tmp_path / "r.xlsx")]) == 1
    assert "No PDF files found" in capsys.readouterr().err


def test_report_cannot_be_written(pdf_folder, tmp_path, capsys):
    blocker = tmp_path / "blocker"
    blocker.write_text("I am a file, not a folder")
    assert main([str(pdf_folder), "-o", str(blocker / "report.xlsx")]) == 1
    assert "Could not write the report" in capsys.readouterr().err


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--version"])
    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


# ---------- the printed summary ----------


def test_format_summary_lists_problems_and_outputs():
    ok = ExtractedInvoice("ok.pdf", "INV-1", None, "V", "C", (), None, None, None, ())
    bad = ExtractedInvoice(
        "bad.pdf",
        None,
        None,
        None,
        None,
        (),
        None,
        None,
        None,
        ("Total not found", "Date not found"),
    )
    text = format_summary([ok, bad], [Path("out/report.xlsx")])
    assert text.splitlines() == [
        "Processed 2 invoice(s): 1 OK, 1 need review",
        "Total of all invoices: 0.00",
        "Needs review:",
        "  bad.pdf",
        "    - Total not found",
        "    - Date not found",
        "Report written to: out/report.xlsx",
    ]


# ---------- running it the way users do ----------


def test_python_dash_m_entry_point_in_process(pdf_folder, tmp_path, monkeypatch):
    output = tmp_path / "r.xlsx"
    monkeypatch.setattr(sys, "argv", ["pdf_extractor", str(pdf_folder), "-o", str(output)])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("pdf_extractor", run_name="__main__")
    assert exit_info.value.code == 0
    assert output.exists()


def test_python_dash_m_as_a_real_subprocess(pdf_folder, tmp_path):
    output = tmp_path / "r.xlsx"
    result = subprocess.run(
        [sys.executable, "-m", "pdf_extractor", str(pdf_folder), "-o", str(output)],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "Processed 3 invoice(s): 3 OK, 0 need review" in result.stdout
    assert output.exists()
