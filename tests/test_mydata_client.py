# ABOUTME: Tests fetch με mock στο HTTP boundary — καμία κλήση production.
# ABOUTME: Επιβεβαιώνει ότι η σελιδοποίηση ακολουθεί nextPartitionKey/nextRowKey.
from esoda_exoda import mydata_client
import pytest

PAGE1 = """<?xml version="1.0" encoding="utf-8"?>
<RequestedBookInfo xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<bookInfo><counterVatNumber>990000106</counterVatNumber><issueDate>2025-01-10</issueDate>
<invType>1.1</invType><netValue>100</netValue><vatAmount>24</vatAmount>
<withheldAmount>0</withheldAmount><grossValue>124</grossValue><minMark>M1</minMark></bookInfo>
<continuationToken><nextPartitionKey>PK</nextPartitionKey><nextRowKey>RK</nextRowKey></continuationToken>
</RequestedBookInfo>"""
PAGE2 = """<?xml version="1.0" encoding="utf-8"?>
<RequestedBookInfo xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<bookInfo><counterVatNumber>090000125</counterVatNumber><issueDate>2025-01-20</issueDate>
<invType>1.1</invType><netValue>50</netValue><vatAmount>12</vatAmount>
<withheldAmount>0</withheldAmount><grossValue>62</grossValue><minMark>M2</minMark></bookInfo>
</RequestedBookInfo>"""

class FakeResp:
    def __init__(self, body): self._b = body.encode("utf-8")
    def read(self): return self._b
    def __enter__(self): return self
    def __exit__(self, *a): return False

def test_fetch_xml_διαλέγει_endpoint_και_παραμέτρους(monkeypatch):
    monkeypatch.setattr(mydata_client, "_headers", lambda env: {})
    seen = []
    def opener(req, timeout):
        seen.append(req.full_url)
        return FakeResp("<RequestedBookInfo/>")
    mydata_client.fetch_xml("RequestMyExpenses", "01/07/2026", "31/07/2026", env="production", opener=opener)
    mydata_client.fetch_xml("RequestDocs", "01/07/2026", "31/07/2026", env="production", opener=opener)
    assert "RequestMyExpenses?dateFrom=01%2F07%2F2026&dateTo=31%2F07%2F2026" in seen[0]
    assert seen[1].endswith("RequestDocs?mark=0")

def test_send_expenses_classification_επιστρέφει_και_το_raw(monkeypatch):
    monkeypatch.setattr(mydata_client, "_headers", lambda env: {})
    raw = ('<ResponseDoc><response><index>1</index><invoiceMark>1</invoiceMark>'
           '<classificationMark>2</classificationMark><statusCode>Success</statusCode></response></ResponseDoc>')
    results, body = mydata_client.send_expenses_classification("<x/>", env="production", opener=lambda req, timeout: FakeResp(raw))
    assert results[0]["classification_mark"] == "2" and body == raw

def test_fetch_follows_pagination(monkeypatch):
    calls = []
    def fake_opener(req, timeout=0):
        calls.append(req.full_url)
        return FakeResp(PAGE1 if "nextPartitionKey" not in req.full_url else PAGE2)
    monkeypatch.setattr(mydata_client, "_headers", lambda env: {})
    xml = mydata_client.fetch_xml("RequestMyIncome", "01/01/2025", "31/01/2025", env="production", opener=fake_opener)
    assert "M1" in xml and "M2" in xml
    assert len(calls) == 2

def test_fetch_pages_caps_runaway_pagination(monkeypatch):
    def fake_opener(req, timeout=0):
        return FakeResp(PAGE1)   # πάντα continuation token
    monkeypatch.setattr(mydata_client, "_headers", lambda env: {})
    monkeypatch.setattr(mydata_client, "MAX_PAGES", 3)
    with pytest.raises(RuntimeError, match="σελίδες"):
        mydata_client.fetch_xml("RequestMyIncome", "01/01/2025", "31/01/2025", env="production", opener=fake_opener)
    with pytest.raises(RuntimeError, match="σελίδες"):
        mydata_client.fetch_xml("RequestTransmittedDocs", "01/01/2025", "31/01/2025", env="production", opener=fake_opener)

