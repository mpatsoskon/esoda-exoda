# ABOUTME: Tests ανάγνωσης φύλλων ΕΣΟΔΑ/ΕΞΟΔΑ — κανονικοποίηση legacy τιμών
# ABOUTME: (λατινικό NAI/OXI στη στήλη ΕΚΠΙΠΤΕΙ ΤΟ ΦΠΑ) σε ελληνικά ΝΑΙ/ΌΧΙ.
from datetime import date
import openpyxl
from esoda_exoda.excel_sheets import read_sheet, write_sheet
from esoda_exoda.models import SheetRow

def _legacy_expense_book(path, col_j_values):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "ΕΞΟΔΑ"
    ws.append(["", "ΤΥΠΟΣ", "Σειρά", "ΑΑ", "ΗΜ/ΝΙΑ", "ΑΦΜ", "ΚΑΘ. ΑΞΙΑ",
               "ΦΠΑ", "ΣΥΝΟΛΟ", "ΕΚΠΙΠΤΕΙ ΤΟ ΦΠΑ", "ΧΑΡΑΚΤ.", "Κατηγορία", "Είδος"])
    for n, v in enumerate(col_j_values, start=1):
        ws.append([n, "1.1 Τιμολόγιο", "", "", date(2025, 1, 10), "090000125",
                   100.0, 24.0, 124.0, v, "ΝΑΙ", "2.3", "Λοιπά"])
    wb.save(path)

def test_expense_totals_formulas():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    rows = [SheetRow("1.1 Τ", "", "", date(2025, 1, 5), "090000125",
                     100.0, 24.0, 124.0, cj, "ΝΑΙ", "2.3", "Λοιπά έξοδα (E3_585_016)")
            for cj in ("ΝΑΙ", "ΌΧΙ")]
    write_sheet(wb, "ΕΞΟΔΑ", rows)
    ws = wb["ΕΞΟΔΑ"]
    assert ws["G5"].value == "=SUM(G2:G3)"          # ΣΥΝΟΛΑ
    assert ws["A6"].value == "ΣΥΝΟΛΑ ΜΕ ΕΚΠΙΠΤΩΜΕΝΟ ΦΠΑ"
    assert ws["G6"].value == "=SUM(G2:G3)"           # καθαρή αξία: πάντα πλήρες SUM
    assert ws["H6"].value == '=SUMIF(J2:J3,"ΝΑΙ",H2:H3)'

def test_write_sheet_zero_rows_keeps_ranges_forward():
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    write_sheet(wb, "ΕΞΟΔΑ", [])
    ws = wb["ΕΞΟΔΑ"]
    assert ws["G4"].value == "=SUM(G2:G2)"           # όχι ανάποδο G2:G1
    assert ws["H5"].value == '=SUMIF(J2:J2,"ΝΑΙ",H2:H2)'

def test_υποσύνολα_ανά_αντισυμβαλλόμενο_και_λοιπά():
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    rows = [SheetRow("1.1", "", "", date(2026, 7, 1), "990000106", 100, 24, 124, 0, "ΝΑΙ", "c", "k"),
            SheetRow("1.1", "", "", date(2026, 7, 2), "5", 10, 2.4, 12.4, 0, "ΝΑΙ", "c", "k")]
    write_sheet(wb, "ΕΣΟΔΑ", rows, [("990000106", "ΠΕΛΑΤΗΣ Α"), ("5", "ΑΛΛΟΣ")])
    ws = wb["ΕΣΟΔΑ"]
    labels = [ws.cell(row=r, column=1).value for r in range(5, 9)]
    assert labels == ["ΣΥΝΟΛΑ", "ΣΥΝΟΛΑ ΠΕΛΑΤΗΣ Α (ΑΦΜ 990000106)", "ΣΥΝΟΛΑ ΑΛΛΟΣ (ΑΦΜ 5)", "ΣΥΝΟΛΑ ΛΟΙΠΑ"]
    assert ws.cell(row=6, column=7).value == '=SUMIF(F2:F3,"990000106",G2:G3)'
    assert ws.cell(row=8, column=7).value == "=G5-G6-G7"

def test_χωρίς_parties_δεν_γράφει_υποσύνολα():
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    write_sheet(wb, "ΕΣΟΔΑ", [], [])
    assert wb["ΕΣΟΔΑ"].cell(row=5, column=1).value is None

def test_read_sheet_normalizes_latin_nai_oxi(tmp_path):
    p = tmp_path / "legacy.xlsx"
    _legacy_expense_book(p, ["NAI", "OXI", "ΝΑΙ", "ΌΧΙ"])  # τα δύο πρώτα λατινικά
    rows = read_sheet(p, "ΕΞΟΔΑ")
    assert [r.col_j for r in rows] == ["ΝΑΙ", "ΌΧΙ", "ΝΑΙ", "ΌΧΙ"]
