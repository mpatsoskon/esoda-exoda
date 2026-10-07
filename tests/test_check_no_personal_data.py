# ABOUTME: Tests του ελέγχου προσωπικών δεδομένων: γενικοί κανόνες (xlsx, πραγματικά MARK)
# ABOUTME: και όροι από τοπική λίστα, ανεξαρτήτως πεζών/τόνων.
from scripts.check_no_personal_data import load_terms, scan


def test_καθαρό_tree():
    assert scan([("a.py", b"x = '900000000000001'\n")], []) == []


def test_xlsx_απαγορεύεται():
    assert scan([("data/β.xlsx", b"PK\x03\x04")], []) == ["data/β.xlsx: αρχείο xlsx"]


def test_πραγματικό_MARK():
    mark = "4" + "0" * 11 + "123"
    assert scan([("t.xml", f"<a/>\n<mark>{mark}</mark>\n".encode())], []) == ["t.xml:2: MARK"]


def test_όρος_ανεξαρτήτως_πεζών_και_τόνων():
    out = scan([("r.md", "Έδρα: Αλφάπολη\n".encode())], ["ΑΛΦΑΠΟΛΗ"])
    assert out == ["r.md:1: όρος από τη λίστα"]


def test_ο_όρος_δεν_τυπώνεται():
    out = scan([("r.md", b"user jdoe42\n")], ["jdoe42"])
    assert "jdoe42" not in out[0]


def test_δυαδικό_αρχείο_δεν_ρίχνει_το_script():
    assert scan([("f.woff2", bytes(range(256)))], ["abc"]) == []


def test_load_terms_αγνοεί_σχόλια_και_κενά(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("# σχόλιο\n\nΑΒΓ\n  δεδ  \n", encoding="utf-8")
    assert load_terms(p) == ["ΑΒΓ", "δεδ"]


def test_load_terms_χωρίς_αρχείο(tmp_path):
    assert load_terms(tmp_path / "λείπει.txt") == []
