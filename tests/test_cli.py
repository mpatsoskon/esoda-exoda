# ABOUTME: Tests του `esoda-exoda setup`/`keys` με προσομοιωμένη είσοδο και keyring σε mock·
# ABOUTME: η βάση είναι προσωρινό αρχείο SQLite. Και το `backup`.
import sqlite3
import pytest
from esoda_exoda import cli, credentials
from esoda_exoda.taxpayers import create_taxpayer

class Console:
    def __init__(self, answers):
        self.answers = list(answers); self.out = []
    def ask(self, prompt):
        self.out.append(prompt)
        if not self.answers:
            raise EOFError
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a
    def say(self, text):
        self.out.append(text)

@pytest.fixture
def keys(monkeypatch):
    stored = {}
    monkeypatch.setattr(credentials.keyring, "set_password",
                        lambda svc, name, val: stored.__setitem__((svc, name), val))
    return stored

def _run(db_cfg, answers):
    c = Console(answers)
    return cli.run_setup(db_cfg, c.ask, c.ask, c.say), c

def test_setup_dev(db, db_cfg, keys):
    code, c = _run(db_cfg, ["123456783", "ΔΟΚΙΜΗ ΑΕ", "10000", "ΔΕΛΤΑΠΟΛΗ", "dev", "uid", "key"])
    assert code == 0
    row = db.execute("select afm, name, postal_code, city, environment from taxpayer").fetchall()
    assert row == [("123456783", "ΔΟΚΙΜΗ ΑΕ", "10000", "ΔΕΛΤΑΠΟΛΗ", "dev")]
    assert keys == {("esoda-exoda-mydata-dev", "user-id"): "uid",
                    ("esoda-exoda-mydata-dev", "subscription-key"): "key"}

def test_setup_production_με_επιβεβαίωση(db, db_cfg, keys):
    code, _ = _run(db_cfg, ["123456783", "", "", "", "production", "123456783", "uid", "key"])
    assert code == 0
    assert db.execute("select environment from taxpayer").fetchone()[0] == "production"
    assert ("esoda-exoda-mydata", "user-id") in keys

def test_λάθος_επιβεβαίωση_production_δεν_γράφει_τίποτα(db, db_cfg, keys):
    code, c = _run(db_cfg, ["123456783", "", "", "", "production", "090000010"])
    assert code == 1 and keys == {}
    assert db.execute("select count(*) from taxpayer").fetchone()[0] == 0

def test_άκυρος_ΑΦΜ_ξαναρωτά(db, db_cfg, keys):
    code, c = _run(db_cfg, ["123456789", "123456783", "", "", "", "dev", "u", "k"])
    assert code == 0 and any("ψηφίο ελέγχου" in line for line in c.out)

def test_άκυρο_περιβάλλον_ξαναρωτά(db, db_cfg, keys):
    code, _ = _run(db_cfg, ["123456783", "", "", "", "prod", "dev", "u", "k"])
    assert code == 0

def test_υπάρχων_φορολογούμενος_άρνηση_χωρίς_εγγραφή(db, db_cfg, keys):
    create_taxpayer(db, "090000010", environment="dev"); db.commit()
    code, c = _run(db_cfg, ["123456783", "", "", "", "dev", "u", "k"])
    assert code == 1 and keys == {}
    assert db.execute("select afm from taxpayer").fetchall() == [("090000010",)]

def test_διακοπή_στη_μέση_δεν_γράφει_τίποτα(db, db_cfg, keys):
    code, c = _run(db_cfg, ["123456783", "", "", "", KeyboardInterrupt()])
    assert code == 1 and keys == {}
    assert db.execute("select count(*) from taxpayer").fetchone()[0] == 0
    assert any("Ακυρώθηκε" in line for line in c.out)

def test_κενό_user_id_ή_κλειδί_ξαναρωτά(db, db_cfg, keys):
    code, c = _run(db_cfg, ["123456783", "", "", "", "dev", "", "uid", "", "key"])
    assert code == 0
    assert keys == {("esoda-exoda-mydata-dev", "user-id"): "uid",
                    ("esoda-exoda-mydata-dev", "subscription-key"): "key"}
    assert any("δεν μπορεί να είναι κενό" in line for line in c.out)

def test_main_χωρίς_όρισμα_σηκώνει_server(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "_serve", lambda: called.append(True))
    assert cli.main([]) == 0 and called == [True]

def test_main_άγνωστη_εντολή(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["foo"])
    assert e.value.code == 2

def test_setup_δεν_ζητά_κωδικό_βάσης(db, db_cfg, keys):
    code, c = _run(db_cfg, ["123456783", "", "", "", "dev", "u", "k"])
    assert code == 0 and c.out[0] == "ΑΦΜ: "
    assert not any("κωδικός βάσης" in line.lower() for line in c.out)
    assert {svc for svc, _ in keys} == {"esoda-exoda-mydata-dev"}

def test_setup_φτιάχνει_το_αρχείο_της_βάσης(db_cfg, keys):
    assert not db_cfg.db_path().exists()
    code, _ = _run(db_cfg, ["123456783", "", "", "", "dev", "u", "k"])
    assert code == 0 and db_cfg.db_path().is_file()

def test_setup_χωρίς_φάκελο_βάσης_δεν_γράφει_τίποτα(tmp_path, keys):
    from esoda_exoda.config import Config
    cfg = Config(data_dir=tmp_path, database={"path": "λείπει/βάση.sqlite3"})
    code, c = _run(cfg, ["123456783"])
    assert code == 1 and keys == {}
    assert any("δεν άλλαξε τίποτα" in line for line in c.out)

