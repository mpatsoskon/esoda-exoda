# ABOUTME: Tests δόμησης XML διαβίβασης και υπολογισμού επόμενου ΑΑ.
# ABOUTME: Το 17.2 συγκρίνεται με το XML που δέχτηκε η ΑΑΔΕ στις 20/07/2026.
import re
from dataclasses import replace
from datetime import date
import pytest
import xml.etree.ElementTree as ET
from esoda_exoda.classifications import SelfDeclared
from esoda_exoda.counterparties import ForeignSupplier
from esoda_exoda.transmit import (
    Entry, TransmitError, build_xml, build_xml_14, next_aa, notional_vat,
    parse_amount, parse_entry_summary, parse_issue_date, parse_response)

ACCEPTED_172 = """<?xml version="1.0" encoding="utf-8"?>
<InvoicesDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0"
             xmlns:ecls="https://www.aade.gr/myDATA/expensesClassificaton/v1.0">
  <invoice>
    <issuer>
      <vatNumber>123456783</vatNumber>
      <country>GR</country>
      <branch>0</branch>
    </issuer>
    <invoiceHeader>
      <series>0</series>
      <aa>1</aa>
      <issueDate>2025-12-31</issueDate>
      <invoiceType>17.2</invoiceType>
      <currency>EUR</currency>
    </invoiceHeader>
    <invoiceDetails>
      <lineNumber>1</lineNumber>
      <netValue>1250.40</netValue>
      <vatCategory>8</vatCategory>
      <vatAmount>0.00</vatAmount>
      <expensesClassification>
        <ecls:classificationType>E3_587</ecls:classificationType>
        <ecls:classificationCategory>category2_8</ecls:classificationCategory>
        <ecls:amount>1250.40</ecls:amount>
      </expensesClassification>
    </invoiceDetails>
    <invoiceSummary>
      <totalNetValue>1250.40</totalNetValue>
      <totalVatAmount>0.00</totalVatAmount>
      <totalWithheldAmount>0.00</totalWithheldAmount>
      <totalFeesAmount>0.00</totalFeesAmount>
      <totalStampDutyAmount>0.00</totalStampDutyAmount>
      <totalOtherTaxesAmount>0.00</totalOtherTaxesAmount>
      <totalDeductionsAmount>0.00</totalDeductionsAmount>
      <totalGrossValue>1250.40</totalGrossValue>
      <expensesClassification>
        <ecls:classificationType>E3_587</ecls:classificationType>
        <ecls:classificationCategory>category2_8</ecls:classificationCategory>
        <ecls:amount>1250.40</ecls:amount>
      </expensesClassification>
    </invoiceSummary>
  </invoice>
</InvoicesDoc>
"""

def _norm(xml: str) -> str:
    return "".join(line.strip() for line in xml.splitlines())

def test_build_xml_matches_the_invoice_aade_accepted():
    entry = Entry(inv_type="17.2", series="0", aa="1", issue_date=date(2025, 12, 31),
                  net=1250.40, vat=0.0, vat_category="8",
                  e3_type="E3_587", category="category2_8")
    assert _norm(build_xml(entry, "123456783")) == _norm(ACCEPTED_172)

def test_build_xml_13_3_uses_counterpart_and_no_issuer():
    """Το myDATA απορρίπτει τα 13.x με «Counterpart is mandatory for this invoice type·
    Issuer is forbidden for this invoice type». Τα δεκτά 13.3 φέρουν το ΑΦΜ μας σε
    counterpart με διεύθυνση, χωρίς issuer."""
    entry = Entry(inv_type="13.3", series="123456783", aa="8000000020",
                  issue_date=date(2026, 8, 1), net=12.0, vat=0.0, vat_category="8",
                  e3_type="E3_585_016", category="category2_3")
    xml = build_xml(entry, "123456783", "10000", "ΑΛΦΑΠΟΛΗ")
    assert "<issuer>" not in xml
    assert "<counterpart>" in xml
    assert _norm("""<counterpart>
      <vatNumber>123456783</vatNumber>
      <country>GR</country>
      <branch>0</branch>
      <address>
        <postalCode>10000</postalCode>
        <city>ΑΛΦΑΠΟΛΗ</city>
      </address>
    </counterpart>""") in _norm(xml)
    assert "<invoiceType>13.3</invoiceType>" in xml
    assert "<netValue>12.00</netValue>" in xml
    assert "<totalGrossValue>12.00</totalGrossValue>" in xml

