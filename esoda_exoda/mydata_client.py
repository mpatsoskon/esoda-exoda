# ABOUTME: REST client myDATA: fetch εσόδων/εξόδων με σελιδοποίηση
# ABOUTME: (nextPartitionKey/nextRowKey). Το opener param επιτρέπει mock σε tests.
import re
import urllib.parse
import urllib.request
from .classify import parse_classification_response
from .credentials import get_headers
from .transmit import parse_response

_BASES = {"production": "https://mydatapi.aade.gr/myDATA",
          "dev": "https://mydataapidev.aade.gr"}
MAX_PAGES = 500  # όριο ασφαλείας αν το myDATA επιστρέφει επ' άπειρον continuation token
RANGE_METHODS = ("RequestMyIncome", "RequestMyExpenses", "RequestE3Info", "RequestVatInfo")
DOC_METHODS = ("RequestTransmittedDocs", "RequestDocs")

def base_url(environment: str) -> str:
    try:
        return _BASES[environment]
    except KeyError:
        raise ValueError(f"Άγνωστο περιβάλλον myDATA: {environment!r}") from None

def _headers(env):
    return get_headers(env)

def _fetch_pages(endpoint, date_from, date_to, opener, env) -> str:
    pages, pk, rk = [], None, None
    while True:
        if len(pages) >= MAX_PAGES:
            raise RuntimeError(f"Το {endpoint} ξεπέρασε τις {MAX_PAGES} σελίδες — πιθανό μπλοκαρισμένο continuation token.")
        q = {"dateFrom": date_from, "dateTo": date_to}
        if pk:
            q.update(nextPartitionKey=pk, nextRowKey=rk)
        url = f"{base_url(env)}/{endpoint}?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(url, headers=_headers(env))
        with opener(req, timeout=120) as r:
            body = r.read().decode("utf-8")
        pages.append(body)
        m = re.search(r"<nextPartitionKey>(.*?)</nextPartitionKey>.*?"
                      r"<nextRowKey>(.*?)</nextRowKey>", body, re.S)
        if m and m.group(1).strip():
            pk, rk = m.group(1).strip(), m.group(2).strip()
        else:
            break
    return "\n<!-- PAGE BREAK -->\n".join(pages)

def fetch_xml(method: str, date_from: str, date_to: str, *, env: str,
              opener=urllib.request.urlopen) -> str:
    """Ένα σημείο εισόδου για το refresh: το ωμό XML όλων των σελίδων. Τα RequestDocs/
    RequestTransmittedDocs δεν φιλτράρουν με εύρος (mark=0, όλο το ιστορικό), όπως πάντα."""
    if method in RANGE_METHODS:
        return _fetch_pages(method, date_from, date_to, opener, env)
    if method in DOC_METHODS:
        return _fetch_doc_pages(method, opener, env)
    raise ValueError(f"Άγνωστη μέθοδος myDATA: {method}")

def _fetch_doc_pages(endpoint, opener, env) -> str:
    pages, pk, rk = [], None, None
    while True:
        if len(pages) >= MAX_PAGES:
            raise RuntimeError(f"Το {endpoint} ξεπέρασε τις {MAX_PAGES} σελίδες — πιθανό μπλοκαρισμένο continuation token.")
        q = {"mark": "0"}
        if pk:
            q.update(nextPartitionKey=pk, nextRowKey=rk)
        url = f"{base_url(env)}/{endpoint}?{urllib.parse.urlencode(q)}"
        req = urllib.request.Request(url, headers=_headers(env))
        with opener(req, timeout=120) as r:
            body = r.read().decode("utf-8")
        pages.append(body)
        m = re.search(r"<nextPartitionKey>(.*?)</nextPartitionKey>.*?<nextRowKey>(.*?)</nextRowKey>", body, re.S)
        if m and m.group(1).strip():
            pk, rk = m.group(1).strip(), m.group(2).strip()
        else:
            break
    return "\n<!-- PAGE BREAK -->\n".join(pages)

def send_invoices(xml: str, *, env: str, opener=urllib.request.urlopen) -> dict:
    """POST στο SendInvoices. Χωρίς retry: διπλή υποβολή θα έδινε δύο MARK."""
    req = urllib.request.Request(
        f"{base_url(env)}/SendInvoices", data=xml.encode("utf-8"),
        headers={**_headers(env), "Content-Type": "application/xml"}, method="POST")
    with opener(req, timeout=120) as r:
        body = r.read().decode("utf-8")
    result = parse_response(body)
    result["response_xml"] = body
    return result

def send_expenses_classification(xml: str, per_invoice: bool = True, *, env: str,
                                 opener=urllib.request.urlopen) -> tuple[list[dict], str]:
    """POST στο SendExpensesClassification. Το postPerInvoice είναι query parameter, όχι
    στοιχείο XML — το XSD απορρίπτει το στοιχείο (XMLSyntaxError 101), επιβεβαιωμένο στο
    dev sandbox 01/09/2026. Χωρίς retry: διπλή υποβολή θα έδινε δύο χαρακτηρισμούς."""
    url = f"{base_url(env)}/SendExpensesClassification"
    if per_invoice:
        url += "?postPerInvoice=true"
    req = urllib.request.Request(
        url, data=xml.encode("utf-8"),
        headers={**_headers(env), "Content-Type": "application/xml"}, method="POST")
    with opener(req, timeout=120) as r:
        body = r.read().decode("utf-8")
    return parse_classification_response(body), body
