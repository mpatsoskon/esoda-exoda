# ABOUTME: Parse των RequestE3Info/RequestVatInfo — η επίσημη κατάσταση χαρακτηρισμού
# ABOUTME: ανά MARK. Τα πεδία τους είναι κεφαλαία με underscores, όχι camelCase.
import re
from dataclasses import dataclass, field
from datetime import date, datetime
import xml.etree.ElementTree as ET

PAGE_BREAK = "<!-- PAGE BREAK -->"

# Κωδικός Φ2 όπως τον εκπέμπει το RequestVatInfo: «Vat» + αριθμός.
_VAT_CODE = re.compile(r"^Vat\d+$")

@dataclass
class E3Line:
    mark: str
    date: date
    category: str
    e3_type: str
    value: float

@dataclass
class VatCodes:
    mark: str
    date: date
    codes: dict[str, float] = field(default_factory=dict)

def _local(tag: str) -> str:
    return tag.split("}")[-1]

def _texts(elem) -> dict[str, str]:
    return {_local(c.tag): (c.text or "").strip() for c in elem}

def _issue_date(raw: str, mark: str) -> date:
    """Το IssueDate έρχεται «2026-07-01T00:00:00» — το date.fromisoformat δεν το δέχεται."""
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        raise ValueError(
            f"Μη έγκυρη ημερομηνία «{raw}» στη γραμμή με MARK {mark}") from None

def _amount(raw: str, name: str, mark: str) -> float:
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            f"Μη έγκυρο ποσό «{raw}» στο πεδίο {name} της γραμμής με MARK {mark}") from None

def _pages(xml_text: str, tag: str):
    for page in xml_text.split(PAGE_BREAK):
        page = page.strip()
        if not page:
            continue
        for elem in ET.fromstring(page).iter():
            if _local(elem.tag) == tag:
                yield elem

def parse_e3_info(xml_text: str) -> dict[str, list[E3Line]]:
    """Μία γραμμή ανά χαρακτηρισμό, όχι ανά παραστατικό: δαπάνη σπασμένη σε δύο κωδικούς
    Ε3 δίνει δύο γραμμές με το ίδιο V_Mark. Επιστρέφει έσοδα ΚΑΙ έξοδα — η διάκριση
    γίνεται μόνο από το πρόθεμα category1_/category2_ (βλ. expense_lines)."""
    out: dict[str, list[E3Line]] = {}
    for elem in _pages(xml_text, "E3Info"):
        t = _texts(elem)
        mark = t.get("V_Mark", "")
        if not mark:
            continue
        out.setdefault(mark, []).append(E3Line(
            mark=mark,
            date=_issue_date(t.get("IssueDate", ""), mark),
            category=t.get("V_Class_Category", ""),
            e3_type=t.get("V_Class_Type", ""),
            value=_amount(t.get("V_Class_Value", "0"), "V_Class_Value", mark)))
    return out

def parse_vat_info(xml_text: str) -> dict[str, VatCodes]:
    """Τα ακυρωμένα φιλτράρονται. Γραμμή χωρίς κανένα πεδίο Vat* είναι έγκυρη και
    σημαίνει «δεν συμμετέχει στη δήλωση» — δεν είναι μηδέν και δεν πετιέται."""
    out: dict[str, VatCodes] = {}
    for elem in _pages(xml_text, "VatInfo"):
        t = _texts(elem)
        mark = t.get("Mark", "")
        if not mark or t.get("IsCancelled", "").lower() == "true":
            continue
        out[mark] = VatCodes(
            mark=mark,
            date=_issue_date(t.get("IssueDate", ""), mark),
            codes={k: _amount(v, k, mark) for k, v in t.items() if _VAT_CODE.match(k)})
    return out

def expense_lines(by_mark: dict[str, list[E3Line]]) -> dict[str, list[E3Line]]:
    """Το RequestE3Info επιστρέφει και τα δικά μας εκδοθέντα. Κρατά μόνο τις γραμμές
    εξόδων, ώστε ο πρώτος της λίστας να είναι πάντα γραμμή εξόδου: η οθόνη προεπιλέγει
    τον current[0] και ένα έσοδο εκεί θα έβαζε κωδικό ΕΣΟΔΟΥ σε dropdown εξόδου."""
    return {mark: [l for l in lines if l.category.startswith("category2_")]
            for mark, lines in by_mark.items()
            if any(l.category.startswith("category2_") for l in lines)}

def official_by_month(by_mark: dict[str, VatCodes]) -> dict[int, dict[str, float]]:
    """Αθροίζει τους κωδικούς Φ2 του RequestVatInfo ανά μήνα έκδοσης. Το φύλλο ΦΠΑ
    δουλεύει ανά μήνα και δεν κρατά MARK, άρα η αντιπαραβολή γίνεται σε αυτό το
    επίπεδο και μόνο."""
    out: dict[int, dict[str, float]] = {}
    for info in by_mark.values():
        month = out.setdefault(info.date.month, {})
        for code, value in info.codes.items():
            month[code] = month.get(code, 0.0) + value
    return out
