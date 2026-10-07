# ABOUTME: Tests του `esoda-exoda setup` με προσομοιωμένη είσοδο και keyring σε mock·
# ABOUTME: η βάση είναι η βάση των tests (database_url), άρα δεν ζητείται κωδικός βάσης.
import dataclasses
from urllib.parse import urlparse
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

@pytest.fixture
def pw_cfg(db_cfg, test_dsn):
    """Config χωρίς database_url: η σύνδεση χτίζεται από [database] και τον κωδικό που πληκτρολογείται."""
    u = urlparse(test_dsn)
    cfg = dataclasses.replace(db_cfg, database_url="", database={
        "host": u.hostname, "port": u.port, "dbname": u.path.lstrip("/"), "user": u.username})
    return cfg, u.password

def test_κωδικός_βάσης_γράφεται_μόνο_στο_τέλος(db, pw_cfg, keys):
    cfg, pw = pw_cfg
    code, _ = _run(cfg, [pw, "123456783", "", "", "", "dev", "u", "k"])
    assert code == 0
    assert keys[("esoda-exoda-db", "password")] == pw

def test_κωδικός_βάσης_δεν_γράφεται_όταν_υπάρχει_φορολογούμενος(db, pw_cfg, keys):
    create_taxpayer(db, "090000010", environment="dev"); db.commit()
    cfg, pw = pw_cfg
    code, _ = _run(cfg, [pw, "123456783"])
    assert code == 1 and keys == {}

def test_κωδικός_βάσης_δεν_γράφεται_σε_διακοπή(db, pw_cfg, keys):
    cfg, pw = pw_cfg
    code, _ = _run(cfg, [pw, "123456783", KeyboardInterrupt()])
    assert code == 1 and keys == {}

def test_EOF_στη_μέση_δεν_γράφει_τίποτα(db, pw_cfg, keys):
    cfg, pw = pw_cfg
    code, c = _run(cfg, [pw, "123456783", "", ""])
    assert code == 1 and keys == {}
    assert db.execute("select count(*) from taxpayer").fetchone()[0] == 0
    assert any("Ακυρώθηκε" in line for line in c.out)

def test_λάθος_κωδικός_βάσης_δεν_γράφει_τίποτα(db, pw_cfg, keys):
    cfg, pw = pw_cfg
    code, c = _run(cfg, [pw + "x"])
    assert code == 1 and keys == {}
    assert any("δεν άλλαξε τίποτα" in line for line in c.out)

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

def test_keys_με_κωδικό_βάσης_τον_γράφει_στο_τέλος(db, pw_cfg, keys):
    create_taxpayer(db, "123456783", environment="dev"); db.commit()
    cfg, pw = pw_cfg
    code, _ = _run_keys(cfg, [pw, "u", "k"])
    assert code == 0 and keys[("esoda-exoda-db", "password")] == pw
    assert keys[("esoda-exoda-mydata-dev", "user-id")] == "u"

def test_keys_χωρίς_φορολογούμενο_δεν_γράφει_τίποτα(db, db_cfg, keys):
    code, c = _run_keys(db_cfg, ["u", "k"])
    assert code == 1 and keys == {}
    assert any("esoda-exoda setup" in line for line in c.out)

def test_keys_διακοπή_δεν_γράφει_τίποτα(db, pw_cfg, keys):
    create_taxpayer(db, "123456783", environment="dev"); db.commit()
    cfg, pw = pw_cfg
    code, c = _run_keys(cfg, [pw, "u", KeyboardInterrupt()])
    assert code == 1 and keys == {}
    assert any("Ακυρώθηκε" in line for line in c.out)

def test_keys_λάθος_κωδικός_βάσης_δεν_γράφει_τίποτα(db, pw_cfg, keys):
    cfg, pw = pw_cfg
    code, c = _run_keys(cfg, [pw + "x"])
    assert code == 1 and keys == {}
    assert any("δεν άλλαξε τίποτα" in line for line in c.out)

def test_main_keys_καλεί_run_keys(monkeypatch):
    called = []
    monkeypatch.setattr(cli, "run_keys", lambda *a: called.append(True) or 0)
    assert cli.main(["keys"]) == 0 and called == [True]
