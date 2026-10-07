# ABOUTME: Κανόνες και δόμηση XML χαρακτηρισμού εξόδων ανά παραστατικό
# ABOUTME: (postPerInvoice). Καθαρή λογική: κανένα δίκτυο, κανένα I/O.
from dataclasses import dataclass
from xml.sax.saxutils import escape as _x
import xml.etree.ElementTree as ET
from .transmit import notional_vat   # πλασματικό ΦΠΑ 24%, από τη Φάση 4

class ClassifyError(RuntimeError):
    pass

# Οι κατηγορίες χωρίς χαρακτηρισμό ΦΠΑ: στην 2.5 το ΦΠΑ πάει στο ποσό του Ε3
# (κανόνας 7.ii), στην 2.9 δεν επιτρέπεται καθόλου χαρακτηρισμός ΦΠΑ (7.iii).
_NO_VAT_CATEGORIES = ("category2_5", "category2_9")

_VAT_CODES = {
    "category2_3": "VAT_361",   # Λήψη υπηρεσιών εσωτερικού
    "category2_4": "VAT_361",   # Γενικά έξοδα με δικαίωμα έκπτωσης
    "category2_7": "VAT_362",   # Αγορές παγίων
}

@dataclass
class VatObject:
    code: str
    vat_category: int
    vat_exemption_category: int | None
    amount: float
    vat_amount: float

def vat_code_for(category: str) -> str:
    code = _VAT_CODES.get(category)
    if code is None:
        raise ClassifyError(
            f"Δεν υπάρχει κωδικός ΦΠΑ για την κατηγορία «{category}». "
            "Πρόσθεσέ τον στο _VAT_CODES αφού τον επιβεβαιώσεις με τον λογιστή.")
    return code

def e3_amount(doc, category: str) -> float:
    base = doc.net + doc.other_taxes + doc.stamp_duty + doc.fees
    if category == "category2_5":
        # Κανόνας 7.ii: μόνο στην 2.5 το ΦΠΑ που δεν χαρακτηρίζεται προστίθεται στο Ε3.
        # Η 2.9 εξαιρείται από τον χαρακτηρισμό ΦΠΑ (7.iii) αλλά το ποσό της μένει
        # καθαρή αξία + λοιποί φόροι — ο 7.i ισχύει ακέραιος.
        base += doc.vat
    return round(base, 2)

# Άρθρο 39α του Κώδικα ΦΠΑ: πράξη λήπτη με 0% στη γραμμή, που όμως χαρακτηρίζεται
# ως 366 με πλασματικό ΦΠΑ (κανόνας 7.v). Στα δεδομένα υπάρχουν δύο τέτοιες γραμμές.
_ARTICLE_39A = 16

def _skip_for_vat(line) -> bool:
    if line.vat_category == 8:
        return True
    if line.vat_category == 7:
        return line.vat_exemption_category != _ARTICLE_39A
    return False

def vat_objects(doc, category: str) -> list[VatObject]:
    if category in _NO_VAT_CATEGORIES:
        return []
    code = vat_code_for(category)
    groups: dict[tuple, list[float]] = {}
    for line in doc.lines:
        if _skip_for_vat(line):
            continue
        if line.vat_exemption_category == _ARTICLE_39A:
            key = ("VAT_366", 1, _ARTICLE_39A)
        else:
            key = (code, line.vat_category, line.vat_exemption_category)
        acc = groups.setdefault(key, [0.0, 0.0])
        acc[0] += line.net
        acc[1] += line.vat_amount
    out = []
    for (obj_code, cat, exc), (net, vat) in sorted(
            groups.items(), key=lambda kv: (kv[0][1], kv[0][2] or 0)):
        if exc == _ARTICLE_39A:
            vat = notional_vat(net)
        out.append(VatObject(code=obj_code, vat_category=cat,
                             vat_exemption_category=exc,
                             amount=round(net, 2), vat_amount=round(vat, 2)))
    return out

@dataclass
class Selection:
    mark: str
    e3_type: str
    category: str

_E3_DETAIL = """        <expensesClassificationDetailData>
          <ecls:classificationType>{e3_type}</ecls:classificationType>
          <ecls:classificationCategory>{category}</ecls:classificationCategory>
          <ecls:amount>{amount:.2f}</ecls:amount>
        </expensesClassificationDetailData>"""

def _vat_detail_block(o: VatObject) -> str:
    lines = [
        "        <expensesClassificationDetailData>",
        f"          <ecls:classificationType>{o.code}</ecls:classificationType>",
        f"          <ecls:amount>{o.amount:.2f}</ecls:amount>",
        f"          <ecls:vatAmount>{o.vat_amount:.2f}</ecls:vatAmount>",
        f"          <ecls:vatCategory>{o.vat_category}</ecls:vatCategory>",
    ]
    if o.vat_exemption_category is not None:
        lines.append(
            f"          <ecls:vatExemptionCategory>{o.vat_exemption_category}"
            "</ecls:vatExemptionCategory>")
    lines.append("        </expensesClassificationDetailData>")
    return "\n".join(lines)

