# ABOUTME: Δόμηση XML διαβίβασης αυτο-δηλούμενων εξόδων (13.3, 17.2) και έλεγχος
# ABOUTME: της απόκρισης. Καθαρή λογική: κανένα δίκτυο, κανένα I/O.
from dataclasses import dataclass
from datetime import date
import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as _x

@dataclass
class Entry:
    inv_type: str
    series: str
    aa: str
    issue_date: date
    net: float
    vat: float
    vat_category: str
    e3_type: str
    category: str

_CLASSIFICATION = """      <expensesClassification>
        <ecls:classificationType>{e3_type}</ecls:classificationType>
        <ecls:classificationCategory>{category}</ecls:classificationCategory>
        <ecls:amount>{net:.2f}</ecls:amount>
      </expensesClassification>"""

_ISSUER = """    <issuer>
      <vatNumber>{afm}</vatNumber>
      <country>GR</country>
      <branch>0</branch>
    </issuer>"""

_COUNTERPART = """    <counterpart>
      <vatNumber>{afm}</vatNumber>
      <country>GR</country>
      <branch>0</branch>
      <address>
        <postalCode>{postal_code}</postalCode>
        <city>{city}</city>
      </address>
    </counterpart>"""

def build_xml(entry: Entry, afm: str, postal_code: str = "", city: str = "") -> str:
    """Στα 13.x η οντότητα που διαβιβάζει είναι ο λήπτης του εξόδου: το myDATA απαιτεί
    counterpart και απαγορεύει issuer. Στα 17.x ισχύει το αντίστροφο."""
    if entry.inv_type.startswith("13."):
        if not postal_code or not city:
            raise TransmitError("Συμπλήρωσε postal_code και city στο config.toml "
                                "πριν τη διαβίβαση 13.x.")
        party = _COUNTERPART.format(afm=afm, postal_code=_x(postal_code), city=_x(city))
    else:
        party = _ISSUER.format(afm=afm)
    cls = _CLASSIFICATION.format(e3_type=entry.e3_type, category=entry.category,
                                 net=entry.net)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<InvoicesDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0"
             xmlns:ecls="https://www.aade.gr/myDATA/expensesClassificaton/v1.0">
  <invoice>
{party}
    <invoiceHeader>
      <series>{entry.series}</series>
      <aa>{entry.aa}</aa>
      <issueDate>{entry.issue_date.isoformat()}</issueDate>
      <invoiceType>{entry.inv_type}</invoiceType>
      <currency>EUR</currency>
    </invoiceHeader>
    <invoiceDetails>
      <lineNumber>1</lineNumber>
      <netValue>{entry.net:.2f}</netValue>
      <vatCategory>{entry.vat_category}</vatCategory>
      <vatAmount>{entry.vat:.2f}</vatAmount>
{cls}
    </invoiceDetails>
    <invoiceSummary>
      <totalNetValue>{entry.net:.2f}</totalNetValue>
      <totalVatAmount>{entry.vat:.2f}</totalVatAmount>
      <totalWithheldAmount>0.00</totalWithheldAmount>
      <totalFeesAmount>0.00</totalFeesAmount>
      <totalStampDutyAmount>0.00</totalStampDutyAmount>
      <totalOtherTaxesAmount>0.00</totalOtherTaxesAmount>
      <totalDeductionsAmount>0.00</totalDeductionsAmount>
      <totalGrossValue>{entry.net + entry.vat:.2f}</totalGrossValue>
{cls}
    </invoiceSummary>
  </invoice>
