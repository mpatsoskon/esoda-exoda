# ABOUTME: Tests του κλειδώματος εγγραφής (BEGIN IMMEDIATE) πριν από κάθε αμετάκλητο POST:
# ABOUTME: αν η βάση είναι πιασμένη, η διαβίβαση και οι χαρακτηρισμοί σταματούν πριν φύγει αίτημα.
import sqlite3
import pytest
from esoda_exoda import db as db_mod
from esoda_exoda.web import app as web_app
from esoda_exoda.web import classify_routes

XML_172 = ('<InvoicesDoc><invoice><invoiceHeader><series>0</series><aa>1</aa>'
           '<issueDate>2026-12-31</issueDate><invoiceType>17.2</invoiceType></invoiceHeader>'
           '<invoiceSummary><totalNetValue>1250.40</totalNetValue></invoiceSummary></invoice>'
           '</InvoicesDoc>')
XML_CLS = ('<ExpensesClassificationsDoc><expensesInvoiceClassification><invoiceMark>900000000000003'
           '</invoiceMark><invoiceClassificationDetails><expensesClassificationDetailData>'
           '<classificationType>E3_585_016</classificationType><classificationCategory>category2_4'
           '</classificationCategory><amount>10.00</amount></expensesClassificationDetailData>'
           '</invoiceClassificationDetails></expensesInvoiceClassification>'
           '</ExpensesClassificationsDoc>')

@pytest.fixture
def busy(db, db_conn_factory, monkeypatch):
    """Άλλη σύνδεση κρατά κλείδωμα εγγραφής, όπως μια ανανέωση σε εξέλιξη."""
    monkeypatch.setattr(db_mod, "BUSY_TIMEOUT", 0.05)
    holder = db_conn_factory()
    holder.execute("begin immediate")
    yield holder
    holder.rollback()
    holder.close()

def _can_write(db_cfg) -> bool:
    other = db_mod.open_db(db_cfg.db_path(), timeout=0)
    try:
        other.execute("begin immediate")
        other.rollback()
        return True
    except sqlite3.OperationalError:
        return False
    finally:
        other.close()

def test_διαβίβαση_σταματά_πριν_το_POST_αν_η_βάση_είναι_πιασμένη(monkeypatch, db, db_cfg, taxpayer, busy):
    sent = []
    monkeypatch.setattr(web_app, "send_invoices", lambda x, *, env: sent.append(x))
    body, status = web_app.submit_invoice(db_cfg, taxpayer, XML_172, 2026)
    assert sent == [] and status == 503
    assert "ΔΕΝ στάλθηκε" in body["error"]

def test_χαρακτηρισμοί_σταματούν_πριν_το_POST_αν_η_βάση_είναι_πιασμένη(monkeypatch, db, db_cfg, taxpayer, busy):
    sent = []
    monkeypatch.setattr(classify_routes, "send_expenses_classification",
                        lambda x, per_invoice=True, *, env: sent.append(x))
    body, status = classify_routes.submit_classifications(db_cfg, taxpayer, 2026, 7, XML_CLS)
    assert sent == [] and status == 503
    assert "ΔΕΝ στάλθηκαν" in body["error"]

def test_η_διαβίβαση_κρατά_το_κλείδωμα_όσο_στέλνει(monkeypatch, db, db_cfg, taxpayer):
    seen = []
    def send(x, *, env):
        seen.append(_can_write(db_cfg))
        return {"mark": "900000000000011", "uid": "U", "response_xml": ""}
    monkeypatch.setattr(web_app, "send_invoices", send)
    monkeypatch.setattr(web_app, "refresh", lambda *a, **k: None)
    body, status = web_app.submit_invoice(db_cfg, taxpayer, XML_172, 2026)
    assert seen == [False]  # κανείς άλλος δεν γράφει όσο φεύγει το POST
    assert _can_write(db_cfg)  # και ελευθερώνεται μετά
    assert db.execute("select mark from invoice_submission").fetchall() == [("900000000000011",)]

def test_οι_χαρακτηρισμοί_κρατούν_το_κλείδωμα_όσο_στέλνουν(monkeypatch, db, db_cfg, taxpayer):
    seen = []
    def send(x, per_invoice=True, *, env):
        seen.append(_can_write(db_cfg))
        return [{"invoice_mark": "900000000000003", "classification_mark": "900000000000012",
                 "status": "Success", "errors": []}], "<r/>"
    monkeypatch.setattr(classify_routes, "send_expenses_classification", send)
    monkeypatch.setattr(classify_routes, "refresh", lambda *a, **k: None)
    monkeypatch.setattr(classify_routes, "build_workbook", lambda *a, **k: (b"", {}))
    body, status = classify_routes.submit_classifications(db_cfg, taxpayer, 2026, 7, XML_CLS)
    assert seen == [False] and status == 200
    assert _can_write(db_cfg)
    assert db.execute("select classification_mark from classification_submission").fetchall() == [
        ("900000000000012",)]

@pytest.mark.parametrize("error", ["transmit", "rate_limit", "crash"])
def test_η_διαβίβαση_ελευθερώνει_το_κλείδωμα_σε_αποτυχία(monkeypatch, db, db_cfg, taxpayer, error):
    from urllib.error import HTTPError
    from esoda_exoda.transmit import TransmitError
    def send(x, *, env):
        if error == "transmit":
            raise TransmitError("άρνηση")
        if error == "rate_limit":
            raise HTTPError("u", 429, "Too Many Requests", {}, None)
        raise RuntimeError("κάτω")
    monkeypatch.setattr(web_app, "send_invoices", send)
    try:
        web_app.submit_invoice(db_cfg, taxpayer, XML_172, 2026)
    except RuntimeError:
        pass
    assert _can_write(db_cfg)
