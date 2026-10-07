# ABOUTME: Tests των κανόνων χαρακτηρισμού Ε3/ΦΠΑ των guidelines postPerInvoice.
# ABOUTME: Κάθε test αντιστοιχεί σε έναν κανόνα της §7 του PDF.
from datetime import date
import pytest
from esoda_exoda.received import ReceivedDoc, VatLine
from esoda_exoda.classify import (ClassifyError, Selection, build_classification_documents,
                                  build_classification_xml,
                                  e3_amount, parse_classification_response,
                                  parse_classification_summary, vat_code_for,
                                  vat_objects)

def _norm(xml: str) -> str:
    return "".join(line.strip() for line in xml.splitlines())

def doc(lines, net=None, vat=None, other_taxes=0.0, stamp_duty=0.0, fees=0.0, fuel=False):
    net = sum(l.net for l in lines) if net is None else net
    vat = sum(l.vat_amount for l in lines) if vat is None else vat
    return ReceivedDoc(mark="900000000001000", issuer_vat="990000155", issuer_name="Χ",
                       counterpart_vat="123456783", series="Β", aa="1", date=date(2026, 7, 22), inv_type="1.1",
                       fuel_invoice=fuel, net=net, vat=vat, other_taxes=other_taxes,
                       stamp_duty=stamp_duty, fees=fees, lines=lines)

def test_vat_code_from_category():
    assert vat_code_for("category2_7") == "VAT_362"
    assert vat_code_for("category2_3") == "VAT_361"
    assert vat_code_for("category2_4") == "VAT_361"

def test_vat_code_refuses_unknown_category():
    with pytest.raises(ClassifyError, match="category9_9"):
        vat_code_for("category9_9")

def test_e3_amount_is_net_plus_other_taxes_stamp_and_fees():
    d = doc([VatLine(100.0, 1, 24.0)], other_taxes=5.0, stamp_duty=2.0, fees=1.5)
    assert e3_amount(d, "category2_4") == 108.5

def test_e3_amount_adds_unclassified_vat_for_category_2_5():
    """Κανόνας 7.ii: στην 2.5 δεν υποβάλλεται χαρακτηρισμός ΦΠΑ, άρα όλο το ΦΠΑ
    προστίθεται στο ποσό του Ε3 (αλλιώς σφάλμα 336)."""
    d = doc([VatLine(100.0, 1, 24.0)])
    assert e3_amount(d, "category2_5") == 124.0

def test_single_rate_invoice_gives_one_vat_object():
    d = doc([VatLine(50.0, 1, 12.0), VatLine(25.0, 1, 6.0)])
    objs = vat_objects(d, "category2_4")
    assert len(objs) == 1
    o = objs[0]
    assert (o.code, o.vat_category, o.amount, o.vat_amount) == ("VAT_361", 1, 75.0, 18.0)
    assert o.vat_exemption_category is None

def test_two_rates_give_two_vat_objects():
    d = doc([VatLine(100.0, 1, 24.0), VatLine(50.0, 2, 6.5)])
    objs = vat_objects(d, "category2_4")
    assert [(o.vat_category, o.amount, o.vat_amount) for o in objs] == [
        (1, 100.0, 24.0), (2, 50.0, 6.5)]

def test_vat_category_8_lines_are_excluded():
    d = doc([VatLine(100.0, 1, 24.0), VatLine(30.0, 8, 0.0)])
    objs = vat_objects(d, "category2_4")
    assert len(objs) == 1 and objs[0].amount == 100.0

def test_vat_category_7_is_excluded():
    assert vat_objects(doc([VatLine(80.0, 7, 0.0)]), "category2_4") == []

def test_article_39a_line_is_classified_as_366_with_notional_vat():
    """Κανόνας 7.v: γραμμή άρθρου 39α χαρακτηρίζεται με classificationType 366,
    vatCategory 1 (24%) και vatAmount > 0 — ΟΧΙ με το 0% της γραμμής. Είναι πράξη
    λήπτη, άρα το ΦΠΑ είναι πλασματικό, όπως στα 14.x της Φάσης 4."""
    objs = vat_objects(doc([VatLine(80.0, 7, 0.0, vat_exemption_category=16)]),
                       "category2_4")
    assert len(objs) == 1
    o = objs[0]
    assert (o.code, o.vat_category, o.vat_exemption_category) == ("VAT_366", 1, 16)
    assert (o.amount, o.vat_amount) == (80.0, 19.2)