</InvoicesDoc>
"""

_VAT_CLS = """      <expensesClassification>
        <ecls:classificationType>{vat_cls}</ecls:classificationType>
        <ecls:amount>{net:.2f}</ecls:amount>
      </expensesClassification>"""

def notional_vat(net: float) -> float:
    """Πλασματικό ΦΠΑ 24% (reverse charge) — το vatCategory 8 απορρίπτεται στα 14.x."""
    return round(net * 0.24, 2)

def build_xml_14(sup, issue_date: date, net: float, aa: str, afm: str,
                 postal_code: str, city: str) -> str:
    vat = notional_vat(net)
    cls = (_CLASSIFICATION.format(e3_type=_x(sup.e3), category=_x(sup.category), net=net)
           + "\n" + _VAT_CLS.format(vat_cls=sup.vat_classification, net=net))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<InvoicesDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0"
             xmlns:ecls="https://www.aade.gr/myDATA/expensesClassificaton/v1.0">
  <invoice>
    <issuer>
      <vatNumber>{_x(sup.vat)}</vatNumber>
      <country>{_x(sup.country)}</country>
      <branch>0</branch>
      <name>{_x(sup.name)}</name>
      <address>
        <postalCode>{_x(sup.postal_code)}</postalCode>
        <city>{_x(sup.city)}</city>
      </address>
    </issuer>
    <counterpart>
      <vatNumber>{afm}</vatNumber>
      <country>GR</country>
      <branch>0</branch>
      <address>
        <postalCode>{_x(postal_code)}</postalCode>
        <city>{_x(city)}</city>
      </address>
    </counterpart>
    <invoiceHeader>
      <series>0</series>
      <aa>{aa}</aa>
      <issueDate>{issue_date.isoformat()}</issueDate>
      <invoiceType>{sup.inv_type}</invoiceType>
      <currency>EUR</currency>
    </invoiceHeader>
    <invoiceDetails>
      <lineNumber>1</lineNumber>
      <netValue>{net:.2f}</netValue>
      <vatCategory>1</vatCategory>
      <vatAmount>{vat:.2f}</vatAmount>
{cls}
    </invoiceDetails>
    <invoiceSummary>
      <totalNetValue>{net:.2f}</totalNetValue>
      <totalVatAmount>{vat:.2f}</totalVatAmount>
      <totalWithheldAmount>0.00</totalWithheldAmount>
      <totalFeesAmount>0.00</totalFeesAmount>
      <totalStampDutyAmount>0.00</totalStampDutyAmount>
      <totalOtherTaxesAmount>0.00</totalOtherTaxesAmount>
      <totalDeductionsAmount>0.00</totalDeductionsAmount>
      <totalGrossValue>{net + vat:.2f}</totalGrossValue>
{cls}
    </invoiceSummary>
  </invoice>
</InvoicesDoc>
"""

def next_aa(self_declared: list, inv_type: str, year: int) -> int:
    used = [int(sd.aa) for sd in self_declared
            if sd.inv_type == inv_type and sd.date.year == year and sd.aa.isdigit()]
    return max(used) + 1 if used else 1

class TransmitError(RuntimeError):
    pass

_GREEK_AMOUNT = re.compile(r"^\d{1,3}(\.\d{3})*(,\d{1,2})?$")
_PLAIN_AMOUNT = re.compile(r"^\d+(\.\d+)?$")
_PLAIN_INT = re.compile(r"^\d+$")

def parse_amount(raw: str) -> float:
    """Δέχεται είτε την ελληνική μορφή (τελεία χιλιάδων, κόμμα δεκαδικών, π.χ.
    "1.234,56") είτε την απλή μορφή υπολογιστή (τελεία δεκαδικών, π.χ. "1234.56").
    Μια τιμή με ακριβώς μία τελεία και ακριβώς τρία ψηφία μετά (π.χ. "1.234") είναι
    αμφίσημη — θα μπορούσε να εννοεί είτε 1234 (χιλιάδες) είτε 1,234 (δεκαδικό) —
    και απορρίπτεται αντί να μαντεύεται, γιατί μια διαβίβαση είναι αμετάκλητη."""
    s = raw.strip()
    if "," in s:
        if _GREEK_AMOUNT.match(s):
            return float(s.replace(".", "").replace(",", "."))
        raise TransmitError(
            f"Μη έγκυρο ποσό: «{raw}». Ελληνική μορφή: 1.234,56 — απλή μορφή: 1234.56.")
    if _PLAIN_INT.match(s):
        return float(s)
    if _PLAIN_AMOUNT.match(s):
        frac = s.split(".")[1]
        if len(frac) == 3:
            plain = s.replace(".", "")
            raise TransmitError(
                f"Αμφίσημο ποσό: «{raw}». Εννοείς {plain} €; Γράψε το ρητά, "
                f"«{plain}» ή «{s},00» — τα ποσά διαβιβάζονται με δύο δεκαδικά.")
        return float(s)
    raise TransmitError(f"Μη έγκυρο ποσό: «{raw}».")

