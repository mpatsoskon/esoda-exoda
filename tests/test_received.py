# ABOUTME: Tests parse ληφθέντων παραστατικών από το RequestDocs.
# ABOUTME: Το fixture είναι πραγματικό δείγμα RequestedDoc.
from datetime import date
import pytest
from esoda_exoda.received import parse_received

def test_parse_received_reads_header_and_totals(fixtures_dir):
    docs = parse_received((fixtures_dir / "mydata_received_sample.xml").read_text(encoding="utf-8"))
    d = [x for x in docs if x.mark == "900000000001048"][0]
    assert d.issuer_vat == "990000155"
    assert d.issuer_name == "ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ"
    assert d.counterpart_vat == "123456783"
    assert (d.series, d.aa) == ("Β", "0003095")
    assert d.date == date(2026, 7, 22)
    assert d.inv_type == "1.1"
    assert d.net == 75.0 and d.vat == 18.0
    assert d.other_taxes == 0.0 and d.stamp_duty == 0.0 and d.fees == 0.0
    assert d.fuel_invoice is False

def test_parse_received_reads_vat_lines(fixtures_dir):
    docs = parse_received((fixtures_dir / "mydata_received_sample.xml").read_text(encoding="utf-8"))
    d = [x for x in docs if x.mark == "900000000001048"][0]
    assert len(d.lines) == 2
    assert [(l.net, l.vat_category, l.vat_amount) for l in d.lines] == [
        (50.0, 1, 12.0), (25.0, 1, 6.0)]
    assert all(l.vat_exemption_category is None for l in d.lines)
    assert [l.line_number for l in d.lines] == [1, 2]

def test_parse_received_flags_fuel_invoice(fixtures_dir):
    docs = parse_received((fixtures_dir / "mydata_received_sample.xml").read_text(encoding="utf-8"))
    d = [x for x in docs if x.mark == "900000000001047"][0]
    assert d.fuel_invoice is True
    assert d.issuer_name == "ΠΡΟΜΗΘΕΥΤΗΣ Α A.E."

def test_parse_received_handles_pagination_marker(fixtures_dir):
    raw = (fixtures_dir / "mydata_received_sample.xml").read_text(encoding="utf-8")
    two_pages = raw + "\n<!-- PAGE BREAK -->\n" + raw
    assert len(parse_received(two_pages)) == 4

def test_parse_received_refuses_present_but_empty_amount():
    """Υπαρκτό αλλά κενό ποσό είναι χαλασμένο δεδομένο, όχι μηδέν."""
    xml = """<?xml version="1.0" encoding="utf-8"?>
<RequestedDoc><invoicesDoc><invoice>
  <mark>900000000001004</mark>
  <invoiceHeader><series>Α</series><aa>1</aa>
    <issueDate>2026-07-01</issueDate><invoiceType>1.1</invoiceType></invoiceHeader>
  <invoiceDetails><lineNumber>1</lineNumber><netValue></netValue>
    <vatCategory>1</vatCategory><vatAmount>2.40</vatAmount></invoiceDetails>
  <invoiceSummary><totalNetValue>10.00</totalNetValue>
    <totalVatAmount>2.40</totalVatAmount></invoiceSummary>
</invoice></invoicesDoc></RequestedDoc>"""
    with pytest.raises(ValueError, match="900000000001004"):
        parse_received(xml)

def test_parse_received_names_the_mark_on_missing_issue_date():
    xml = """<?xml version="1.0" encoding="utf-8"?>
<RequestedDoc><invoicesDoc><invoice>
  <mark>900000000001005</mark>
  <invoiceHeader><series>Α</series><aa>1</aa><invoiceType>1.1</invoiceType></invoiceHeader>
  <invoiceSummary><totalNetValue>10.00</totalNetValue>
    <totalVatAmount>2.40</totalVatAmount></invoiceSummary>
</invoice></invoicesDoc></RequestedDoc>"""
    with pytest.raises(ValueError, match="900000000001005"):
        parse_received(xml)