def test_build_xml_13_3_refuses_without_address():
    entry = Entry(inv_type="13.3", series="0", aa="3", issue_date=date(2026, 3, 31),
                  net=120.0, vat=0.0, vat_category="8",
                  e3_type="E3_585_016", category="category2_3")
    with pytest.raises(TransmitError, match="postal_code"):
        build_xml(entry, "123456783", "", "")

def test_next_aa_starts_at_one_and_increments_per_type_and_year():
    def sd(inv_type, aa, year):
        return SelfDeclared(mark="M", uid="U", inv_type=inv_type, series="0", aa=aa,
                            date=date(year, 6, 1), net=1.0, vat=0.0,
                            e3_type="E3_587", category="category2_8")
    assert next_aa([], "13.3", 2026) == 1
    assert next_aa([sd("13.3", "1", 2026), sd("13.3", "2", 2026)], "13.3", 2026) == 3
    assert next_aa([sd("13.3", "9", 2025)], "13.3", 2026) == 1
    assert next_aa([sd("17.2", "4", 2026)], "13.3", 2026) == 1

SUCCESS_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<ResponseDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<response><index>1</index>
<invoiceUid>A000000000000000000000000000000000000001</invoiceUid>
<invoiceMark>900000000001046</invoiceMark>
<statusCode>Success</statusCode></response>
</ResponseDoc>"""

VALIDATION_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<ResponseDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<response><index>1</index><statusCode>ValidationError</statusCode>
<errors><error><message>Invalid vatCategory</message><code>219</code></error>
<error><message>Λάθος ΑΑ</message><code>220</code></error></errors>
</response></ResponseDoc>"""

def test_parse_response_returns_mark_and_uid_on_success():
    out = parse_response(SUCCESS_RESPONSE)
    assert out["mark"] == "900000000001046"
    assert out["uid"] == "A000000000000000000000000000000000000001"

def test_parse_response_raises_with_all_errors_on_validation_error():
    with pytest.raises(TransmitError) as exc:
        parse_response(VALIDATION_RESPONSE)
    msg = str(exc.value)
    assert "ValidationError" in msg
    assert "Invalid vatCategory" in msg
    assert "Λάθος ΑΑ" in msg

def test_parse_response_raises_when_no_response_element():
    with pytest.raises(TransmitError):
        parse_response('<?xml version="1.0"?><ResponseDoc/>')

def test_parse_response_raises_on_success_without_mark():
    success_no_mark = """<?xml version="1.0" encoding="utf-8"?>
<ResponseDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<response><statusCode>Success</statusCode><invoiceUid>U1</invoiceUid></response>
</ResponseDoc>"""
    with pytest.raises(TransmitError) as exc:
        parse_response(success_no_mark)
    msg = str(exc.value)
    assert "MARK" in msg or "mark" in msg
    assert "Success" in msg

def test_parse_response_includes_codes_when_no_messages():
    error_no_message = """<?xml version="1.0" encoding="utf-8"?>
<ResponseDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<response><statusCode>XMLSyntaxError</statusCode>
<errors><error><code>500</code></error><error><code>501</code></error></errors>
</response></ResponseDoc>"""
    with pytest.raises(TransmitError) as exc:
        parse_response(error_no_message)
    msg = str(exc.value)
    assert "XMLSyntaxError" in msg
    assert ("500" in msg or "501" in msg)

def test_parse_amount_greek_form_with_thousands_and_decimals():
    assert parse_amount("1.250,40") == 1250.40

def test_parse_amount_plain_machine_decimal():
    assert parse_amount("1250.40") == 1250.40

def test_parse_amount_plain_integer():
    assert parse_amount("120") == 120.0

def test_parse_amount_greek_decimal_without_thousands():
    assert parse_amount("120,50") == 120.50

def test_parse_amount_rejects_ambiguous_thousands_looking_value():
    with pytest.raises(TransmitError) as exc:
        parse_amount("1.250")
    assert "Αμφίσημο" in str(exc.value)

