# ABOUTME: Tests ενορχήστρωσης της ανανέωσης πάνω στα fixtures Ιουλίου 2026: idempotent
# ABOUTME: upserts, snapshots ανά λήψη, αντισυμβαλλόμενοι με όνομα, rollback στη μέση.
from datetime import date
from urllib.error import HTTPError
import pytest
from esoda_exoda import db as db_mod
from esoda_exoda.fetches import refresh_dates
from esoda_exoda.invoices import invoices_in_range, received_docs_of_month
from esoda_exoda.counterparties import find_by_vat
from esoda_exoda.refresh import month_range, refresh, year_range

def _fixture_fetch(fixtures_dir):
    files = {"RequestMyIncome": "mydata_income_2025.xml", "RequestMyExpenses": "mydata_expenses_2025.xml",
             "RequestTransmittedDocs": "mydata_transmitted_sample.xml", "RequestDocs": "mydata_received_sample.xml",
             "RequestE3Info": "mydata_e3_info_2026_07.xml", "RequestVatInfo": "mydata_vat_info_2026_07.xml"}
    calls = []
    def fetch_xml(method, df, dt):
        calls.append((method, df, dt))
        return (fixtures_dir / files[method]).read_text(encoding="utf-8")
    fetch_xml.calls = calls
    return fetch_xml

def test_ranges():
    assert month_range(2026, 2) == ("01/02/2026", "28/02/2026")
    assert year_range(2026) == ("01/01/2026", "31/12/2026")

def test_refresh_κάνει_έξι_κλήσεις_και_γράφει_τα_ωμά(db, taxpayer, fixtures_dir):
    fx = _fixture_fetch(fixtures_dir)
    out = refresh(db, taxpayer, 2026, 7, fetch_xml=fx)
    assert [c[0] for c in fx.calls] == ["RequestMyIncome", "RequestMyExpenses", "RequestTransmittedDocs",
                                        "RequestDocs", "RequestE3Info", "RequestVatInfo"]
    assert fx.calls[0][1:] == ("01/07/2026", "31/07/2026")
    n = db.execute("select count(*) from mydata_fetch").fetchone()[0]
    assert n == 6 and out["snapshots"] > 0 and out["new_invoices"] > 0
    assert refresh_dates(db, taxpayer.id, 2026) .keys() == {7}

def test_δεύτερο_refresh_δεν_διπλασιάζει_παραστατικά_αλλά_προσθέτει_snapshots(db, taxpayer, fixtures_dir):
    fx = _fixture_fetch(fixtures_dir)
    a = refresh(db, taxpayer, 2026, 7, fetch_xml=fx)
    inv1 = db.execute("select count(*) from invoice").fetchone()[0]
    snap1 = db.execute("select count(*) from classification_snapshot").fetchone()[0]
    b = refresh(db, taxpayer, 2026, 7, fetch_xml=fx)
    inv2 = db.execute("select count(*) from invoice").fetchone()[0]
    snap2 = db.execute("select count(*) from classification_snapshot").fetchone()[0]
    assert inv1 == inv2 and snap2 == 2 * snap1
    assert b["new_invoices"] == 0 and b["seen_invoices"] == a["new_invoices"] + a["seen_invoices"]
    assert b["new_counterparties"] == 0

def test_αντισυμβαλλόμενος_παίρνει_όνομα_από_το_RequestDocs(db, taxpayer, fixtures_dir):
    refresh(db, taxpayer, 2026, 7, fetch_xml=_fixture_fetch(fixtures_dir))
    docs = received_docs_of_month(db, taxpayer.id, 2026, 7)
    named = next(d for d in docs if d.issuer_name)
    assert find_by_vat(db, taxpayer.id, named.issuer_vat).name == named.issuer_name
    [row] = [r for r in invoices_in_range(db, taxpayer.id, 2026, 7) if r.mark == named.mark]
    assert row.counterparty_id == find_by_vat(db, taxpayer.id, named.issuer_vat).id

def test_χαρακτηρισμοί_E3Info_φτάνουν_στις_γραμμές(db, taxpayer, fixtures_dir):
    refresh(db, taxpayer, 2026, 7, fetch_xml=_fixture_fetch(fixtures_dir))
    rows = invoices_in_range(db, taxpayer.id, 2026, 7)
    assert any(r.e3_lines for r in rows)

def test_σφάλμα_στην_πέμπτη_κλήση_αφήνει_τη_βάση_άθικτη(db, db_cfg, taxpayer, fixtures_dir):
    fx = _fixture_fetch(fixtures_dir)
    def broken(method, df, dt):
        if method == "RequestE3Info":
            raise HTTPError("u", 429, "Too Many Requests", {}, None)
        return fx(method, df, dt)
    with pytest.raises(HTTPError):
        with db_mod.connect(db_cfg) as conn:
            refresh(conn, taxpayer, 2026, 7, fetch_xml=broken)
    assert db.execute("select count(*) from mydata_fetch").fetchone()[0] == 0
    assert db.execute("select count(*) from invoice").fetchone()[0] == 0