def test_send_invoices_posts_xml_and_returns_mark(monkeypatch):
    from esoda_exoda.transmit import TransmitError
    sent = {}
    def fake_opener(req, timeout=0):
        sent["url"] = req.full_url
        sent["body"] = req.data.decode("utf-8")
        sent["method"] = req.get_method()
        sent["ctype"] = req.get_header("Content-type")
        return FakeResp("""<?xml version="1.0" encoding="utf-8"?>
<ResponseDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<response><invoiceUid>U1</invoiceUid><invoiceMark>M1</invoiceMark>
<statusCode>Success</statusCode></response></ResponseDoc>""")
    monkeypatch.setattr(mydata_client, "_headers", lambda env: {})
    out = mydata_client.send_invoices("<InvoicesDoc/>", env="production", opener=fake_opener)
    assert out["mark"] == "M1" and out["uid"] == "U1"
    assert "<invoiceMark>M1</invoiceMark>" in out["response_xml"]
    assert sent["url"].endswith("/SendInvoices")
    assert sent["method"] == "POST"
    assert sent["ctype"] == "application/xml"
    assert sent["body"] == "<InvoicesDoc/>"

def test_send_expenses_classification_posts_to_the_right_url(monkeypatch):
    import esoda_exoda.mydata_client as mc
    monkeypatch.setattr(mc, "_headers", lambda env: {"aade-user-id": "u",
                                                 "Ocp-Apim-Subscription-Key": "k"})
    seen = {}
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return b"""<?xml version="1.0" encoding="utf-8"?>
<ResponseDoc><response><invoiceMark>900000000001000</invoiceMark>
<classificationMark>1000000000000001</classificationMark>
<statusCode>Success</statusCode></response></ResponseDoc>"""
    def fake_opener(req, timeout=None):
        seen["url"] = req.full_url
        seen["method"] = req.get_method()
        seen["body"] = req.data.decode("utf-8")
        return FakeResp()
    out, raw = mc.send_expenses_classification("<ExpensesClassificationsDoc/>", env="production", opener=fake_opener)
    assert seen["url"] == ("https://mydatapi.aade.gr/myDATA/SendExpensesClassification"
                           "?postPerInvoice=true")
    assert seen["method"] == "POST"
    assert out == [{"invoice_mark": "900000000001000",
                    "classification_mark": "1000000000000001",
                    "status": "Success", "errors": []}]
    assert "1000000000000001" in raw

    mc.send_expenses_classification("<ExpensesClassificationsDoc/>", per_invoice=False, env="production",
                                    opener=fake_opener)
    assert seen["url"] == "https://mydatapi.aade.gr/myDATA/SendExpensesClassification"
    assert "postPerInvoice" not in seen["url"]

def test_base_url_ανά_περιβάλλον():
    assert mydata_client.base_url("production") == "https://mydatapi.aade.gr/myDATA"
    assert mydata_client.base_url("dev") == "https://mydataapidev.aade.gr"

def test_base_url_αρνείται_άγνωστο_περιβάλλον():
    with pytest.raises(ValueError):
        mydata_client.base_url("prod")

def test_dev_πηγαίνει_στο_sandbox_με_τα_dev_κλειδιά(monkeypatch):
    seen = {}
    monkeypatch.setattr(mydata_client, "_headers", lambda env: seen.setdefault("env", env) and {})
    urls = []
    def opener(req, timeout):
        urls.append(req.full_url)
        return FakeResp("<ResponseDoc><response><statusCode>Success</statusCode>"
                        "<invoiceMark>900000000000001</invoiceMark><invoiceUid>U</invoiceUid>"
                        "</response></ResponseDoc>")
    mydata_client.send_invoices("<InvoicesDoc/>", env="dev", opener=opener)
    assert urls == ["https://mydataapidev.aade.gr/SendInvoices"] and seen["env"] == "dev"