def test_exemption_category_other_than_39a_is_excluded():
    """Στα δεδομένα υπάρχει και exemption 27, που δεν είναι πράξη λήπτη."""
    assert vat_objects(doc([VatLine(50.0, 7, 0.0, vat_exemption_category=27)]),
                       "category2_4") == []

def test_category_2_5_submits_no_vat_object():
    d = doc([VatLine(100.0, 1, 24.0)])
    assert vat_objects(d, "category2_5") == []

def test_category_2_9_submits_no_vat_object():
    d = doc([VatLine(100.0, 1, 24.0)])
    assert vat_objects(d, "category2_9") == []

def test_e3_amount_does_not_fold_vat_for_category_2_9():
    """Κανόνας 7.iii: η 2.9 δεν φέρει χαρακτηρισμό ΦΠΑ, αλλά το ποσό του Ε3 μένει
    καθαρή αξία + λοιποί φόροι (7.i). Μόνο η 2.5 απορροφά το ΦΠΑ."""
    d = doc([VatLine(100.0, 1, 24.0)], other_taxes=5.0)
    assert e3_amount(d, "category2_9") == 105.0
    assert e3_amount(d, "category2_5") == 129.0

def test_mixed_24_percent_and_article_39a_stay_separate():
    d = doc([VatLine(100.0, 1, 24.0), VatLine(80.0, 7, 0.0, vat_exemption_category=16)])
    objs = vat_objects(d, "category2_4")
    assert [(o.code, o.vat_category, o.vat_exemption_category, o.amount, o.vat_amount)
            for o in objs] == [("VAT_361", 1, None, 100.0, 24.0),
                               ("VAT_366", 1, 16, 80.0, 19.2)]

def test_document_with_only_exempt_lines_gives_no_vat_objects():
    """Παραστατικό εξ ολοκλήρου άνευ ΦΠΑ: κανένα αντικείμενο ΦΠΑ, το Ε3 μένει καθαρή αξία."""
    d = doc([VatLine(30.0, 8, 0.0)])
    assert vat_objects(d, "category2_4") == []
    assert e3_amount(d, "category2_4") == 30.0

def test_build_xml_has_one_e3_and_one_vat_object():
    d = doc([VatLine(50.0, 1, 12.0), VatLine(25.0, 1, 6.0)])
    xml = build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])
    n = _norm(xml)
    assert "<invoiceMark>900000000001000</invoiceMark>" in n
    assert n.count("<expensesClassificationDetailData>") == 2
    assert "<ecls:classificationType>E3_585_016</ecls:classificationType>" in n
    assert "<ecls:classificationCategory>category2_4</ecls:classificationCategory>" in n
    assert "<ecls:classificationType>VAT_361</ecls:classificationType>" in n
    assert "<ecls:amount>75.00</ecls:amount>" in n
    assert "<ecls:vatAmount>18.00</ecls:vatAmount>" in n
    assert "<ecls:vatCategory>1</ecls:vatCategory>" in n

def test_build_xml_category_2_5_has_only_e3_with_vat_folded_in():
    d = doc([VatLine(100.0, 1, 24.0)])
    xml = build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_5"))])
    n = _norm(xml)
    assert n.count("<expensesClassificationDetailData>") == 1
    assert "<ecls:amount>124.00</ecls:amount>" in n
    assert "VAT_" not in n

def test_build_xml_refuses_type_1_5():
    d = doc([VatLine(10.0, 1, 2.4)])
    d.inv_type = "1.5"
    with pytest.raises(ClassifyError, match="1.5"):
        build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])

def test_build_xml_escapes_and_batches_many_invoices():
    a = doc([VatLine(10.0, 1, 2.4)])
    b = doc([VatLine(20.0, 1, 4.8)])
    b.mark = "900000000001001"
    xml = build_classification_xml([(a, Selection(a.mark, "E3_585_016", "category2_4")),
                                    (b, Selection(b.mark, "E3_585_009", "category2_3"))])
    assert xml.count("<expensesInvoiceClassification>") == 2
    assert "900000000001001" in xml

