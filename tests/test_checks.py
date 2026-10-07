# ABOUTME: Tests των ελέγχων πριν την αμετάκλητη υποβολή: διπλή διαβίβαση, ασυνήθιστο ποσό,
# ABOUTME: ύποπτη ημερομηνία, χαρακτηρισμός προμηθευτή 14.x, και οι κανόνες του χαρακτηρισμού.
from datetime import date
from esoda_exoda.checks import BLOCK, WARN, classification_findings, transmission_findings
from esoda_exoda.classify import Selection
from esoda_exoda.config import Config
from esoda_exoda.counterparties import ClassificationDefault, ForeignSupplier
from esoda_exoda.invoices import SelfDeclaredDoc

CFG = Config(e3_income=["E3_561_001"])
TODAY = date(2026, 9, 29)

def _sd(net, d, aa="1", inv_type="13.3", series="123456783", issuer_vat="", cancelled=False):
    return SelfDeclaredDoc(inv_type, series, aa, d, net, issuer_vat, cancelled)

def _t(history=(), *, inv_type="13.3", series="123456783", aa="9", issue_date=date(2026, 9, 1),
       net=12.0, supplier=None):
    return transmission_findings(CFG, inv_type=inv_type, series=series, aa=aa,
                                 issue_date=issue_date, net=net, history=list(history),
                                 today=TODAY, supplier=supplier)

def _levels(findings):
    return [f.level for f in findings]

def _supplier(e3="E3_585_010", category="category2_3", vat="NL999999003B01"):
    return ForeignSupplier("FOREIGN SUPPLIER A B.V.", vat, "NL", "1017", "Amsterdam", "14.3", e3, category)

# ── T1: διπλή διαβίβαση ────────────────────────────────────────────────────

def test_T1_ίδιο_ΑΑ_ίδιο_έτος_μπλοκάρει():
    [f] = _t([_sd(12.0, date(2026, 7, 1), aa="8000000010")], aa="8000000010",
             issue_date=date(2026, 7, 28))
    assert f.level == BLOCK and "8000000010" in f.message and "Ανανέωση" in f.message

def test_T1_ακυρωμένο_δεν_μπλοκάρει():
    assert _t([_sd(12.0, date(2026, 7, 1), aa="8000000010", cancelled=True)],
              aa="8000000010", issue_date=date(2026, 7, 28)) == []

def test_T1_ίδιο_ΑΑ_άλλο_έτος_δεν_μπλοκάρει():
    # Το 17.2 διαβιβάζεται κάθε χρόνο ως 0/1.
    assert _t([_sd(1250.40, date(2025, 12, 31), aa="1", inv_type="17.2", series="0")],
              inv_type="17.2", series="0", aa="1", net=1250.40) == []

def test_T1_άλλη_σειρά_δεν_μπλοκάρει():
    assert BLOCK not in _levels(_t([_sd(12.0, date(2026, 7, 1), aa="8000000010", series="0")],
                                   aa="8000000010", issue_date=date(2026, 7, 28)))

def test_T1_άλλος_τύπος_δεν_μπλοκάρει():
    assert _t([_sd(12.0, date(2026, 7, 1), aa="8000000010", inv_type="13.1")],
              aa="8000000010", issue_date=date(2026, 7, 28)) == []

# ── T2: ασυνήθιστο ποσό ────────────────────────────────────────────────────

_RANGE = [_sd(12.0, date(2026, 6, 1)), _sd(20.0, date(2026, 7, 1))]

def test_T2_ακριβώς_στο_άνω_όριο_δεν_προειδοποιεί():
    assert _t(_RANGE, net=30.0) == []

def test_T2_πάνω_από_το_άνω_όριο_προειδοποιεί_με_το_εύρος():
    [f] = _t(_RANGE, net=30.01)
    assert f.level == WARN and "30,01" in f.message and "12,00" in f.message and "20,00" in f.message

def test_T2_ακριβώς_στο_κάτω_όριο_δεν_προειδοποιεί():
    assert _t(_RANGE, net=6.0) == []

def test_T2_κάτω_από_το_κάτω_όριο_προειδοποιεί():
    assert _levels(_t(_RANGE, net=5.99)) == [WARN]

def test_T2_χωρίς_ιστορικό_δεν_προειδοποιεί():
    assert _t([], net=5000.0) == []

