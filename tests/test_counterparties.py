# ABOUTME: Tests της οντότητας αντισυμβαλλόμενου: επικυρώσεις (πρώην Supplier.validate),
# ABOUTME: ensure χωρίς να πειράζει υπάρχοντα, defaults ανά direction, λίστα με πλήθη.
from datetime import date
import pytest
from esoda_exoda import counterparties as cp_mod
from esoda_exoda.counterparties import (Counterparty, ClassificationDefault, CounterpartyError,
                                        ensure_counterparty, find_by_vat, foreign_suppliers,
                                        get_counterparty, list_counterparties, save_counterparty,
                                        save_default, subtotal_parties, validate)

def _cp(tp, **kw):
    base = dict(id=None, taxpayer_id=tp.id, vat="NL999999003B01", country="NL",
                name="FOREIGN SUPPLIER A B.V.", postal_code="1017", city="Amsterdam")
    base.update(kw)
    return Counterparty(**base)

def test_ensure_δημιουργεί_μία_φορά_και_δεν_πειράζει_όνομα(db, taxpayer):
    a = ensure_counterparty(db, taxpayer.id, "090000113", name="ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ")
    b = ensure_counterparty(db, taxpayer.id, "090000113", name="ΑΛΛΟ ΟΝΟΜΑ")
    assert a == b
    assert find_by_vat(db, taxpayer.id, "090000113").name == "ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ"

def test_ensure_γεμίζει_κενό_όνομα_τη_δεύτερη_φορά(db, taxpayer):
    ensure_counterparty(db, taxpayer.id, "090000113")  # από βιβλίο, χωρίς όνομα
    ensure_counterparty(db, taxpayer.id, "090000113", name="ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ")  # από RequestDocs
    assert find_by_vat(db, taxpayer.id, "090000113").name == "ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ"

def test_ensure_βρίσκει_ξένο_vat_ανεξάρτητα_από_χώρα(db, taxpayer):
    save_counterparty(db, _cp(taxpayer))
    assert ensure_counterparty(db, taxpayer.id, "NL999999003B01") == find_by_vat(
        db, taxpayer.id, "NL999999003B01").id

def test_save_και_get_με_defaults(db, taxpayer):
    cid = save_counterparty(db, _cp(taxpayer))
    save_default(db, cid, "expense", "category2_3", "E3_585_010", True, "14.3")
    save_default(db, cid, "expense", "category2_3", "E3_585_010", False, "14.3")  # upsert
    cp = get_counterparty(db, cid)
    assert cp.defaults["expense"] == ClassificationDefault("expense", "category2_3",
                                                           "E3_585_010", False, "14.3")

def test_update_αλλάζει_όνομα_και_σημειώσεις(db, taxpayer):
    cid = save_counterparty(db, _cp(taxpayer))
    cp = get_counterparty(db, cid)
    save_counterparty(db, Counterparty(**{**cp.__dict__, "name": "FOREIGN SUPPLIER A", "notes": "VPN"}))
    again = get_counterparty(db, cid)
    assert (again.name, again.notes) == ("FOREIGN SUPPLIER A", "VPN")

@pytest.mark.parametrize("kw,λέξη", [
    (dict(country="GR", inv_type="14.3"), "GR"),
    (dict(country="US", inv_type="14.3"), "ΕΕ"),
    (dict(country="NL", inv_type="14.4"), "ΕΕ"),
    (dict(country="nl"), "ISO"),
    (dict(country="NLD"), "ISO"),
    (dict(name="FOREIGN\nSUPPLIER"), "ελέγχου"),
    (dict(name=""), "Κενό"),
])
def test_validate_αρνείται(taxpayer, kw, λέξη):
    inv_type = kw.pop("inv_type", "")
    cp = _cp(taxpayer, **kw)
    if inv_type:
        cp.defaults["expense"] = ClassificationDefault("expense", "category2_3",
                                                       "E3_585_010", True, inv_type)
    with pytest.raises(CounterpartyError) as e:
        validate(cp)
    assert λέξη in str(e.value)

def test_validate_δέχεται_ελληνικό_χωρίς_διεύθυνση(taxpayer):
    validate(Counterparty(id=None, taxpayer_id=taxpayer.id, vat="090000113",
                          name="ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ"))

def test_foreign_suppliers_μόνο_με_inv_type(db, taxpayer):
    a = save_counterparty(db, _cp(taxpayer))
    save_default(db, a, "expense", "category2_3", "E3_585_010", True, "14.3")
    save_counterparty(db, _cp(taxpayer, vat="US1", country="US", name="ACME"))
    out = foreign_suppliers(db, taxpayer.id)
    assert [(i, s.name, s.vat_classification) for i, s in out] == [(a, "FOREIGN SUPPLIER A B.V.", "VAT_365")]

def test_subtotal_parties(db, taxpayer):
    save_counterparty(db, Counterparty(id=None, taxpayer_id=taxpayer.id, vat="990000106",
                                       name="ΠΕΛΑΤΗΣ Α", separate_totals=True))
    ensure_counterparty(db, taxpayer.id, "1")
    assert subtotal_parties(db, taxpayer.id) == [("990000106", "ΠΕΛΑΤΗΣ Α")]

def test_list_βάζει_πρώτα_όσους_έχουν_έξοδα_χωρίς_default(db, taxpayer):
    with_default = ensure_counterparty(db, taxpayer.id, "A", name="Α")
    save_default(db, with_default, "expense", "category2_4", "E3_585_016", True)
    without = ensure_counterparty(db, taxpayer.id, "B", name="Β")
    # Seed με σκέτο SQL, χωρίς store_fetch/upsert_book_record (Task 5) — αλλιώς το commit
    # του Task 4 θα ήταν red μέχρι να υπάρξει το Task 5.
    f = db.execute("insert into mydata_fetch (taxpayer_id, method, date_from, date_to, body) "
                   "values (%s, 'RequestMyExpenses', '2026-01-01', '2026-12-31', '<x/>') returning id",
                   (taxpayer.id,)).fetchone()[0]
    db.execute("insert into invoice (taxpayer_id, mark, direction, issue_date, counterparty_id, "
               "first_seen_fetch_id, last_seen_fetch_id) "
               "values (%s, 'M1', 'expense', '2026-07-03', %s, %s, %s)", (taxpayer.id, without, f, f))
    rows = list_counterparties(db, taxpayer.id)
    assert [r["cp"].vat for r in rows] == ["B", "A"]
    assert rows[0]["invoices"] == 1 and rows[0]["last_date"] == date(2026, 7, 3)
    assert rows[0]["missing_default"] and not rows[1]["missing_default"]
