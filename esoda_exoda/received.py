# ABOUTME: Parsing του myDATA RequestedDoc (RequestDocs) σε ληφθέντα παραστατικά
# ABOUTME: με γραμμές ΦΠΑ — η πηγή της οθόνης χαρακτηρισμού. Αγνοεί το XML namespace.
from dataclasses import dataclass, field
from datetime import date
import xml.etree.ElementTree as ET

PAGE_BREAK = "<!-- PAGE BREAK -->"

@dataclass
class VatLine:
    net: float
    vat_category: int
    vat_amount: float
    vat_exemption_category: int | None = None
    # Το πραγματικό <lineNumber> του παραστατικού. Το 0 σημαίνει «δεν το έδωσε το XML»
    # και τότε μόνο πέφτουμε στη σειρά της λίστας.
    line_number: int = 0

@dataclass
class ReceivedDoc:
    mark: str
    issuer_vat: str
    issuer_name: str
    counterpart_vat: str
    series: str
    aa: str
    date: date
    inv_type: str
    fuel_invoice: bool
    net: float
    vat: float
    other_taxes: float
    stamp_duty: float
    fees: float
    lines: list[VatLine] = field(default_factory=list)

def _local(tag: str) -> str:
    return tag.split("}")[-1]

def _child(elem, name):
    if elem is None:
        return None
    for c in elem:
        if _local(c.tag) == name:
            return c
    return None

def _text(elem, name, default=""):
    c = _child(elem, name)
    return (c.text or "").strip() if c is not None else default

def _num(elem, name, mark, default="0") -> float:
    """Απόν στοιχείο σημαίνει μηδέν· υπαρκτό αλλά κενό σημαίνει χαλασμένο δεδομένο και
    δεν σιωπά — ένα ποσό που «χάνεται» ως 0 δεν αφήνει ίχνος."""
    raw = _text(elem, name, default)
    try:
        return float(raw)
    except ValueError:
        raise ValueError(
            f"Μη έγκυρο ποσό «{raw}» στο πεδίο {name} του παραστατικού με MARK {mark}") from None

def _int_or_none(elem, name):
    raw = _text(elem, name, "")
    return int(raw) if raw else None

def parse_received(xml_text: str) -> list[ReceivedDoc]:
    docs: list[ReceivedDoc] = []
    for page in xml_text.split(PAGE_BREAK):
        page = page.strip()
        if not page:
            continue
        root = ET.fromstring(page)
        for inv in root.iter():
            if _local(inv.tag) != "invoice":
                continue
            header = _child(inv, "invoiceHeader")
            summary = _child(inv, "invoiceSummary")
            if header is None or summary is None:
                continue
            issuer = _child(inv, "issuer")
            counterpart = _child(inv, "counterpart")
            mark = _text(inv, "mark")
            raw_date = _text(header, "issueDate")
            if not raw_date:
                raise ValueError(f"Απόν issueDate σε παραστατικό με MARK {mark}")
            try:
                issue_date = date.fromisoformat(raw_date)
            except ValueError:
                raise ValueError(
                    f"Μη έγκυρο issueDate «{raw_date}» σε παραστατικό με MARK {mark}") from None
            lines = [VatLine(net=_num(det, "netValue", mark),
                             vat_category=int(_text(det, "vatCategory", "0") or 0),
                             vat_amount=_num(det, "vatAmount", mark),
                             vat_exemption_category=_int_or_none(det, "vatExemptionCategory"),
                             line_number=int(_text(det, "lineNumber", "0") or 0))
                     for det in inv if _local(det.tag) == "invoiceDetails"]
            docs.append(ReceivedDoc(
                mark=mark,
                issuer_vat=_text(issuer, "vatNumber"),
                issuer_name=_text(issuer, "name"),
                counterpart_vat=_text(counterpart, "vatNumber"),
                series=_text(header, "series"),
                aa=_text(header, "aa"),
                date=issue_date,
                inv_type=_text(header, "invoiceType"),
                fuel_invoice=_text(header, "fuelInvoice", "false").lower() == "true",
                net=_num(summary, "totalNetValue", mark),
                vat=_num(summary, "totalVatAmount", mark),
                other_taxes=_num(summary, "totalOtherTaxesAmount", mark),
                stamp_duty=_num(summary, "totalStampDutyAmount", mark),
                fees=_num(summary, "totalFeesAmount", mark),
                lines=lines))
    return docs