def test_build_xml_omits_vat_block_when_all_lines_are_exempt():
    d = doc([VatLine(30.0, 8, 0.0)])
    xml = build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])
    n = _norm(xml)
    assert n.count("<expensesClassificationDetailData>") == 1
    assert "VAT_" not in n
    assert "<ecls:amount>30.00</ecls:amount>" in n

def test_parse_response_reports_per_invoice_success_and_errors():
    xml = """<?xml version="1.0" encoding="utf-8"?>
<ResponseDoc>
  <response>
    <invoiceMark>900000000001000</invoiceMark>
    <classificationMark>1000000000000001</classificationMark>
    <statusCode>Success</statusCode>
  </response>
  <response>
    <invoiceMark>900000000001001</invoiceMark>
    <statusCode>ValidationError</statusCode>
    <errors>
      <error><message>Invalid combination</message><code>339</code></error>
    </errors>
  </response>
</ResponseDoc>"""
    out = parse_classification_response(xml)
    assert out[0] == {"invoice_mark": "900000000001000",
                      "classification_mark": "1000000000000001",
                      "status": "Success", "errors": []}
    assert out[1]["status"] == "ValidationError"
    assert out[1]["errors"] == [{"code": "339", "message": "Invalid combination"}]

def test_fuel_invoice_is_built_per_line_without_vat_fields():
    d = doc([VatLine(45.0, 1, 10.8)], fuel=True)
    xml = build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])
    n = _norm(xml)
    assert "postPerInvoice" not in n
    assert "vatAmount" not in n and "vatCategory" not in n
    assert "vatExemptionCategory" not in n
    assert n.count("<expensesClassificationDetailData>") == 2
    assert "<ecls:classificationType>VAT_361</ecls:classificationType>" in n
    assert n.count("<ecls:amount>45.00</ecls:amount>") == 2

def test_fuel_invoice_uses_real_line_numbers():
    d = doc([VatLine(10.0, 1, 2.4), VatLine(20.0, 1, 4.8)], fuel=True)
    n = _norm(build_classification_xml(
        [(d, Selection(d.mark, "E3_585_016", "category2_4"))]))
    assert n.count("<invoicesExpensesClassificationDetails>") == 2
    assert "<lineNumber>1</lineNumber>" in n and "<lineNumber>2</lineNumber>" in n

def test_fuel_invoice_keeps_non_contiguous_line_numbers():
    """Με μη συνεχόμενη αρίθμηση, η σειρά της λίστας θα κολλούσε τον χαρακτηρισμό σε
    λάθος γραμμή — το πραγματικό lineNumber του RequestDocs είναι διαθέσιμο."""
    d = doc([VatLine(10.0, 1, 2.4, line_number=1),
             VatLine(20.0, 1, 4.8, line_number=3)], fuel=True)
    n = _norm(build_classification_xml(
        [(d, Selection(d.mark, "E3_585_016", "category2_4"))]))
    assert "<lineNumber>1</lineNumber>" in n and "<lineNumber>3</lineNumber>" in n
    assert "<lineNumber>2</lineNumber>" not in n

def test_fuel_invoice_category_2_5_folds_line_vat_into_e3():
    d = doc([VatLine(100.0, 1, 24.0)], fuel=True)
    n = _norm(build_classification_xml(
        [(d, Selection(d.mark, "E3_585_016", "category2_5"))]))
    assert n.count("<expensesClassificationDetailData>") == 1
    assert "<ecls:amount>124.00</ecls:amount>" in n

def test_mixed_batch_builds_both_shapes():
    plain = doc([VatLine(75.0, 1, 18.0)])
    fuel = doc([VatLine(45.0, 1, 10.8)], fuel=True)
    fuel.mark = "900000000001001"
    n = _norm(build_classification_xml(
        [(plain, Selection(plain.mark, "E3_585_016", "category2_4")),
         (fuel, Selection(fuel.mark, "E3_585_016", "category2_4"))]))
    assert "postPerInvoice" not in n
    assert n.count("<expensesInvoiceClassification>") == 2

def test_per_line_refuses_document_with_other_taxes():
    d = doc([VatLine(100.0, 1, 24.0)], other_taxes=5.0, fees=1.5, fuel=True)
    with pytest.raises(ClassifyError, match="Ε3 i"):
        build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])

