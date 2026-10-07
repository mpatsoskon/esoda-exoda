# ABOUTME: Tests του audit αμετάκλητων POST στη βάση, με τα ίδια κλειδιά που είχαν τα jsonl.
# ABOUTME: Καταγραφή των invoice_submission και classification_submission με request/response XML.
from esoda_exoda.counterparties import ensure_counterparty
from esoda_exoda.submissions import (last_submission, list_classification_submissions,
                                     list_invoice_submissions, record_classification_submissions,
                                     record_invoice_submission)

_ENTRY = {"inv_type": "13.3", "series": "123456783", "aa": "8000000020", "issue_date": "2026-08-01",
          "net": 12.0, "issuer_vat": "", "issuer_name": ""}

def test_invoice_submission_roundtrip_νεότερο_πρώτα(db, taxpayer):
    record_invoice_submission(db, taxpayer.id, _ENTRY, "M1", "U1", "<a/>", "<r/>")
    record_invoice_submission(db, taxpayer.id, {**_ENTRY, "aa": "2"}, "M2", "U2", "<b/>", "<r/>")
    out = list_invoice_submissions(db, taxpayer.id)
    assert [t["mark"] for t in out] == ["M2", "M1"]
    t = out[1]
    assert (t["inv_type"], t["series"], t["aa"], t["issue_date"], t["net"], t["uid"], t["statusCode"]) == (
        "13.3", "123456783", "8000000020", "2026-08-01", 12.0, "U1", "Success")
    assert isinstance(t["at"], str) and len(t["at"]) == 19
    assert last_submission(db, taxpayer.id)["mark"] == "M2"
    xml = db.execute("select request_xml from invoice_submission where mark = 'M1'").fetchone()[0]
    assert xml == "<a/>"

def test_invoice_submission_δένει_αντισυμβαλλόμενο(db, taxpayer):
    cid = ensure_counterparty(db, taxpayer.id, "NL1", "FOREIGN SUPPLIER A", "NL")
    record_invoice_submission(db, taxpayer.id, {**_ENTRY, "issuer_vat": "NL1", "issuer_name": "FOREIGN SUPPLIER A"}, "M1", "U1", "", "")
    got = db.execute("select counterparty_id from invoice_submission").fetchone()[0]
    assert got == cid

def test_χωρίς_υποβολές(db, taxpayer):
    assert list_invoice_submissions(db, taxpayer.id) == [] and last_submission(db, taxpayer.id) is None

def test_classification_submissions_με_errors_και_xml_ανά_mode(db, taxpayer):
    records = [{"invoice_mark": "A", "classification_mark": "C1", "status": "Success", "errors": [],
                "per_invoice": True, "e3_type": "E3_585_016", "category": "category2_4", "amount": 100.0},
               {"invoice_mark": "B", "classification_mark": "", "status": "ValidationError",
                "errors": [{"code": "339", "message": "Invalid classification combination"}], "per_invoice": False}]
    record_classification_submissions(db, taxpayer.id, 2026, records, {True: "<pi/>", False: "<pl/>"}, {True: "<r1/>", False: "<r2/>"})
    out = list_classification_submissions(db, taxpayer.id, 2026)
    assert {o["invoice_mark"] for o in out} == {"A", "B"}
    b = next(o for o in out if o["invoice_mark"] == "B")
    assert b["errors"][0]["code"] == "339" and b["request_xml"] == "<pl/>"
    a = next(o for o in out if o["invoice_mark"] == "A")
    assert a["amount"] == 100.0 and a["request_xml"] == "<pi/>"