def test_ambiguous_amount_message_does_not_offer_an_unwritable_reading():
    """Η ανάγνωση «1,250» δεν γράφεται: ο parse_amount δέχεται μέχρι δύο δεκαδικά.
    Το μήνυμα δεν επιτρέπεται να την προσφέρει ως επιλογή, γιατί στέλνει τον χρήστη
    να γράψει κάτι που θα απορριφθεί ξανά."""
    with pytest.raises(TransmitError):
        parse_amount("1,250")
    with pytest.raises(TransmitError) as exc:
        parse_amount("1.250")
    msg = str(exc.value)
    assert "1250" in msg
    assert "1.250 €" not in msg

def test_ambiguous_amount_message_suggests_only_writable_rewrites():
    """Κάθε γραφή που προτείνει το μήνυμα πρέπει να γίνεται δεκτή από τον ίδιο τον
    parse_amount και να δίνει την τιμή που το μήνυμα λέει ότι εννοεί — αλλιώς η
    οδηγία στέλνει τον χρήστη σε δεύτερη άρνηση."""
    with pytest.raises(TransmitError) as exc:
        parse_amount("1.250")
    advice = str(exc.value).split("Γράψε το ρητά")[1]
    suggestions = re.findall(r"«([^»]+)»", advice)
    assert suggestions
    for s in suggestions:
        try:
            assert parse_amount(s) == 1250.0
        except TransmitError as e:
            pytest.fail(f"Το μήνυμα προτείνει «{s}», που απορρίπτεται: {e}")

def _foreign_supplier():
    return ForeignSupplier(name="FOREIGN SUPPLIER A B.V.", vat="NL999999003B01", country="NL",
                    postal_code="1017", city="Amsterdam", inv_type="14.3",
                    e3="E3_585_010", category="category2_3")

def _local(tag): return tag.split("}")[-1]

def _els(root, name):
    return [e for e in root.iter() if _local(e.tag) == name]

def _txt(elem, name):
    for e in elem.iter():
        if _local(e.tag) == name:
            return (e.text or "").strip()
    return ""

def test_build_xml_14_issuer_counterpart_and_line():
    xml = build_xml_14(_foreign_supplier(), date(2026, 7, 31), net=117.30, aa="1",
                       afm="123456783", postal_code="10000", city="ΑΛΦΑΠΟΛΗ")
    root = ET.fromstring(xml)
    issuer = _els(root, "issuer")[0]
    assert _txt(issuer, "vatNumber") == "NL999999003B01"
    assert _txt(issuer, "country") == "NL"
    assert _txt(issuer, "name") == "FOREIGN SUPPLIER A B.V."
    assert _txt(issuer, "postalCode") == "1017" and _txt(issuer, "city") == "Amsterdam"
    cp = _els(root, "counterpart")[0]
    assert _txt(cp, "vatNumber") == "123456783" and _txt(cp, "country") == "GR"
    assert not _els(cp, "name")          # όνομα απαγορεύεται για GR
    assert _txt(cp, "postalCode") == "10000" and _txt(cp, "city") == "ΑΛΦΑΠΟΛΗ"
    header = _els(root, "invoiceHeader")[0]
    assert _txt(header, "invoiceType") == "14.3"
    assert _txt(header, "series") == "0" and _txt(header, "aa") == "1"
    assert _txt(header, "currency") == "EUR"
    details = _els(root, "invoiceDetails")[0]
    assert _txt(details, "netValue") == "117.30"
    assert _txt(details, "vatCategory") == "1"
    assert _txt(details, "vatAmount") == "28.15"

def test_build_xml_14_classifications_e3_plus_vat365():
    xml = build_xml_14(_foreign_supplier(), date(2026, 7, 31), net=117.30, aa="1",
                       afm="123456783", postal_code="10000", city="ΑΛΦΑΠΟΛΗ")
    root = ET.fromstring(xml)
    for scope_name in ("invoiceDetails", "invoiceSummary"):
        scope = _els(root, scope_name)[0]
        cls = _els(scope, "expensesClassification")
        assert len(cls) == 2
        e3 = next(c for c in cls if _txt(c, "classificationType") == "E3_585_010")
        assert _txt(e3, "classificationCategory") == "category2_3"
        assert _txt(e3, "amount") == "117.30"
        vat = next(c for c in cls if _txt(c, "classificationType") == "VAT_365")
        assert not _els(vat, "classificationCategory")   # χωρίς category, όπως το επίσημο δείγμα
        assert _txt(vat, "amount") == "117.30"           # καθαρή αξία, όχι το ΦΠΑ
    summary = _els(root, "invoiceSummary")[0]
    assert _txt(summary, "totalVatAmount") == "28.15"
    assert _txt(summary, "totalGrossValue") == "145.45"

