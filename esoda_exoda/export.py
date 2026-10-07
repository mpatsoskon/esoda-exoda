# ABOUTME: Excel κατ' απαίτηση από τη βάση: ΕΣΟΔΑ/ΕΞΟΔΑ/Ε3/ΦΠΑ με τους υπάρχοντες writers,
# ABOUTME: σε bytes. Κανένα αρχείο δεν γράφεται στο δίσκο.
import dataclasses
import io
import openpyxl
from . import vat
from .books_query import book_rows
from .counterparties import subtotal_parties
from .e3 import write_e3_sheet
from .excel_sheets import write_sheet
from .invoices import official_vat_by_month
from .taxpayers import Taxpayer

def build_workbook(conn, cfg, taxpayer: Taxpayer, year: int, month: int | None = None):
    income, expenses = book_rows(conn, cfg, taxpayer, year, month)
    official = official_vat_by_month(conn, taxpayer.id, year)
    if month:
        official = {m: c for m, c in official.items() if m == month}
    parties = subtotal_parties(conn, taxpayer.id)
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    n_inc = write_sheet(wb, "ΕΣΟΔΑ", income, parties)
    n_exp = write_sheet(wb, "ΕΞΟΔΑ", expenses, parties)
    write_e3_sheet(wb, n_inc, n_exp)
    months = vat.compute(income, expenses, official)
    vat.write_vat_sheet(wb, months)
    buf = io.BytesIO(); wb.save(buf)
    summary = {"ΕΣΟΔΑ": {"rows": len(income), "net": round(sum(r.net for r in income), 2),
                         "vat": round(sum(r.vat for r in income), 2)},
               "ΕΞΟΔΑ": {"rows": len(expenses), "net": round(sum(r.net for r in expenses), 2),
                         "vat": round(sum(r.vat for r in expenses), 2)},
               "ΦΠΑ": [dataclasses.asdict(v) for v in months]}
    other = vat.unknown_codes(official)
    if other:
        summary["ΦΠΑ_λοιποί_κωδικοί"] = other
    return buf.getvalue(), summary