def test_EOF_στη_μέση_δεν_γράφει_τίποτα(db, db_cfg, keys):
    code, c = _run(db_cfg, ["123456783", "", ""])
    assert code == 1 and keys == {}
    assert db.execute("select count(*) from taxpayer").fetchone()[0] == 0
    assert any("Ακυρώθηκε" in line for line in c.out)

def _run_keys(cfg, answers):
    c = Console(answers)
    return cli.run_keys(cfg, c.ask, c.ask, c.say), c

def test_keys_dev_γράφει_στο_service_του_dev(db, db_cfg, keys):
    create_taxpayer(db, "123456783", environment="dev", name="Χ"); db.commit()
    before = db.execute("select * from taxpayer").fetchall()
    code, c = _run_keys(db_cfg, ["uid2", "key2"])
    assert code == 0
    assert keys == {("esoda-exoda-mydata-dev", "user-id"): "uid2",
                    ("esoda-exoda-mydata-dev", "subscription-key"): "key2"}
    assert db.execute("select * from taxpayer").fetchall() == before
    assert any("dev" in line and "123456783" in line for line in c.out)

def test_keys_κενό_ξαναρωτά(db, db_cfg, keys):
    create_taxpayer(db, "123456783", environment="dev"); db.commit()
    code, _ = _run_keys(db_cfg, ["", "u", "", "k"])
    assert code == 0 and keys[("esoda-exoda-mydata-dev", "user-id")] == "u"
    assert keys[("esoda-exoda-mydata-dev", "subscription-key")] == "k"

def test_keys_ζητά_μόνο_κλειδιά_myDATA(db, db_cfg, keys):
    create_taxpayer(db, "123456783", environment="dev"); db.commit()
    code, c = _run_keys(db_cfg, ["u", "k"])
    assert code == 0 and {svc for svc, _ in keys} == {"esoda-exoda-mydata-dev"}
    assert not any("κωδικός βάσης" in line.lower() for line in c.out)

def test_keys_χωρίς_φορολογούμενο_δεν_γράφει_τίποτα(db, db_cfg, keys):
    code, c = _run_keys(db_cfg, ["u", "k"])
    assert code == 1 and keys == {}
    assert any("esoda-exoda setup" in line for line in c.out)

def test_keys_διακοπή_δεν_γράφει_τίποτα(db, db_cfg, keys):
    create_taxpayer(db, "123456783", environment="dev"); db.commit()
    code, c = _run_keys(db_cfg, ["u", KeyboardInterrupt()])
    assert code == 1 and keys == {}
    assert any("Ακυρώθηκε" in line for line in c.out)

def test_main_keys_καλεί_run_keys(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "run_keys", lambda *a: called.append(True) or 0)
    assert cli.main(["keys"]) == 0 and called == [True]

def test_backup_αντιγράφει_τη_βάση(db, db_cfg, tmp_path):
    create_taxpayer(db, "123456783", environment="dev"); db.commit()
    target = tmp_path / "αντίγραφα" / "backup.sqlite3"
    target.parent.mkdir()
    c = Console([])
    assert cli.run_backup(db_cfg, str(target), c.say) == 0
    copy = sqlite3.connect(target)
    assert copy.execute("select afm from taxpayer").fetchall() == [("123456783",)]
    copy.close()
    assert any(str(target) in line for line in c.out)

def test_backup_περιλαμβάνει_ό_τι_είναι_ακόμη_στο_WAL(db, db_cfg, tmp_path):
    # Η απλή αντιγραφή του αρχείου εδώ θα έχανε τη γραμμή: ζει μόνο στο -wal.
    create_taxpayer(db, "123456783", environment="dev"); db.commit()
    target = tmp_path / "b.sqlite3"
    assert cli.run_backup(db_cfg, str(target), Console([]).say) == 0
    copy = sqlite3.connect(target)
    assert copy.execute("select count(*) from taxpayer").fetchone()[0] == 1
    copy.close()

def test_backup_δεν_γράφει_πάνω_σε_υπάρχον_αρχείο(db, db_cfg, tmp_path):
    target = tmp_path / "υπάρχει.sqlite3"
    target.write_bytes(b"x")
    c = Console([])
    assert cli.run_backup(db_cfg, str(target), c.say) == 1
    assert target.read_bytes() == b"x" and any("υπάρχει ήδη" in line for line in c.out)

def test_backup_χωρίς_βάση_δεν_φτιάχνει_άδεια(db_cfg, tmp_path):
    c = Console([])
    assert cli.run_backup(db_cfg, str(tmp_path / "b.sqlite3"), c.say) == 1
    assert not db_cfg.db_path().exists() and not (tmp_path / "b.sqlite3").exists()

def test_main_backup_καλεί_run_backup(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "load_config", lambda: "cfg")
    monkeypatch.setattr(cli, "run_backup", lambda cfg, target, say: called.append((cfg, target)) or 0)
    assert cli.main(["backup", "x.sqlite3"]) == 0 and called == [("cfg", "x.sqlite3")]

def test_main_backup_χωρίς_αρχείο(capsys):
    with pytest.raises(SystemExit) as e:
        cli.main(["backup"])
    assert e.value.code == 2

def test_αποτυχημένο_backup_δεν_αφήνει_μισό_αρχείο(db, db_cfg, tmp_path, monkeypatch):
    from esoda_exoda import db as db_mod
    class Πηγή:
        def backup(self, dst):
            dst.execute("create table μισό (x)")
            dst.commit()
            raise sqlite3.OperationalError("database or disk is full")
        def close(self):
            pass
    monkeypatch.setattr(db_mod, "open_db", lambda path: Πηγή())
    target = tmp_path / "b.sqlite3"
    c = Console([])
    assert cli.run_backup(db_cfg, str(target), c.say) == 1
    assert not target.exists() and any("disk is full" in line for line in c.out)