def test_T2_το_παράθυρο_είναι_365_ημέρες_πριν_την_ημερομηνία():
    assert _levels(_t([_sd(100.0, date(2025, 9, 1))], net=12.0)) == [WARN]
    assert _t([_sd(100.0, date(2025, 8, 31))], net=12.0) == []

def test_T2_ακυρωμένα_και_άλλος_τύπος_δεν_μετράνε():
    assert _t([_sd(100.0, date(2026, 6, 1), cancelled=True),
               _sd(1250.40, date(2026, 1, 1), inv_type="17.2", series="0")], net=12.0) == []

def test_T2_στα_14x_μετράει_μόνο_ο_ίδιος_προμηθευτής():
    history = [_sd(100.0, date(2026, 5, 1), inv_type="14.3", series="0", issuer_vat="IE9999004V"),
               _sd(10.0, date(2026, 6, 1), inv_type="14.3", series="0", issuer_vat="NL999999003B01")]
    assert _levels(_t(history, inv_type="14.3", series="0", net=100.0,
                      supplier=_supplier())) == [WARN]

# ── T5: πιθανό διπλότυπο με άλλο ΑΑ ────────────────────────────────────────

def test_T5_ίδιος_μήνας_και_ποσό_με_άλλο_ΑΑ_προειδοποιεί():
    [f] = _t([_sd(12.0, date(2026, 7, 1), aa="8000000010")], aa="8000000011",
             issue_date=date(2026, 7, 28))
    assert f.level == WARN and "01/07/2026" in f.message and "8000000010" in f.message
    assert "12,00" in f.message

def test_T5_ίδιο_ποσό_τον_επόμενο_μήνα_δεν_προειδοποιεί():
    assert _t([_sd(12.0, date(2026, 7, 1), aa="8000000010")], aa="8000000020",
              issue_date=date(2026, 8, 1)) == []

def test_T5_ίδιος_μήνας_άλλου_έτους_δεν_προειδοποιεί():
    assert _t([_sd(12.0, date(2025, 7, 30), aa="8000000010")], aa="8000000011",
              issue_date=date(2026, 7, 28)) == []

def test_T5_ποσό_που_διαφέρει_κατά_ένα_λεπτό_δεν_προειδοποιεί():
    assert _t([_sd(12.0, date(2026, 7, 1), aa="8000000010")], aa="8000000011",
              issue_date=date(2026, 7, 28), net=12.01) == []

def test_T5_συγκρίνει_στο_λεπτό():
    assert _levels(_t([_sd(12.0, date(2026, 7, 1), aa="8000000010")], aa="8000000011",
                      issue_date=date(2026, 7, 28), net=12.004)) == [WARN]

def test_T5_ακυρωμένο_και_άλλος_τύπος_δεν_μετράνε():
    assert _t([_sd(12.0, date(2026, 7, 1), aa="8000000010", cancelled=True),
               _sd(12.0, date(2026, 7, 2), aa="700000000001", inv_type="13.1")],
              aa="8000000011", issue_date=date(2026, 7, 28)) == []

def test_T5_στα_14x_με_αυτόματο_ΑΑ_ο_ίδιος_προμηθευτής_προειδοποιεί():
    history = [_sd(100.0, date(2026, 9, 2), aa="1", inv_type="14.3", series="0",
                   issuer_vat="NL999999003B01")]
    [f] = _t(history, inv_type="14.3", series="0", aa="2", issue_date=date(2026, 9, 2),
             net=100.0, supplier=_supplier())
    assert f.level == WARN and "02/09/2026" in f.message

def test_T5_στα_14x_άλλος_προμηθευτής_δεν_μετράει():
    history = [_sd(100.0, date(2026, 9, 2), aa="1", inv_type="14.3", series="0",
                   issuer_vat="IE9999004V")]
    assert _t(history, inv_type="14.3", series="0", aa="2", issue_date=date(2026, 9, 2),
              net=100.0, supplier=_supplier()) == []

# ── T3: ημερομηνία ─────────────────────────────────────────────────────────

def test_T3_μελλοντική_ημερομηνία_προειδοποιεί():
    [f] = _t(issue_date=date(2026, 9, 30))
    assert f.level == WARN and "30/09/2026" in f.message

def test_T3_σημερινή_ημερομηνία_δεν_προειδοποιεί():
    assert _t(issue_date=TODAY) == []

def test_T3_άλλο_έτος_προειδοποιεί():
    [f] = _t(issue_date=date(2025, 12, 31))
    assert f.level == WARN and "2026" in f.message