_UI_DATE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")

def parse_issue_date(raw: str) -> date:
    """Δέχεται τη μορφή που δηλώνει το UI (dd-mm-yyyy) και την ISO (yyyy-mm-dd).
    Οι δύο ξεχωρίζουν από τη θέση της τετραψήφιας χρονιάς, οπότε δεν υπάρχει
    αμφισημία. Η μορφή δηλώνεται ρητά γιατί το input[type=date] αποδίδει σε μορφή
    του browser — σε en-US η 02/09 φαινόταν ως 9/2, δηλαδή ανάποδα."""
    s = raw.strip()
    m = _UI_DATE.match(s)
    try:
        if m:
            d, mo, y = (int(x) for x in m.groups())
            return date(y, mo, d)
        return date.fromisoformat(s)
    except ValueError:
        raise TransmitError(
            f"Μη έγκυρη ημερομηνία: «{raw}». Μορφή dd-mm-yyyy, π.χ. 02-09-2026.")

def _local(tag: str) -> str:
    return tag.split("}")[-1]

def _text(elem, name: str) -> str:
    for e in elem.iter():
        if _local(e.tag) == name:
            return (e.text or "").strip()
    return ""

def parse_entry_summary(xml_text: str) -> dict:
    """Εξάγει τύπο/σειρά/ΑΑ/ημ.έκδοσης/καθαρή αξία από το ήδη σταλμένο XML, ώστε
    το audit log να μην κρατά δεύτερη αντιγραφή αυτών των τιμών."""
    root = ET.fromstring(xml_text)
    header = next((e for e in root.iter() if _local(e.tag) == "invoiceHeader"), None)
    issuer = next((e for e in root.iter() if _local(e.tag) == "issuer"), None)
    return {
        "inv_type": _text(header, "invoiceType") if header is not None else "",
        "series": _text(header, "series") if header is not None else "",
        "aa": _text(header, "aa") if header is not None else "",
        "issue_date": _text(header, "issueDate") if header is not None else "",
        "net": float(_text(root, "totalNetValue") or 0),
        "issuer_vat": _text(issuer, "vatNumber") if issuer is not None else "",
        "issuer_name": _text(issuer, "name") if issuer is not None else "",
    }

def parse_response(xml_text: str) -> dict:
    """Επιστρέφει mark/uid μόνο σε statusCode Success· αλλιώς σηκώνει TransmitError."""
    root = ET.fromstring(xml_text)
    for resp in root.iter():
        if _local(resp.tag) != "response":
            continue
        status = _text(resp, "statusCode")
        if status == "Success":
            mark = _text(resp, "invoiceMark")
            uid = _text(resp, "invoiceUid")
            if not mark or not uid:
                raise TransmitError(f"myDATA Success χωρίς MARK: {xml_text[:200]}")
            return {"mark": mark, "uid": uid}
        messages = [(e.text or "").strip() for e in resp.iter()
                    if _local(e.tag) == "message"]
        if not messages:
            codes = [(e.text or "").strip() for e in resp.iter()
                     if _local(e.tag) == "code"]
            if codes:
                messages = [f"code {c}" for c in codes]
            else:
                messages = ["χωρίς περιγραφή σφάλματος"]
        raise TransmitError(f"myDATA {status}: " + "· ".join(messages))
    raise TransmitError("Απόκριση myDATA χωρίς στοιχείο response")
