# ABOUTME: Tests parsing χαρακτηρισμών από RequestTransmittedDocs.
# ABOUTME: Χρησιμοποιεί το πραγματικό (μικρό) fixture, χωρίς δίκτυο.
from esoda_exoda.classifications import parse_transmitted, parse_doc_headers, parse_self_declared

def test_parse_income_and_expense(fixtures_dir):
    m = parse_transmitted((fixtures_dir / "mydata_transmitted_sample.xml").read_text(encoding="utf-8"))
    inc = m["900000000001007"]
    assert inc.kind == "income" and inc.e3_type == "E3_561_001" and inc.category == "category1_3"
    exp = m["900000000001008"]
    assert exp.kind == "expense" and exp.e3_type == "E3_585_016" and exp.category == "category2_5"

def test_parse_doc_headers(fixtures_dir):
    h = parse_doc_headers((fixtures_dir / "mydata_transmitted_sample.xml").read_text(encoding="utf-8"))
    assert h["900000000001007"] == ("Α", "1")
    assert h["900000000001008"] == ("090000149", "8000000001")

SELF_DECLARED_DOC = """<?xml version="1.0" encoding="utf-8"?>
<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0"
              xmlns:ecls="https://www.aade.gr/myDATA/expensesClassificaton/v1.0"
              xmlns:icls="https://www.aade.gr/myDATA/incomeClassificaton/v1.0">
<invoicesDoc>
<invoice><uid>UID13</uid><mark>900000000001000</mark>
<invoiceHeader><series>0</series><aa>3</aa><issueDate>2026-03-31</issueDate>
<invoiceType>13.3</invoiceType></invoiceHeader>
<invoiceDetails><lineNumber>1</lineNumber><netValue>120.00</netValue>
<vatCategory>8</vatCategory><vatAmount>0.00</vatAmount>
<expensesClassification><ecls:classificationType>E3_585_016</ecls:classificationType>
<ecls:classificationCategory>category2_5</ecls:classificationCategory>
<ecls:amount>120.00</ecls:amount></expensesClassification></invoiceDetails>
<invoiceSummary><totalNetValue>120.00</totalNetValue><totalVatAmount>0.00</totalVatAmount>
<expensesClassification><ecls:classificationType>E3_585_016</ecls:classificationType>
<ecls:classificationCategory>category2_5</ecls:classificationCategory>
<ecls:amount>120.00</ecls:amount></expensesClassification></invoiceSummary>
</invoice>
<invoice><uid>UID17</uid><mark>900000000001001</mark>
<invoiceHeader><series>0</series><aa>1</aa><issueDate>2025-12-31</issueDate>
<invoiceType>17.2</invoiceType></invoiceHeader>
<invoiceDetails><lineNumber>1</lineNumber><netValue>1250.40</netValue>
<vatCategory>8</vatCategory><vatAmount>0.00</vatAmount>
<expensesClassification><ecls:classificationType>E3_587</ecls:classificationType>
<ecls:classificationCategory>category2_8</ecls:classificationCategory>
<ecls:amount>1250.40</ecls:amount></expensesClassification></invoiceDetails>
<invoiceSummary><totalNetValue>1250.40</totalNetValue><totalVatAmount>0.00</totalVatAmount>
</invoiceSummary></invoice>
<invoice><uid>UID21</uid><mark>900000000001002</mark>
<invoiceHeader><series>Α</series><aa>5</aa><issueDate>2026-02-10</issueDate>
<invoiceType>2.1</invoiceType></invoiceHeader>
<invoiceDetails><lineNumber>1</lineNumber><netValue>500.00</netValue>
<vatCategory>1</vatCategory><vatAmount>120.00</vatAmount>
<incomeClassification><icls:classificationType>E3_561_001</icls:classificationType>
<icls:classificationCategory>category1_3</icls:classificationCategory>
<icls:amount>500.00</icls:amount></incomeClassification></invoiceDetails>
</invoice>
</invoicesDoc></RequestedDoc>"""

