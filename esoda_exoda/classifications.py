# ABOUTME: Parsing/άντληση χαρακτηρισμών από RequestTransmittedDocs, ανά MARK.
# ABOUTME: incomeClassification στα εκδοθέντα, expensesClassification στα αυτο-δηλωθέντα.
from dataclasses import dataclass
from datetime import date
import xml.etree.ElementTree as ET

PAGE_BREAK = "<!-- PAGE BREAK -->"

@dataclass
class Classification:
    kind: str
    e3_type: str
    category: str

@dataclass
class SelfDeclared:
    mark: str
    uid: str
    inv_type: str
    series: str
    aa: str
    date: date
    net: float
    vat: float
    e3_type: str
    category: str
    cancelled_by: str = ""
    issuer_vat: str = ""

def _local(tag): return tag.split("}")[-1]

def _find_first(elem, name):
    for e in elem.iter():
        if _local(e.tag) == name:
            return e
    return None

def _first_text(elem, name) -> str:
    e = _find_first(elem, name)
    return (e.text or "").strip() if e is not None else ""

def _find_classification(inv, tag):
    """Ένα παραστατικό μπορεί να φέρει δύο classification blocks του ίδιου tag
    (π.χ. 14.x: ένα E3_* και ένα VAT_365/VAT_366). Προτιμάται το E3_*, γιατί
    μόνο αυτό φέρει classificationCategory και οδηγεί σε κωδικό Ε3 και σε
    σωστό έλεγχο έκπτωσης ΦΠΑ."""
    matches = [e for e in inv.iter() if _local(e.tag) == tag]
    for m in matches:
        if _first_text(m, "classificationType").startswith("E3_"):
            return m
    return matches[0] if matches else None

def parse_self_declared(xml_text: str) -> list[SelfDeclared]:
    out = []
    for page in xml_text.split(PAGE_BREAK):
        page = page.strip()
        if not page:
            continue
        root = ET.fromstring(page)
        for inv in root.iter():
            if _local(inv.tag) != "invoice":
                continue
            cl = _find_classification(inv, "expensesClassification")
            header = _find_first(inv, "invoiceHeader")
            if cl is None or header is None:
                continue
            issuer = _find_first(inv, "issuer")
            issuer_vat = _first_text(issuer, "vatNumber") if issuer is not None else ""
            out.append(SelfDeclared(
                mark=_first_text(inv, "mark"),
                uid=_first_text(inv, "uid"),
                inv_type=_first_text(header, "invoiceType"),
                series=_first_text(header, "series"),
                aa=_first_text(header, "aa"),
                date=date.fromisoformat(_first_text(header, "issueDate")),
                net=float(_first_text(inv, "totalNetValue")
                          or _first_text(inv, "netValue") or 0),
                vat=float(_first_text(inv, "totalVatAmount")
                          or _first_text(inv, "vatAmount") or 0),
                e3_type=_first_text(cl, "classificationType"),
                category=_first_text(cl, "classificationCategory"),
                cancelled_by=_first_text(inv, "cancelledByMark"),
                issuer_vat=issuer_vat))
    return out

def parse_doc_headers(xml_text: str) -> dict:
    """Επιστρέφει mark -> (series, aa) από το invoiceHeader κάθε παραστατικού."""
    out = {}
    for page in xml_text.split(PAGE_BREAK):
        page = page.strip()
        if not page:
            continue
        root = ET.fromstring(page)
        for inv in root.iter():
            if _local(inv.tag) != "invoice":
                continue
            mark_el = next((c for c in inv if _local(c.tag) == "mark"), None)
            if mark_el is None or not (mark_el.text or "").strip():
                continue
            header = _find_first(inv, "invoiceHeader")
            if header is None:
                continue
            series = _find_first(header, "series")
            aa = _find_first(header, "aa")
            out[mark_el.text.strip()] = (
                (series.text or "").strip() if series is not None else "",
                (aa.text or "").strip() if aa is not None else "")
    return out

def parse_transmitted(xml_text: str) -> dict:
    out = {}
    for page in xml_text.split(PAGE_BREAK):
        page = page.strip()
        if not page:
            continue
        root = ET.fromstring(page)
        for inv in root.iter():
            if _local(inv.tag) != "invoice":
                continue
            mark_el = next((c for c in inv if _local(c.tag) == "mark"), None)
            if mark_el is None or not (mark_el.text or "").strip():
                continue
            mark = mark_el.text.strip()
            for kind, tag in (("income", "incomeClassification"),
                              ("expense", "expensesClassification")):
                cl = _find_classification(inv, tag)
                if cl is None:
                    continue
                ctype = _find_first(cl, "classificationType")
                ccat = _find_first(cl, "classificationCategory")
                out[mark] = Classification(
                    kind=kind,
                    e3_type=(ctype.text or "").strip() if ctype is not None else "",
                    category=(ccat.text or "").strip() if ccat is not None else "")
                break
    return out