def _one_invoice(doc, sel: Selection) -> str:
    details = [_E3_DETAIL.format(e3_type=_x(sel.e3_type), category=_x(sel.category),
                                amount=e3_amount(doc, sel.category))]
    details.extend(_vat_detail_block(o) for o in vat_objects(doc, sel.category))
    body = "\n".join(details)
    # Το postPerInvoice δεν είναι στοιχείο XML — το XSD το απορρίπτει με
    # XMLSyntaxError 101 (invalid child element). Είναι query parameter στο URL της
    # κλήσης (?postPerInvoice=true), επιβεβαιωμένο στο dev sandbox 01/09/2026.
    return f"""  <expensesInvoiceClassification>
    <invoiceMark>{_x(doc.mark)}</invoiceMark>
    <invoicesExpensesClassificationDetails>
      <lineNumber>1</lineNumber>
{body}
    </invoicesExpensesClassificationDetails>
  </expensesInvoiceClassification>"""

# Το Ε3 αντικείμενο είναι ίδιο και στους δύο τρόπους, οπότε το _E3_DETAIL
# επαναχρησιμοποιείται. Το ΦΠΑ αντικείμενο διαφέρει: ανά γραμμή απαγορεύονται τα
# πεδία vatCategory/vatAmount/vatExemptionCategory (σφάλμα 337).
_VAT_LINE = """        <expensesClassificationDetailData>
          <ecls:classificationType>{code}</ecls:classificationType>
          <ecls:amount>{amount:.2f}</ecls:amount>
        </expensesClassificationDetailData>"""

def _per_line_invoice(doc, sel: Selection) -> str:
    """Τα τιμολόγια καυσίμων δεν δέχονται per-invoice χαρακτηρισμό (σφάλμα 335).
    Ανά γραμμή, τα πεδία ΦΠΑ απαγορεύονται (σφάλμα 337), οπότε τα αντικείμενα
    φέρουν μόνο τύπο, κατηγορία και ποσό."""
    if doc.other_taxes or doc.stamp_duty or doc.fees:
        raise ClassifyError(
            f"Το παραστατικό {doc.mark} φέρει λοιπούς φόρους/χαρτόσημα/τέλη και "
            "χαρακτηρίζεται ανά γραμμή, όπου ο κανόνας Ε3 i απαιτεί να τα περιλαμβάνει "
            "το άθροισμα των ποσών. Ο επιμερισμός τους ανά γραμμή δεν ορίζεται από την "
            "τεκμηρίωση — χαρακτήρισέ το από το portal.")
    blocks = []
    for n, line in enumerate(doc.lines, start=1):
        if line.vat_exemption_category == _ARTICLE_39A:
            raise ClassifyError(
                f"Το παραστατικό {doc.mark} έχει γραμμή άρθρου 39α και χαρακτηρίζεται ανά "
                "γραμμή. Ο κανόνας 7.v απαιτεί κωδικό 366 με ποσό ΦΠΑ μεγαλύτερο του "
                "μηδενός, αλλά ανά γραμμή τα πεδία ΦΠΑ απαγορεύονται (σφάλμα 337) — οι δύο "
                "κανόνες συγκρούονται. Χαρακτήρισέ το από το portal.")
        amount = line.net
        details = []
        if sel.category in _NO_VAT_CATEGORIES:
            amount += line.vat_amount
        details.append(_E3_DETAIL.format(e3_type=_x(sel.e3_type),
                                        category=_x(sel.category),
                                        amount=round(amount, 2)))
        if sel.category not in _NO_VAT_CATEGORIES and not _skip_for_vat(line):
            details.append(_VAT_LINE.format(code=vat_code_for(sel.category),
                                           amount=round(line.net, 2)))
        body = "\n".join(details)
        blocks.append(f"""    <invoicesExpensesClassificationDetails>
      <lineNumber>{line.line_number or n}</lineNumber>
{body}
    </invoicesExpensesClassificationDetails>""")
    joined = "\n".join(blocks)
    return f"""  <expensesInvoiceClassification>
    <invoiceMark>{_x(doc.mark)}</invoiceMark>
{joined}
  </expensesInvoiceClassification>"""

