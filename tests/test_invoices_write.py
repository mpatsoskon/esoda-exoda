# ABOUTME: Tests των upserts ανά MARK: κάθε πηγή συμπληρώνει μόνο τις στήλες της,
# ABOUTME: τίποτα δεν διαγράφεται, τα snapshots χαρακτηρισμού μόνο προστίθενται.
from datetime import date
from esoda_exoda.classifications import SelfDeclared
from esoda_exoda.fetches import store_fetch
from esoda_exoda.invoices import (add_snapshot, set_headers, upsert_book_record,
                                  upsert_received, upsert_self_declared)
from esoda_exoda.models import Record
from esoda_exoda.received import ReceivedDoc, VatLine

def _fetch(db, tp, method="RequestMyExpenses"):
    return store_fetch(db, tp.id, method, date(2026, 7, 1), date(2026, 7, 31), "")

def _doc(mark="M1", **kw):
    base = dict(mark=mark, issuer_vat="090000113", issuer_name="ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ",
                counterpart_vat="123456783", series="Α", aa="42", date=date(2026, 7, 3),
                inv_type="1.1", fuel_invoice=False, net=100.0, vat=24.0, other_taxes=0,
                stamp_duty=0, fees=0, lines=[VatLine(100.0, 1, 24.0, None, 1)])
    base.update(kw)
    return ReceivedDoc(**base)

def _row(db, mark):
    return db.execute(
        "select direction, inv_type, series, aa, issuer_vat, issuer_name, counterpart_vat, "
        "net, vat, withheld, in_book, received, self_declared, uid, cancelled_by_mark, "
        "first_seen_fetch_id, last_seen_fetch_id from invoice where mark = %s", (mark,)).fetchone()

def test_βιβλίο_μετά_RequestDocs_συμπληρώνουν_την_ίδια_γραμμή(db, taxpayer):
    f1 = _fetch(db, taxpayer)
    rec = Record("090000113", date(2026, 7, 3), "1.1", 100, 24, 0, 124, "M1")
    assert upsert_book_record(db, taxpayer.id, rec, "expense", f1, None) is True
    f2 = _fetch(db, taxpayer, "RequestDocs")
    assert upsert_received(db, taxpayer.id, _doc(), f2, None) is False
    r = _row(db, "M1")
    assert r[0] == "expense" and r[2:4] == ("Α", "42") and r[5] == "ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ"
    assert (r[10], r[11]) == (True, True) and (r[15], r[16]) == (f1, f2)
    assert float(r[7]) == 100.0
    n = db.execute("select count(*) from invoice where mark = 'M1'").fetchone()[0]
    assert n == 1

def test_RequestDocs_πρώτα_μετά_βιβλίο(db, taxpayer):
    f = _fetch(db, taxpayer, "RequestDocs")
    upsert_received(db, taxpayer.id, _doc(), f, None)
    assert _row(db, "M1")[10] is False
    upsert_book_record(db, taxpayer.id, Record("090000113", date(2026, 7, 3), "1.1", 100, 24, 0, 124, "M1"),
                       "expense", _fetch(db, taxpayer), None)
    r = _row(db, "M1")
    assert r[10] is True and r[2:4] == ("Α", "42")  # η σειρά/ΑΑ του RequestDocs έμεινε

def test_γραμμές_ΦΠΑ_αντικαθίστανται_σε_κάθε_λήψη(db, taxpayer):
    f = _fetch(db, taxpayer, "RequestDocs")
    upsert_received(db, taxpayer.id, _doc(), f, None)
    upsert_received(db, taxpayer.id, _doc(lines=[VatLine(50, 1, 12, None, 1), VatLine(50, 1, 12, None, 2)]), f, None)
    n = db.execute("select count(*) from invoice_line").fetchone()[0]
    assert n == 2

def test_αυτο_δηλωθέν_και_ακύρωση(db, taxpayer):
    f = _fetch(db, taxpayer, "RequestTransmittedDocs")
    sd = SelfDeclared(mark="M9", uid="U9", inv_type="17.2", series="0", aa="1",
                      date=date(2026, 12, 31), net=1250.40, vat=0.0, e3_type="E3_587",
                      category="category2_8", cancelled_by="", issuer_vat="123456783")
    assert upsert_self_declared(db, taxpayer.id, sd, f, None) is True
    sd.cancelled_by = "M10"
    upsert_self_declared(db, taxpayer.id, sd, f, None)
    r = _row(db, "M9")
    assert r[12] is True and r[13] == "U9" and r[14] == "M10" and r[0] == "expense"

def test_set_headers_μόνο_για_υπάρχοντα(db, taxpayer):
    f = _fetch(db, taxpayer, "RequestMyIncome")
    upsert_book_record(db, taxpayer.id, Record("990000106", date(2026, 7, 1), "2.1", 500, 120, 100, 620, "I1"),
                       "income", f, None)
    set_headers(db, taxpayer.id, {"I1": ("Β", "7"), "ΑΓΝΩΣΤΟ": ("Χ", "1")})
    r = _row(db, "I1")
    assert r[2:4] == ("Β", "7") and float(r[9]) == 100.0
    assert _row(db, "ΑΓΝΩΣΤΟ") is None

def test_snapshot_με_γραμμές_και_κωδικούς(db, taxpayer):
    f = _fetch(db, taxpayer, "RequestE3Info")
    s1 = add_snapshot(db, taxpayer.id, "M1", "e3_info", f, date(2026, 7, 3),
                      lines=[("expense", "category2_4", "E3_585_016", 100.0)])
    s2 = add_snapshot(db, taxpayer.id, "M1", "vat_info", f, date(2026, 7, 3),
                      codes={"Vat366": 115.0, "Vat386": 27.6})
    assert s1 != s2
    lines = db.execute("select kind, category, e3_type, value from classification_line").fetchall()
    assert [(l[0], l[1], l[2], float(l[3])) for l in lines] == [("expense", "category2_4", "E3_585_016", 100.0)]
    codes = dict(db.execute("select code, value from vat_code_line").fetchall())
    assert {k: float(v) for k, v in codes.items()} == {"Vat366": 115.0, "Vat386": 27.6}
