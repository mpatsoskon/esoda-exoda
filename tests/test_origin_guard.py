# ABOUTME: Tests του φύλακα προέλευσης: ξένο Host/Origin/Sec-Fetch-Site → 403 χωρίς καμία
# ABOUTME: κλήση στο myDATA· ό,τι στέλνει η ίδια η σελίδα της εφαρμογής περνά.
import pytest
from fastapi.testclient import TestClient
from esoda_exoda.web.app import app
from esoda_exoda.web.origin_guard import refusal
from web_client import LOCAL, local_client

EVIL = "http://evil.example"

@pytest.fixture
def calls(monkeypatch, db_cfg, taxpayer):
    """Κάθε δρόμος προς το myDATA καταγράφεται και σκάει: αν ο φύλακας αφήσει κάτι να
    περάσει, το test αποτυγχάνει είτε στην εξαίρεση είτε στη λίστα."""
    from esoda_exoda.web import app as web_app, classify_routes
    monkeypatch.setattr(web_app, "load_config", lambda: db_cfg)
    monkeypatch.setattr(classify_routes, "load_config", lambda: db_cfg)
    seen = []
    def record(name):
        def f(*a, **k):
            seen.append(name)
            raise AssertionError(f"κλήση στο myDATA: {name}")
        return f
    monkeypatch.setattr(web_app, "send_invoices", record("SendInvoices"))
    monkeypatch.setattr(classify_routes, "send_expenses_classification",
                        record("SendExpensesClassification"))
    monkeypatch.setattr(web_app.mydata_client, "fetch_xml", record("fetch"))
    return seen

POSTS = [
    ("/transmit/send", {"xml": "<InvoicesDoc/>", "year": "2026"}),
    ("/classify/send", {"year": "2026", "month": "7", "xml_per_invoice": "<x/>"}),
    ("/refresh", {"year": "2026", "month": "7"}),
]

# (περιγραφή, base_url, headers)
REFUSED = [
    ("ξένο Origin", LOCAL, {"Origin": EVIL}),
    ("DNS rebinding: ξένο Host με το δικό του Origin", EVIL, {"Origin": EVIL}),
    ("χωρίς Origin και Sec-Fetch-Site", LOCAL, {}),
    ("Sec-Fetch-Site cross-site υπερισχύει του Origin", LOCAL,
     {"Sec-Fetch-Site": "cross-site", "Origin": LOCAL}),
    ("Sec-Fetch-Site none", LOCAL, {"Sec-Fetch-Site": "none"}),
    ("Origin null", LOCAL, {"Origin": "null"}),
    ("άλλη θύρα, same-site", LOCAL,
     {"Origin": "http://127.0.0.1:8001", "Sec-Fetch-Site": "same-site"}),
    ("άλλη θύρα, μόνο Origin", LOCAL, {"Origin": "http://127.0.0.1:8001"}),
    ("localhost σελίδα προς 127.0.0.1", "http://localhost:8000", {"Origin": LOCAL}),
]

@pytest.mark.parametrize("path,data", POSTS, ids=[p for p, _ in POSTS])
@pytest.mark.parametrize("why,base_url,headers", REFUSED, ids=[w for w, _, _ in REFUSED])
def test_ξένο_post_απορρίπτεται_χωρίς_κλήση(calls, path, data, why, base_url, headers):
    resp = TestClient(app, base_url=base_url, headers=headers).post(path, data=data)
    assert resp.status_code == 403, why
    assert resp.headers["content-type"].startswith("text/plain") and "Άρνηση" in resp.text
    assert calls == []

def test_get_με_ξένο_host_απορρίπτεται(calls):
    resp = TestClient(app, base_url=EVIL).get("/export/2026.xlsx")
    assert resp.status_code == 403
    assert calls == []

_BAD_DATE = {"preset": "αποσβέσεις", "issue_date": "x", "net": "1"}

@pytest.mark.parametrize("base_url,headers", [
    (LOCAL, {"Origin": LOCAL}),
    ("http://localhost:8000", {"Origin": "http://localhost:8000"}),
    ("http://127.0.0.1:8001", {"Sec-Fetch-Site": "same-origin"}),
])
def test_η_φόρμα_της_εφαρμογής_περνά(calls, base_url, headers):
    # Η άκυρη ημερομηνία κόβεται από το route (400), άρα το αίτημα πέρασε τον φύλακα
    # χωρίς να φτάσει στο myDATA.
    resp = TestClient(app, base_url=base_url, headers=headers).post("/transmit/preview",
                                                                    data=_BAD_DATE)
    assert resp.status_code == 400 and "Μη έγκυρη ημερομηνία" in resp.text
    assert calls == []

def test_η_φόρμα_του_browser_με_sec_fetch_site_και_origin_περνά(calls):
    resp = local_client(headers={"Sec-Fetch-Site": "same-origin"}).post("/transmit/preview",
                                                                        data=_BAD_DATE)
    assert resp.status_code == 400

def test_static_περνά():
    assert TestClient(app, base_url=LOCAL).get("/static/app.css").status_code == 200

@pytest.mark.parametrize("method,headers,refused", [
    ("POST", {}, True),                                         # χωρίς Host
    ("GET", {"host": "127.0.0.1:8000"}, False),
    ("GET", {"host": "[::1]:8000"}, True),
    ("POST", {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"}, False),
    ("PUT", {"host": "127.0.0.1:8000"}, True),                  # μη ασφαλής μέθοδος
    ("HEAD", {"host": "127.0.0.1:8000"}, False),
    ("OPTIONS", {"host": "localhost"}, False),
])
def test_refusal(method, headers, refused):
    assert (refusal(method, headers) is not None) is refused
