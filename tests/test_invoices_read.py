# ABOUTME: Tests των ερωτημάτων ανάγνωσης: «ισχύει τώρα» = νεότερο snapshot ανά (mark, source),
# ABOUTME: επίσημο ΦΠΑ ανά μήνα με έτος, ληφθέντα ως ReceivedDoc, next_aa από τη βάση.
from datetime import date
from esoda_exoda.classifications import SelfDeclared
from esoda_exoda.fetches import store_fetch
from esoda_exoda.invoices import (add_snapshot, current_expense_lines, invoices_in_range,
                                  official_vat_by_month, received_docs_of_month,
                                  self_declared_of_year, SelfDeclaredDoc, self_declared_since,
                                  upsert_book_record, upsert_received, upsert_self_declared)
from esoda_exoda.models import Record
from esoda_exoda.received import ReceivedDoc, VatLine
from esoda_exoda.transmit import next_aa

def _f(db, tp, method="RequestMyExpenses", y=2026):
    return store_fetch(db, tp.id, method, date(y, 1, 1), date(y, 12, 31), "")

def test_τρέχον_snapshot_είναι_το_νεότερο(db, taxpayer):
    f1, f2 = _f(db, taxpayer), _f(db, taxpayer)
    upsert_book_record(db, taxpayer.id, Record("090000113", date(2026, 7, 3), "1.1", 100, 24, 0, 124, "M1"), "expense", f1, None)
    add_snapshot(db, taxpayer.id, "M1", "e3_info", f1, date(2026, 7, 3),
                 lines=[("expense", "category2_3", "E3_585_009", 100.0)])
    add_snapshot(db, taxpayer.id, "M1", "e3_info", f2, date(2026, 7, 3),
                 lines=[("income", "category1_3", "E3_561_001", 5.0),
                        ("expense", "category2_4", "E3_585_016", 100.0)])
    [row] = invoices_in_range(db, taxpayer.id, 2026, 7)
    assert [(l.category, l.e3_type) for l in row.e3_lines] == [("category2_4", "E3_585_016")]
    assert row.transmitted is None and row.net == 100.0 and isinstance(row.net, float)

def test_ακύρωση_από_νεότερο_fetch_εξαφανίζει_τον_τρέχοντα(db, taxpayer):
    # Δύο RequestTransmittedDocs· το δεύτερο (νεότερο) ΔΕΝ φέρνει το M1 — η ΑΑΔΕ το ακύρωσε.
    f_old = store_fetch(db, taxpayer.id, "RequestTransmittedDocs", None, None, "")
    upsert_book_record(db, taxpayer.id, Record("1", date(2026, 7, 3), "1.1", 100, 24, 0, 124, "M1"), "expense", f_old, None)
    add_snapshot(db, taxpayer.id, "M1", "transmitted_docs", f_old, None,
                 lines=[("expense", "category2_4", "E3_585_016", None)])
    f_new = store_fetch(db, taxpayer.id, "RequestTransmittedDocs", None, None, "")
    db.execute("update mydata_fetch set fetched_at = fetched_at + interval '1 second' where id = %s", (f_new,))
    [row] = invoices_in_range(db, taxpayer.id, 2026, 7)
    assert row.transmitted is None  # το snapshot του f_old δεν είναι πια τρέχον

def test_transmitted_docs_φέρνει_kind(db, taxpayer):
    f = _f(db, taxpayer, "RequestMyIncome")
    upsert_book_record(db, taxpayer.id, Record("990000106", date(2026, 7, 1), "2.1", 500, 120, 100, 620, "I1"), "income", f, None)
    add_snapshot(db, taxpayer.id, "I1", "transmitted_docs", f, date(2026, 7, 1),
                 lines=[("income", "category1_3", "E3_561_001", None)])
    [row] = invoices_in_range(db, taxpayer.id, 2026)
    assert row.transmitted.kind == "income" and row.transmitted.e3_type == "E3_561_001"

def test_εύρος_έτους_και_μήνα_και_ταξινόμηση(db, taxpayer):
    f = _f(db, taxpayer)
    for mark, d, aa in (("A", date(2026, 7, 3), "2"), ("B", date(2026, 7, 3), "1"), ("C", date(2026, 8, 1), "1"), ("D", date(2025, 12, 31), "1")):
        upsert_book_record(db, taxpayer.id, Record("1", d, "1.1", 1, 0, 0, 1, mark), "expense", f, None)
        db.execute("update invoice set aa = %s where mark = %s", (aa, mark))
    assert [r.mark for r in invoices_in_range(db, taxpayer.id, 2026)] == ["B", "A", "C"]
    assert [r.mark for r in invoices_in_range(db, taxpayer.id, 2026, 8)] == ["C"]