def test_T3_μελλοντική_σε_άλλο_έτος_δίνει_δύο_προειδοποιήσεις():
    assert _levels(_t(issue_date=date(2027, 1, 2))) == [WARN, WARN]

# ── T4: χαρακτηρισμός προμηθευτή 14.x ──────────────────────────────────────

def test_T4_κατηγορία_εσόδου_στον_προμηθευτή_μπλοκάρει():
    [f] = _t(inv_type="14.3", series="0", supplier=_supplier(category="category1_3"))
    assert f.level == BLOCK and "FOREIGN SUPPLIER A B.V." in f.message and "category1_3" in f.message

def test_T4_κωδικός_ε3_εσόδου_στον_προμηθευτή_μπλοκάρει():
    assert _levels(_t(inv_type="14.3", series="0",
                      supplier=_supplier(e3="E3_561_001"))) == [BLOCK]

def test_T4_ε3_ημεδαπής_σε_προμηθευτή_εξωτερικού_προειδοποιεί():
    [f] = _t(inv_type="14.3", series="0", supplier=_supplier(e3="E3_585_009"))
    assert f.level == WARN and "E3_585_009" in f.message

def test_T4_ε3_αλλοδαπής_σε_προμηθευτή_εξωτερικού_είναι_εντάξει():
    assert _t(inv_type="14.3", series="0", supplier=_supplier()) == []

# ── Χαρακτηρισμός εξόδων ───────────────────────────────────────────────────

GREEK = "990000155"

def _c(e3, category, issuer_vat=GREEK, default=None):
    return classification_findings(CFG, Selection("900000000001048", e3, category),
                                   issuer_vat, default)

def test_C1_κατηγορία_εσόδου_μπλοκάρει_με_το_MARK():
    [f] = _c("E3_585_016", "category1_3")
    assert f.level == BLOCK and f.mark == "900000000001048" and "900000000001048" in f.message

def test_C1_κωδικός_ε3_εσόδου_μπλοκάρει():
    assert _levels(_c("E3_561_001", "category2_3")) == [BLOCK]

def test_C2_ζεύγη_ε3_και_κατηγορίας():
    cases = [("E3_587", "category2_3", [WARN]), ("E3_585_016", "category2_8", [WARN]),
             ("E3_587", "category2_8", []),
             ("E3_883_001", "category2_4", [WARN]), ("E3_585_016", "category2_7", [WARN]),
             ("E3_883_001", "category2_7", []), ("E3_882_002", "category2_7", []),
             ("E3_585_016", "category2_4", [])]
    for e3, category, want in cases:
        assert _levels(_c(e3, category)) == want, (e3, category)

def test_C3_διαφορά_από_την_προεπιλογή_προειδοποιεί():
    d = ClassificationDefault("expense", "category2_4", "E3_585_016", True)
    [f] = _c("E3_585_009", "category2_4", default=d)
    assert f.level == WARN and "E3_585_016" in f.message and "category2_4" in f.message
    assert _c("E3_585_016", "category2_4", default=d) == []

def test_C3_χωρίς_προεπιλογή_δεν_προειδοποιεί():
    assert _c("E3_585_009", "category2_3", default=None) == []

def test_C4_αλλοδαπής_σε_ελληνικό_ΑΦΜ_προειδοποιεί():
    [f] = _c("E3_585_010", "category2_3")
    assert f.level == WARN and "E3_585_010" in f.message

def test_C4_αλλοδαπής_σε_ξένο_VAT_είναι_εντάξει():
    assert _c("E3_585_010", "category2_3", issuer_vat="NL999999003B01") == []

def test_C3_προεπιλογή_μόνο_με_κατηγορία_αγνοεί_τον_κωδικό():
    d = ClassificationDefault("expense", "category2_4", "", True)
    assert _c("E3_585_016", "category2_4", default=d) == []

def test_C3_προεπιλογή_μόνο_με_κωδικό_αγνοεί_την_κατηγορία():
    d = ClassificationDefault("expense", "", "E3_585_016", True)
    assert _c("E3_585_016", "category2_3", default=d) == []

def test_C3_προεπιλογή_μόνο_με_κατηγορία_προειδοποιεί_όταν_αυτή_διαφέρει():
    d = ClassificationDefault("expense", "category2_4", "", True)
    assert _levels(_c("E3_585_016", "category2_3", default=d)) == [WARN]
