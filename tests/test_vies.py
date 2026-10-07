# ABOUTME: Tests της αναζήτησης ΑΦΜ στο VIES: ανάγνωση απάντησης, URL κλήσης, σφάλματα,
# ABOUTME: και συμπλήρωση μόνο κενών πεδίων. Κανένα πραγματικό δίκτυο: ψεύτικος opener.
import io
import json
import urllib.error
import pytest
from esoda_exoda.vies import ViesError, ViesResult, fill_empty, lookup, parse

# Απάντηση του VIES στη μορφή που δίνει για ελληνικό εταιρικό ΑΦΜ.
GR_COMPANY = {"isValid": True, "userError": "VALID",
              "name": "ΠΡΟΜΗΘΕΥΤΗΣ Β ΑΝΩΝΥΜΗ ΕΤΑΙΡΕΙΑ||ΒΗΤΑ",
              "address": "ΟΔΟΣ Γ 3        10003 - ΓΑΜΜΑΠΟΛΗ",
              "vatNumber": "090000113"}
# Η Γερμανία επιβεβαιώνει μόνο την εγκυρότητα, χωρίς επωνυμία και διεύθυνση.
DE_VALID = {"isValid": True, "userError": "VALID", "name": "---", "address": "---",
            "vatNumber": "999999002"}

def test_parse_βάζει_τίτλο_πριν_την_επωνυμία_και_βγάζει_ΤΚ_και_πόλη():
    assert parse(GR_COMPANY) == ViesResult(
        True, "ΒΗΤΑ — ΠΡΟΜΗΘΕΥΤΗΣ Β ΑΝΩΝΥΜΗ ΕΤΑΙΡΕΙΑ",
        "10003", "ΓΑΜΜΑΠΟΛΗ")

def test_parse_χωρίς_τίτλο_κρατά_την_επωνυμία_και_συμπτύσσει_τα_κενά():
    r = parse({**GR_COMPANY, "name": "ΠΡΟΜΗΘΕΥΤΗΣ Γ   ΟΕ||", "address": "ΟΔΟΣ 1  10431 - ΔΕΛΤΑΠΟΛΗ"})
    assert (r.name, r.postal_code, r.city) == ("ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ", "10431", "ΔΕΛΤΑΠΟΛΗ")

def test_parse_χώρα_χωρίς_στοιχεία_δίνει_έγκυρο_χωρίς_όνομα():
    assert parse(DE_VALID) == ViesResult(True)

def test_parse_διεύθυνση_άλλης_μορφής_δεν_μαντεύει_ΤΚ():
    r = parse({**DE_VALID, "name": "FOREIGN SUPPLIER A B.V.", "address": "Teststraat 1\n1000AA Amsterdam"})
    assert (r.name, r.postal_code, r.city) == ("FOREIGN SUPPLIER A B.V.", "", "")

@pytest.mark.parametrize("user_error", ["INVALID", "INVALID_INPUT"])
def test_parse_μη_έγκυρος(user_error):
    assert parse({"isValid": False, "userError": user_error, "name": "---",
                  "address": "---"}) == ViesResult(False)

def test_parse_σφάλμα_υπηρεσίας():
    with pytest.raises(ViesError, match="MS_UNAVAILABLE"):
        parse({"isValid": False, "userError": "MS_UNAVAILABLE", "name": "---", "address": "---"})

def _opener(body, seen):
    def opener(req, timeout):
        seen.append((req.full_url, timeout))
        return io.BytesIO(json.dumps(body).encode())
    return opener

def test_lookup_ελληνικός_ΑΦΜ_πάει_ως_EL():
    seen = []
    assert lookup("GR", "090000113", _opener(GR_COMPANY, seen)).postal_code == "10003"
    assert seen == [("https://ec.europa.eu/taxation_customs/vies/rest-api/ms/EL/vat/090000113", 15)]

def test_lookup_αφαιρεί_το_πρόθεμα_χώρας_από_τον_αριθμό():
    seen = []
    lookup("NL", "NL999999003B01", _opener(DE_VALID, seen))
    assert seen[0][0].endswith("/ms/NL/vat/999999003B01")

def test_lookup_το_πρόθεμα_του_αριθμού_υπερισχύει_της_αποθηκευμένης_χώρας():
    # Γερμανικός ΑΦΜ αποθηκευμένος με χώρα GR.
    seen = []
    lookup("GR", "DE999999001", _opener(DE_VALID, seen))
    assert seen[0][0].endswith("/ms/DE/vat/999999001")

def test_lookup_χωρίς_δίκτυο_δίνει_ViesError():
    def opener(req, timeout):
        raise urllib.error.URLError("timed out")
    with pytest.raises(ViesError, match="VIES"):
        lookup("GR", "090000113", opener)

def test_fill_empty_συμπληρώνει_μόνο_τα_κενά():
    fields = {"name": "", "postal_code": "11111", "city": ""}
    assert fill_empty(fields, parse(GR_COMPANY)) == ["name", "city"]
    assert fields == {"name": "ΒΗΤΑ — ΠΡΟΜΗΘΕΥΤΗΣ Β ΑΝΩΝΥΜΗ ΕΤΑΙΡΕΙΑ",
                      "postal_code": "11111", "city": "ΓΑΜΜΑΠΟΛΗ"}