def test_official_vat_ανά_μήνα_με_έτος(db, taxpayer):
    f1, f2 = _f(db, taxpayer, "RequestVatInfo"), _f(db, taxpayer, "RequestVatInfo")
    add_snapshot(db, taxpayer.id, "X", "vat_info", f1, date(2026, 7, 3), codes={"Vat333": 100.0})
    add_snapshot(db, taxpayer.id, "X", "vat_info", f2, date(2026, 7, 3), codes={"Vat333": 327.6, "Vat386": 27.6})
    add_snapshot(db, taxpayer.id, "Y", "vat_info", f2, date(2026, 7, 9), codes={"Vat386": 1.0})
    add_snapshot(db, taxpayer.id, "Z", "vat_info", f2, date(2025, 7, 9), codes={"Vat333": 999.0})
    assert official_vat_by_month(db, taxpayer.id, 2026) == {7: {"Vat333": 327.6, "Vat386": 28.6}}

def test_received_docs_γυρίζουν_ως_ReceivedDoc(db, taxpayer):
    f = _f(db, taxpayer, "RequestDocs")
    doc = ReceivedDoc(mark="M1", issuer_vat="090000113", issuer_name="Π ΟΕ", counterpart_vat="123456783",
                      series="Α", aa="42", date=date(2026, 7, 3), inv_type="1.1", fuel_invoice=True,
                      net=100.0, vat=24.0, other_taxes=1.0, stamp_duty=0.0, fees=0.0,
                      lines=[VatLine(60.0, 1, 14.4, None, 1), VatLine(40.0, 1, 9.6, 7, 2)])
    upsert_received(db, taxpayer.id, doc, f, None)
    upsert_book_record(db, taxpayer.id, Record("1", date(2026, 7, 5), "1.1", 1, 0, 0, 1, "ΧΩΡΙΣ_DOC"), "expense", f, None)
    [got] = received_docs_of_month(db, taxpayer.id, 2026, 7)
    assert got == doc

def test_current_expense_lines_μόνο_category2(db, taxpayer):
    f = _f(db, taxpayer, "RequestE3Info")
    add_snapshot(db, taxpayer.id, "M1", "e3_info", f, date(2026, 7, 3),
                 lines=[("income", "category1_3", "E3_561_001", 5.0), ("expense", "category2_4", "E3_585_016", 100.0)])
    add_snapshot(db, taxpayer.id, "M2", "e3_info", f, date(2026, 7, 3),
                 lines=[("income", "category1_3", "E3_561_001", 5.0)])
    out = current_expense_lines(db, taxpayer.id, ["M1", "M2", "M3"])
    assert list(out) == ["M1"] and out["M1"][0].e3_type == "E3_585_016" and out["M1"][0].value == 100.0

def test_self_declared_of_year_τρέφει_το_next_aa(db, taxpayer):
    f = _f(db, taxpayer, "RequestTransmittedDocs")
    for aa, y in (("3", 2026), ("9", 2025)):
        upsert_self_declared(db, taxpayer.id, SelfDeclared(mark=f"S{aa}{y}", uid="", inv_type="17.2", series="0", aa=aa,
                             date=date(y, 12, 31), net=1, vat=0, e3_type="E3_587", category="category2_8"), f, None)
    assert next_aa(self_declared_of_year(db, taxpayer.id, 2026), "17.2", 2026) == 4

def test_self_declared_since_φέρνει_ό_τι_χρειάζονται_οι_έλεγχοι(db, taxpayer):
    f = _f(db, taxpayer, "RequestTransmittedDocs")
    for mark, d, cancelled_by in (("S0", date(2025, 8, 31), ""), ("S1", date(2025, 9, 1), ""),
                                  ("S2", date(2026, 7, 28), "C1")):
        upsert_self_declared(db, taxpayer.id, SelfDeclared(
            mark=mark, uid="", inv_type="13.3", series="123456783", aa="8000000010", date=d,
            net=12, vat=0, e3_type="E3_585_016", category="category2_3",
            cancelled_by=cancelled_by, issuer_vat="090000113"), f, None)
    out = self_declared_since(db, taxpayer.id, date(2025, 9, 1))
    assert out == [
        SelfDeclaredDoc("13.3", "123456783", "8000000010", date(2025, 9, 1), 12.0, "090000113", False),
        SelfDeclaredDoc("13.3", "123456783", "8000000010", date(2026, 7, 28), 12.0, "090000113", True)]
    assert isinstance(out[0].net, float)