def build_classification_xml(pairs: list[tuple]) -> str:
    """Το lineNumber είναι συμβολικό στην per-invoice μέθοδο (αγνοείται, αλλά είναι
    mandatory στο σχήμα)· στην per-line μέθοδο των καυσίμων είναι το πραγματικό
    νούμερο γραμμής του παραστατικού."""
    if not pairs:
        raise ClassifyError("Δεν επιλέχθηκε κανένα παραστατικό για χαρακτηρισμό.")
    for doc, sel in pairs:
        if doc.inv_type == "1.5":
            raise ClassifyError(
                f"Το παραστατικό {doc.mark} είναι τύπου 1.5 — δεν υποστηρίζεται από αυτή "
                "τη μέθοδο (σφάλμα 335). Χαρακτήρισέ το από το portal.")
        if not sel.e3_type.startswith("E3_"):
            raise ClassifyError(
                f"Το παραστατικό {doc.mark} δεν έχει έγκυρο κωδικό Ε3 "
                f"(«{sel.e3_type}»). Διάλεξε κωδικό από τη λίστα.")
        if not sel.category.startswith("category"):
            raise ClassifyError(
                f"Το παραστατικό {doc.mark} δεν έχει έγκυρη κατηγορία "
                f"(«{sel.category}»). Διάλεξε κατηγορία από τη λίστα.")
    blocks = "\n".join(
        _per_line_invoice(doc, sel) if doc.fuel_invoice else _one_invoice(doc, sel)
        for doc, sel in pairs)
    # Το http:// στο root namespace απορρίπτεται με XMLSyntaxError 101 (schema not
    # found) — επιβεβαιώθηκε στο dev sandbox 01/09/2026.
    return f"""<?xml version="1.0" encoding="utf-8"?>
<ExpensesClassificationsDoc xmlns="https://www.aade.gr/myDATA/expensesClassificaton/v1.0"
                            xmlns:ecls="https://www.aade.gr/myDATA/expensesClassificaton/v1.0">
{blocks}
</ExpensesClassificationsDoc>"""

def build_classification_documents(pairs) -> list[tuple[bool, str]]:
    """Επιστρέφει [(per_invoice, xml), …] — ένα έγγραφο ανά τρόπο υποβολής, μόνο για
    τους τρόπους που έχουν παραστατικά. Το postPerInvoice είναι query parameter, άρα
    ισχύει για όλο το αίτημα: τα δύο σχήματα δεν συνυπάρχουν σε ένα POST."""
    if not pairs:
        raise ClassifyError("Δεν επιλέχθηκε κανένα παραστατικό για χαρακτηρισμό.")
    groups = ((True, [(d, s) for d, s in pairs if not d.fuel_invoice]),
              (False, [(d, s) for d, s in pairs if d.fuel_invoice]))
    return [(per_invoice, build_classification_xml(group))
            for per_invoice, group in groups if group]

def _local(tag: str) -> str:
    return tag.split("}")[-1]

def parse_classification_summary(xml_text: str) -> dict[str, dict]:
    """Εξάγει ανά invoiceMark τον κωδικό Ε3, την κατηγορία και το ποσό από το ήδη
    σταλμένο XML, ώστε το audit log να διαβάζεται χωρίς σταυρωτή αναφορά. Στα
    καύσιμα (ανά γραμμή) τα ποσά Ε3 των γραμμών αθροίζονται. Ο ΑΦΜ δεν υπάρχει στο
    XML του χαρακτηρισμού — μόνο το MARK."""
    root = ET.fromstring(xml_text)
    out: dict[str, dict] = {}
    for inv in root.iter():
        if _local(inv.tag) != "expensesInvoiceClassification":
            continue
        mark = next(((c.text or "").strip() for c in inv
                     if _local(c.tag) == "invoiceMark"), "")
        if not mark:
            continue
        item = {"e3_type": "", "category": "", "amount": 0.0}
        for det in inv.iter():
            if _local(det.tag) != "expensesClassificationDetailData":
                continue
            fields = {_local(f.tag): (f.text or "").strip() for f in det}
            if not fields.get("classificationType", "").startswith("E3_"):
                continue
            item["e3_type"] = fields["classificationType"]
            item["category"] = fields.get("classificationCategory", "")
            item["amount"] += float(fields.get("amount") or 0)
        item["amount"] = round(item["amount"], 2)
        out[mark] = item
    return out

def parse_classification_response(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    out = []
    for resp in root.iter():
        if resp.tag.split("}")[-1] != "response":
            continue
        item = {"invoice_mark": "", "classification_mark": "", "status": "", "errors": []}
        for child in resp:
            name = child.tag.split("}")[-1]
            if name == "invoiceMark":
                item["invoice_mark"] = (child.text or "").strip()
            elif name == "classificationMark":
                item["classification_mark"] = (child.text or "").strip()
            elif name == "statusCode":
                item["status"] = (child.text or "").strip()
            elif name == "errors":
                for err in child:
                    e = {"code": "", "message": ""}
                    for f in err:
                        fname = f.tag.split("}")[-1]
                        if fname in ("code", "message"):
                            e[fname] = (f.text or "").strip()
                    item["errors"].append(e)
        out.append(item)
    return out