def test_per_line_refuses_article_39a_line():
    d = doc([VatLine(80.0, 7, 0.0, vat_exemption_category=16)], fuel=True)
    with pytest.raises(ClassifyError, match="39α"):
        build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])

def test_type_1_5_is_refused_even_when_marked_as_fuel():
    d = doc([VatLine(10.0, 1, 2.4)], fuel=True)
    d.inv_type = "1.5"
    with pytest.raises(ClassifyError, match="1.5"):
        build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])

def test_build_xml_refuses_empty_e3_type():
    """Κενό e3_type (π.χ. παραστατικό με μόνο αντικείμενο ΦΠΑ) δεν πρέπει να φτάσει
    ποτέ σε XML ως κενό <classificationType>."""
    d = doc([VatLine(10.0, 1, 2.4)])
    with pytest.raises(ClassifyError, match="κωδικό Ε3"):
        build_classification_xml([(d, Selection(d.mark, "", "category2_4"))])

def test_build_xml_refuses_empty_category():
    d = doc([VatLine(10.0, 1, 2.4)])
    with pytest.raises(ClassifyError, match="κατηγορία"):
        build_classification_xml([(d, Selection(d.mark, "E3_585_016", ""))])

def test_classification_summary_reads_e3_category_and_amount():
    d = doc([VatLine(50.0, 1, 12.0), VatLine(25.0, 1, 6.0)])
    xml = build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])
    assert parse_classification_summary(xml) == {
        d.mark: {"e3_type": "E3_585_016", "category": "category2_4", "amount": 75.0}}

def test_classification_summary_sums_per_line_amounts_of_fuel_invoice():
    d = doc([VatLine(10.0, 1, 2.4, line_number=1),
             VatLine(20.0, 1, 4.8, line_number=2)], fuel=True)
    xml = build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])
    assert parse_classification_summary(xml)[d.mark]["amount"] == 30.0

def test_classification_summary_ignores_vat_objects():
    """Μόνο το αντικείμενο Ε3 φέρει κατηγορία και το ποσό του Ε3 — τα VAT_361
    δεν πρέπει να προσμετρώνται στο ποσό του log."""
    d = doc([VatLine(100.0, 1, 24.0)])
    xml = build_classification_xml([(d, Selection(d.mark, "E3_585_016", "category2_4"))])
    assert "VAT_361" in xml
    assert parse_classification_summary(xml)[d.mark]["amount"] == 100.0

def test_build_documents_gives_one_per_invoice_document_without_fuel():
    d = doc([VatLine(10.0, 1, 2.4)])
    docs = build_classification_documents(
        [(d, Selection(d.mark, "E3_585_016", "category2_4"))])
    assert [mode for mode, _ in docs] == [True]
    assert d.mark in docs[0][1]

def test_build_documents_gives_one_per_line_document_for_fuel_only():
    d = doc([VatLine(10.0, 1, 2.4, line_number=1)], fuel=True)
    docs = build_classification_documents(
        [(d, Selection(d.mark, "E3_585_016", "category2_4"))])
    assert [mode for mode, _ in docs] == [False]
    assert d.mark in docs[0][1]

def test_build_documents_splits_mixed_selection_with_per_invoice_first():
    """Το postPerInvoice είναι query parameter, άρα ισχύει για όλο το αίτημα: τα
    καύσιμα δεν μπορούν να συνυπάρχουν με τα κανονικά σε ένα POST."""
    a = doc([VatLine(10.0, 1, 2.4)])
    b = doc([VatLine(20.0, 1, 4.8, line_number=1)], fuel=True)
    b.mark = "900000000001001"
    docs = build_classification_documents(
        [(b, Selection(b.mark, "E3_585_016", "category2_4")),
         (a, Selection(a.mark, "E3_585_016", "category2_4"))])
    assert [mode for mode, _ in docs] == [True, False]
    assert a.mark in docs[0][1] and b.mark not in docs[0][1]
    assert b.mark in docs[1][1] and a.mark not in docs[1][1]
    assert all("postPerInvoice" not in xml for _, xml in docs)

def test_build_documents_refuses_empty_selection():
    with pytest.raises(ClassifyError, match="κανένα παραστατικό"):
        build_classification_documents([])