def test_build_xml_14_uses_vat_366_for_third_countries():
    sup = ForeignSupplier(name="FOREIGN SUPPLIER B", vat="000000000", country="US",
                   postal_code="10001", city="New York", inv_type="14.4",
                   e3="E3_585_010", category="category2_3")
    xml = build_xml_14(sup, date(2026, 7, 31), net=50.0, aa="1",
                       afm="123456783", postal_code="10000", city="ΑΛΦΑΠΟΛΗ")
    assert "VAT_366" in xml and "VAT_365" not in xml
    assert "<invoiceType>14.4</invoiceType>" in xml

def test_build_xml_14_escapes_supplier_name():
    sup = replace(_foreign_supplier(), name="A&B <Cloud>")
    xml = build_xml_14(sup, date(2026, 7, 31), net=10.0, aa="1",
                       afm="123456783", postal_code="10000", city="ΑΛΦΑΠΟΛΗ")
    root = ET.fromstring(xml)      # δεν σκάει το parse
    assert _txt(_els(root, "issuer")[0], "name") == "A&B <Cloud>"

def test_notional_vat_is_24_percent_two_decimals():
    assert notional_vat(117.30) == 28.15
    assert notional_vat(100.10) == 24.02
    assert notional_vat(10.31) == 2.47

def test_parse_entry_summary_includes_issuer():
    xml = build_xml_14(_foreign_supplier(), date(2026, 7, 31), net=117.30, aa="1",
                       afm="123456783", postal_code="10000", city="ΑΛΦΑΠΟΛΗ")
    s = parse_entry_summary(xml)
    assert s["issuer_vat"] == "NL999999003B01"
    assert s["issuer_name"] == "FOREIGN SUPPLIER A B.V."
    assert s["inv_type"] == "14.3" and s["net"] == 117.30

def test_build_xml_14_escapes_e3_and_category():
    sup = replace(_foreign_supplier(), e3="E3_585_010 & <A>", category="category2_3 & <B>")
    xml = build_xml_14(sup, date(2026, 7, 31), net=10.0, aa="1",
                       afm="123456783", postal_code="10000", city="ΑΛΦΑΠΟΛΗ")
    root = ET.fromstring(xml)      # δεν σκάει το parse
    details = _els(root, "invoiceDetails")[0]
    e3 = next(c for c in _els(details, "expensesClassification")
              if _txt(c, "classificationType") == "E3_585_010 & <A>")
    assert _txt(e3, "classificationCategory") == "category2_3 & <B>"

def test_parse_issue_date_accepts_the_greek_ui_form():
    """Το ορατό πεδίο στέλνει dd-mm-yyyy: το native input[type=date] αποδίδει σε
    μορφή του browser (en-US έδειχνε 9/2/2026), οπότε η μορφή δηλώνεται ρητά."""
    assert parse_issue_date("02-09-2026") == date(2026, 9, 2)
    assert parse_issue_date(" 31-12-2025 ") == date(2025, 12, 31)

def test_parse_issue_date_still_accepts_iso():
    """Η ISO μορφή μένει δεκτή: είναι ό,τι στέλνει ένα scripted POST και ό,τι
    γράφεται στα logs."""
    assert parse_issue_date("2026-09-02") == date(2026, 9, 2)

def test_parse_issue_date_refuses_anything_else():
    for raw in ("2/9/2026", "02/09/2026", "9-2-26", "", "αύριο"):
        with pytest.raises(TransmitError) as exc:
            parse_issue_date(raw)
        assert "dd-mm-yyyy" in str(exc.value)

def test_parse_issue_date_refuses_an_impossible_day():
    with pytest.raises(TransmitError):
        parse_issue_date("31-02-2026")