def test_parse_self_declared_keeps_only_expense_classified():
    from datetime import date
    from esoda_exoda.classifications import parse_self_declared
    rows = parse_self_declared(SELF_DECLARED_DOC)
    assert [r.inv_type for r in rows] == ["13.3", "17.2"]
    first = rows[0]
    assert first.mark == "900000000001000"
    assert first.uid == "UID13"
    assert first.series == "0" and first.aa == "3"
    assert first.date == date(2026, 3, 31)
    assert first.net == 120.0 and first.vat == 0.0
    assert first.e3_type == "E3_585_016" and first.category == "category2_5"
    assert rows[1].net == 1250.40

def test_parse_self_declared_populates_cancelled_by_from_real_fixture(fixtures_dir):
    from esoda_exoda.classifications import parse_self_declared
    rows = parse_self_declared(
        (fixtures_dir / "mydata_transmitted_sample.xml").read_text(encoding="utf-8"))
    assert len(rows) == 1
    row = rows[0]
    assert row.mark == "900000000001008"
    assert row.cancelled_by == "900000000001009"

DUAL_CLASSIFICATION_DOC = """<?xml version="1.0" encoding="utf-8"?>
<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0"
              xmlns:ecls="https://www.aade.gr/myDATA/expensesClassificaton/v1.0">
<invoicesDoc>
<invoice><uid>UID14</uid><mark>900000000001003</mark>
<invoiceHeader><series>0</series><aa>1</aa><issueDate>2026-05-10</issueDate>
<invoiceType>14.3</invoiceType></invoiceHeader>
<invoiceDetails><lineNumber>1</lineNumber><netValue>500.00</netValue>
<vatCategory>1</vatCategory><vatAmount>120.00</vatAmount>
<expensesClassification><ecls:classificationType>VAT_365</ecls:classificationType>
<ecls:amount>120.00</ecls:amount></expensesClassification>
<expensesClassification><ecls:classificationType>E3_585_016</ecls:classificationType>
<ecls:classificationCategory>category2_5</ecls:classificationCategory>
<ecls:amount>500.00</ecls:amount></expensesClassification></invoiceDetails>
</invoice>
</invoicesDoc></RequestedDoc>"""

def test_parse_self_declared_prefers_e3_classification_when_vat_classification_first():
    from esoda_exoda.classifications import parse_self_declared
    rows = parse_self_declared(DUAL_CLASSIFICATION_DOC)
    assert len(rows) == 1
    assert rows[0].e3_type == "E3_585_016"
    assert rows[0].category == "category2_5"

def test_parse_transmitted_prefers_e3_classification_when_vat_classification_first():
    # Ίδιο σχήμα με τα 14.x: expensesClassification VAT_365 πρώτο, E3_* δεύτερο.
    # Χωρίς τη διόρθωση, το category θα ήταν "" και το ΦΠΑ θα φαινόταν εκπεστέο.
    m = parse_transmitted(DUAL_CLASSIFICATION_DOC)
    cl = m["900000000001003"]
    assert cl.kind == "expense"
    assert cl.e3_type == "E3_585_016"
    assert cl.category == "category2_5"

def test_parse_self_declared_extracts_foreign_issuer_vat():
    xml = """<?xml version="1.0" encoding="utf-8"?>
<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
<invoicesDoc><invoice><uid>U14</uid><mark>M14</mark>
<issuer><vatNumber>NL999999003B01</vatNumber><country>NL</country><branch>0</branch>
<name>FOREIGN SUPPLIER A B.V.</name></issuer>
<counterpart><vatNumber>123456783</vatNumber><country>GR</country><branch>0</branch></counterpart>
<invoiceHeader><series>0</series><aa>1</aa><issueDate>2026-07-31</issueDate>
<invoiceType>14.3</invoiceType></invoiceHeader>
<invoiceDetails><netValue>117.30</netValue><vatAmount>28.15</vatAmount>
<expensesClassification><classificationType>E3_585_010</classificationType>
<classificationCategory>category2_3</classificationCategory></expensesClassification>
<expensesClassification><classificationType>VAT_365</classificationType>
</expensesClassification></invoiceDetails>
</invoice></invoicesDoc></RequestedDoc>"""
    sds = parse_self_declared(xml)
    assert len(sds) == 1
    sd = sds[0]
    assert sd.issuer_vat == "NL999999003B01"
    assert sd.inv_type == "14.3" and sd.e3_type == "E3_585_010"
