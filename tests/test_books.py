# ABOUTME: Tests parsing του myDATA RequestedBookInfo XML σε Record.
# ABOUTME: Δοκιμάζει ότι οι εγγραφές βιβλίων αναλύονται σωστά από myDATA XML.
from datetime import date
import pytest
from esoda_exoda.books import parse_book

def test_parse_income_first_record(fixtures_dir):
    recs = parse_book((fixtures_dir / "mydata_income_2025.xml").read_text(encoding="utf-8"))
    assert len(recs) >= 3
    r = recs[0]
    assert r.counter_vat == "990000106"
    assert r.issue_date == date(2025, 5, 30)
    assert r.inv_type == "1.1"
    assert r.net == 1000.0
    assert r.vat == 240.0
    assert r.withheld == 200.0
    assert r.mark == "900000000001028"

def test_parse_missing_issue_date_names_the_mark():
    xml = ("<RequestedBookInfo><bookInfo>"
           "<counterVatNumber>990000106</counterVatNumber>"
           "<invType>1.1</invType><netValue>10.00</netValue>"
           "<minMark>900000000001028</minMark>"
           "</bookInfo></RequestedBookInfo>")
    with pytest.raises(ValueError, match="issueDate.*900000000001028"):
        parse_book(xml)

def test_parse_missing_issue_date_with_empty_mark_says_unknown():
    xml = ("<RequestedBookInfo><bookInfo>"
           "<invType>1.1</invType><minMark></minMark>"
           "</bookInfo></RequestedBookInfo>")
    with pytest.raises(ValueError, match=r"issueDate.*\(άγνωστο\)"):
        parse_book(xml)

def test_parse_malformed_issue_date_names_the_mark():
    xml = ("<RequestedBookInfo><bookInfo>"
           "<issueDate>30/05/2025</issueDate>"
           "<minMark>900000000001028</minMark>"
           "</bookInfo></RequestedBookInfo>")
    with pytest.raises(ValueError, match="issueDate.*30/05/2025.*900000000001028"):
        parse_book(xml)

def test_parse_handles_page_breaks(fixtures_dir):
    text = (fixtures_dir / "mydata_expenses_2025.xml").read_text(encoding="utf-8")
    recs = parse_book(text)
    assert all(r.mark for r in recs)
    assert len(recs) == text.count("<bookInfo>")
