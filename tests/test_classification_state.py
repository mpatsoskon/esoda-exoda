from datetime import date
from pathlib import Path
import pytest
from esoda_exoda.classification_state import (
    E3Line, VatCodes, PAGE_BREAK, expense_lines, parse_e3_info, parse_vat_info)

FIXTURES = Path(__file__).parent / "fixtures"

def _e3_xml() -> str:
    return (FIXTURES / "mydata_e3_info_2026_07.xml").read_text(encoding="utf-8")

def _vat_xml() -> str:
    return (FIXTURES / "mydata_vat_info_2026_07.xml").read_text(encoding="utf-8")

def test_parse_e3_info_κρατά_και_τα_έσοδα():
    by_mark = parse_e3_info(_e3_xml())
    assert len(by_mark) == 8
    assert by_mark["900000000001045"] == [
        E3Line(mark="900000000001045", date=date(2026, 7, 10),
               category="category1_3", e3_type="E3_561_001", value=500.0)]

def test_parse_e3_info_διαβάζει_ημερομηνία_με_ώρα():
    # Το IssueDate έρχεται «2026-07-08T00:00:00» — το date.fromisoformat σκάει.
    assert parse_e3_info(_e3_xml())["900000000001044"][0].date == date(2026, 7, 8)

def test_expense_lines_κρατά_μόνο_τα_category2():
    marks = set(expense_lines(parse_e3_info(_e3_xml())))
    assert marks == {"900000000001052", "900000000001044", "900000000001047",
                     "900000000001048", "900000000001049", "900000000001050"}

def test_expense_lines_δίνει_τα_καύσιμα_ως_category2_5():
    fuel = expense_lines(parse_e3_info(_e3_xml()))["900000000001044"][0]
    assert (fuel.category, fuel.e3_type, fuel.value) == ("category2_5", "E3_585_016", 30.0)

def test_expense_lines_αφαιρεί_τη_γραμμή_εσόδου_από_μεικτό_mark():
    # Μεικτό MARK με έσοδο πρώτο και έξοδο δεύτερο: η λίστα που επιστρέφει πρέπει να
    # έχει μόνο την γραμμή εξόδου, όχι και τις δύο — αλλιώς ο πρώτος της λίστας
    # μπορεί να είναι το έσοδο.
    by_mark = {"MX": [
        E3Line(mark="MX", date=date(2026, 7, 10), category="category1_3",
               e3_type="E3_561_001", value=100.0),
        E3Line(mark="MX", date=date(2026, 7, 10), category="category2_5",
               e3_type="E3_585_016", value=50.0)]}
    assert expense_lines(by_mark)["MX"] == [
        E3Line(mark="MX", date=date(2026, 7, 10), category="category2_5",
               e3_type="E3_585_016", value=50.0)]

def test_παραστατικό_με_δύο_κωδικούς_Ε3_δίνει_δύο_γραμμές():
    xml = """<?xml version="1.0" encoding="utf-8"?>
<RequestedE3Info xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
  <E3Info><V_Afm>123456783</V_Afm><V_Mark>1</V_Mark>
    <IssueDate>2026-07-01T00:00:00</IssueDate>
    <V_Class_Category>category2_3</V_Class_Category>
    <V_Class_Type>E3_585_016</V_Class_Type><V_Class_Value>10</V_Class_Value></E3Info>
  <E3Info><V_Afm>123456783</V_Afm><V_Mark>1</V_Mark>
    <IssueDate>2026-07-01T00:00:00</IssueDate>
    <V_Class_Category>category2_4</V_Class_Category>
    <V_Class_Type>E3_585_004</V_Class_Type><V_Class_Value>5</V_Class_Value></E3Info>
</RequestedE3Info>"""
    lines = parse_e3_info(xml)["1"]
    assert [(l.e3_type, l.value) for l in lines] == [("E3_585_016", 10.0), ("E3_585_004", 5.0)]

def test_parse_vat_info_πετά_τα_ακυρωμένα():
    by_mark = parse_vat_info(_vat_xml())
    assert "900000000001051" not in by_mark
    assert len(by_mark) == 8

