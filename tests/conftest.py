# ABOUTME: Κοινά fixtures για τα tests (paths στα δεδομένα δοκιμών).
# ABOUTME: fixtures_dir δείχνει στον φάκελο tests/fixtures. netguard εμποδίζει δίκτυο.
import socket
from pathlib import Path
import urllib.request
import pytest

@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"

@pytest.fixture(autouse=True)
def καμία_κλήση_δικτύου(monkeypatch):
    """Το suite δεν επιτρέπεται να χτυπήσει το πραγματικό myDATA: κάθε τρέξιμο θα
    κατανάλωνε από το όριο κλήσεων, και μια υποβολή θα ήταν αμετάκλητη. Τρεις φορές σε
    αυτή τη φάση βρέθηκε test που ξέχασε τον monkeypatch — η παγίδα το κάνει μηχανικό.

    Κάθε fetch_*/send_* του mydata_client.py έχει προεπιλογή opener=urllib.request.
    urlopen, δεσμευμένη ΜΙΑ φορά στο import — το monkeypatch του urlopen από μόνο του
    ΔΕΝ θα έπιανε μια κλήση χωρίς ρητό opener (ό,τι κάνει το classify_routes), γιατί
    εκείνο το opener είναι ήδη το πραγματικό. Αυτό που πιάνει την κλήση είναι ότι η
    πραγματική urlopen() καλεί build_opener() στην ΠΡΩΤΗ κλήση, όσο το module-level
    urllib.request._opener είναι ακόμη None — γι' αυτό μένει το monkeypatch του
    build_opener. Μόλις μια πραγματική κλήση γεμίσει εκείνο το cache, κάθε επόμενη
    urlopen() το επαναχρησιμοποιεί και προσπερνά εντελώς το build_opener· επειδή όλο
    το suite τρέχει σε μία διεργασία, το socket.getaddrinfo είναι η γραμμή άμυνας που
    κρατά, γιατί η ανάλυση DNS γίνεται ανεξάρτητα από το ποιο opener χρησιμοποιείται.
    Επαληθεύτηκε end-to-end μέσω /classify με πραγματικά credentials χωρίς καμία
    κλήση να φύγει. Η βάση των tests είναι αρχείο SQLite, άρα κανένα host δεν εξαιρείται."""
    def σκάσε(*a, **k):
        raise AssertionError("ΔΙΚΤΥΟ: το test κάλεσε το πραγματικό urllib")
    monkeypatch.setattr(urllib.request, "urlopen", σκάσε)
    monkeypatch.setattr(urllib.request, "build_opener", σκάσε)
    monkeypatch.setattr(socket, "getaddrinfo", σκάσε)

@pytest.fixture
def db_cfg(tmp_path):
    """Προσωρινό αρχείο βάσης ανά test. Όχι :memory:, γιατί τα routes ανοίγουν δική τους
    σύνδεση μέσω db.connect(db_cfg) και πρέπει να βλέπουν τα ίδια δεδομένα."""
    from esoda_exoda.config import Config
    return Config(data_dir=tmp_path, database={"path": "test.sqlite3"},
                  type_labels={"1.1": "1.1 Τιμολόγιο Πώλησης", "2.1": "2.1 Τιμολόγιο Παροχής",
                               "13.3": "13.3 Κοινόχρηστες Δαπάνες", "14.3": "14.3 Τιμολόγιο / Ενδοκοινοτική Λήψη Υπηρεσιών",
                               "14.4": "14.4 Τιμολόγιο / Λήψη Υπηρεσιών Τρίτων Χωρών", "17.2": "17.2 Αποσβέσεις"},
                  e3_labels={"E3_561_001": "Πωλήσεις αγαθών και υπηρεσιών Χονδρικές - Επιτηδευματιών (E3_561_001)",
                             "E3_585_009": "Λοιπές Αμοιβές για υπηρεσίες ημεδαπής (E3_585_009)",
                             "E3_585_010": "Λοιπές αμοιβές για υπηρεσίες αλλοδαπής (E3_585_010)",
                             "E3_585_016": "Λοιπά έξοδα (E3_585_016)", "E3_587": "Αποσβέσεις (E3_587)"},
                  e3_income=["E3_561_001"],
                  category_labels={"category1_3": "1.3 Έσοδα από Παροχή Υπηρεσιών",
                                   "category2_3": "2.3 Λήψη Υπηρεσιών",
                                   "category2_4": "2.4 Γενικά Έξοδα με δικαίωμα έκπτωσης ΦΠΑ",
                                   "category2_5": "2.5 Γενικά Έξοδα χωρίς δικαίωμα έκπτωσης ΦΠΑ",
                                   "category2_8": "2.8 Αποσβέσεις"},
                  presets={"κοινόχρηστα": {"inv_type": "13.3", "vat_category": "8",
                                          "e3_type": "E3_585_016", "category": "category2_3"},
                           "αποσβέσεις": {"inv_type": "17.2", "vat_category": "8",
                                         "e3_type": "E3_587", "category": "category2_8"}})

@pytest.fixture
def db_conn_factory(db_cfg):
    """Νέα σύνδεση στο αρχείο του test κάθε φορά — για tests που θέλουν δύο συναλλαγές."""
    from esoda_exoda import db as db_mod
    return lambda: db_mod.open_db(db_cfg.db_path())

@pytest.fixture
def db(db_conn_factory):
    """Βάση με το σχήμα, σε καινούργιο αρχείο ανά test. Η σύνδεση είναι του test
    (seed/έλεγχοι)· τα routes ανοίγουν δική τους μέσω db.connect(db_cfg)."""
    from esoda_exoda import db as db_mod
    conn = db_conn_factory()
    db_mod.migrate(conn)
    yield conn
    conn.rollback()
    conn.close()

@pytest.fixture
def taxpayer(db):
    from esoda_exoda.taxpayers import create_taxpayer
    t = create_taxpayer(db, "123456783", environment="dev", postal_code="10000", city="ΑΛΦΑΠΟΛΗ")
    db.commit()
    return t