def test_parse_vat_info_κρατά_τα_αχαρακτήριστα_με_κενούς_κωδικούς():
    # Απουσία πεδίων Vat* δεν σημαίνει «δεν υπάρχει γραμμή» — σημαίνει «δεν συμμετέχει».
    assert parse_vat_info(_vat_xml())["900000000001044"] == VatCodes(
        mark="900000000001044", date=date(2026, 7, 8), codes={})

def test_parse_vat_info_κρατά_όλους_τους_κωδικούς():
    assert parse_vat_info(_vat_xml())["900000000001048"].codes == {
        "Vat303": 75.0, "Vat333": 18.0, "Vat366": 75.0, "Vat386": 18.0}

def test_parse_vat_info_κρατά_κωδικό_εκτός_του_γνωστού_τετράδου():
    # 331/381 = ο κλιμακωτός 13%. Ένα σταθερό σχήμα τεσσάρων πεδίων θα τους έτρωγε.
    xml = """<?xml version="1.0" encoding="utf-8"?>
<RequestedVatInfo xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
  <VatInfo><Mark>9</Mark><IssueDate>2026-07-01T00:00:00</IssueDate>
    <Vat301>100</Vat301><Vat331>13</Vat331></VatInfo>
</RequestedVatInfo>"""
    assert parse_vat_info(xml)["9"].codes == {"Vat301": 100.0, "Vat331": 13.0}

def test_και_τα_δύο_parse_δέχονται_σελιδοποίηση():
    page = """<?xml version="1.0" encoding="utf-8"?>
<RequestedVatInfo xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
  <VatInfo><Mark>{m}</Mark><IssueDate>2026-07-01T00:00:00</IssueDate></VatInfo>
</RequestedVatInfo>"""
    joined = f"\n{PAGE_BREAK}\n".join((page.format(m="1"), page.format(m="2")))
    assert set(parse_vat_info(joined)) == {"1", "2"}

def test_κενό_XML_δίνει_κενά_dicts():
    empty = ('<?xml version="1.0" encoding="utf-8"?>'
             '<RequestedE3Info xmlns="http://www.aade.gr/myDATA/invoice/v1.0" />')
    assert parse_e3_info(empty) == {}

def test_μη_αριθμητικό_ποσό_λέει_ποιο_MARK():
    xml = """<?xml version="1.0" encoding="utf-8"?>
<RequestedE3Info xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
  <E3Info><V_Afm>1</V_Afm><V_Mark>77</V_Mark>
    <IssueDate>2026-07-01T00:00:00</IssueDate>
    <V_Class_Category>category2_3</V_Class_Category>
    <V_Class_Type>E3_585_016</V_Class_Type><V_Class_Value>abc</V_Class_Value></E3Info>
</RequestedE3Info>"""
    with pytest.raises(ValueError, match="77"):
        parse_e3_info(xml)

def test_official_by_month_αθροίζει_ανά_μήνα_και_κωδικό():
    from esoda_exoda.classification_state import official_by_month
    by_mark = {
        "A": VatCodes(mark="A", date=date(2026, 7, 8), codes={}),
        "B": VatCodes(mark="B", date=date(2026, 7, 10),
                      codes={"Vat303": 500.0, "Vat333": 120.0}),
        "C": VatCodes(mark="C", date=date(2026, 7, 22),
                      codes={"Vat303": 40.0, "Vat333": 9.6,
                             "Vat366": 40.0, "Vat386": 9.6}),
        "D": VatCodes(mark="D", date=date(2026, 8, 1),
                      codes={"Vat333": 10.0})}
    got = official_by_month(by_mark)
    assert got[7] == {"Vat303": 540.0, "Vat333": 129.6, "Vat366": 40.0, "Vat386": 9.6}
    assert got[8] == {"Vat333": 10.0}

def test_official_by_month_από_το_πραγματικό_fixture():
    # Τα επίσημα σύνολα Ιουλίου 2026, αυτούσια από την ΑΑΔΕ.
    from esoda_exoda.classification_state import official_by_month
    got = official_by_month(parse_vat_info(_vat_xml()))[7]
    assert got == {"Vat303": 1365.0, "Vat333": 327.6,
                   "Vat366": 115.0, "Vat386": 27.6}
