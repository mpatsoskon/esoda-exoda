# ABOUTME: Tests φόρτωσης config και resolve relative paths.
# ABOUTME: Καλύπτει load_config και Config.resolve.
from pathlib import Path
from esoda_exoda.config import Config, code_for_label, load_config

def test_load_config_resolves_relative_data_dir(tmp_path):
    (tmp_path / "config.toml").write_text(
        'data_dir = "."\n'
        '[type_labels]\n"1.1" = "1.1 Τιμολόγιο Πώλησης"\n'
        '[presets]\n',
        encoding="utf-8")
    cfg = load_config(tmp_path / "config.toml")
    assert cfg.data_dir == tmp_path
    assert cfg.resolve("out/x.xlsx") == tmp_path / "out" / "x.xlsx"
    assert cfg.type_labels["1.1"] == "1.1 Τιμολόγιο Πώλησης"

def test_real_config_keeps_the_14x_code_prefix_in_type_labels(monkeypatch):
    monkeypatch.delenv("ESODA_EXODA_CONFIG", raising=False)
    # Το vat.compute ξεχωρίζει τα σκέλη reverse charge με r.type.startswith("14.3"/"14.4"),
    # και το r.type είναι ακριβώς αυτό το label του config.toml. Αν το label γραφτεί
    # χωρίς το πρόθεμα του κωδικού, το ΦΠΑ λήπτη μηδενίζεται σιωπηλά ενώ η ισόποση
    # έκπτωση παραμένει, και το μηνιαίο υπόλοιπο ΦΠΑ βγαίνει λάθος χωρίς κανένα σφάλμα.
    cfg = load_config()
    assert cfg.type_labels["14.3"].startswith("14.3 ")
    assert cfg.type_labels["14.4"].startswith("14.4 ")

def test_code_for_label_finds_code(tmp_path):
    labels = {"category2_4": "2.4 Γενικά Έξοδα με δικαίωμα έκπτωσης ΦΠΑ"}
    assert code_for_label(labels, "2.4 Γενικά Έξοδα με δικαίωμα έκπτωσης ΦΠΑ") == "category2_4"

def test_code_for_label_none_when_absent():
    assert code_for_label({"category2_4": "κάτι"}, "άλλο") is None

def test_load_config_remembers_its_own_path(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('data_dir = "."\n', encoding="utf-8")
    assert load_config(p).source_path == p.resolve()

def test_config_διαβάζει_database_και_database_url(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[database]\nhost = "127.0.0.1"\nport = 5432\n'
                 'dbname = "esoda_exoda"\nuser = "esoda"\n', encoding="utf-8")
    cfg = load_config(p)
    assert cfg.database == {"host": "127.0.0.1", "port": 5432,
                            "dbname": "esoda_exoda", "user": "esoda"}
    assert cfg.database_url == ""

def test_config_φτιάχνεται_μόνο_με_database_url():
    cfg = Config(database_url="postgresql://a:b@h/d")
    assert cfg.data_dir == Path(".")

def _labels_cfg():
    return Config(e3_labels={"E3_561_001": "Πωλήσεις", "E3_585_016": "Λοιπά έξοδα", "E3_587": "Αποσβέσεις"},
                  category_labels={"category1_3": "1.3 Έσοδα", "category2_3": "2.3 Λήψη",
                                   "category2_8": "2.8 Αποσβέσεις"},
                  e3_income=["E3_561_001"])

def test_έξοδο_βλέπει_μόνο_κωδικούς_εξόδων():
    cfg = _labels_cfg()
    assert cfg.categories_for("expense") == {"category2_3": "2.3 Λήψη", "category2_8": "2.8 Αποσβέσεις"}
    assert cfg.e3_for("expense") == {"E3_585_016": "Λοιπά έξοδα", "E3_587": "Αποσβέσεις"}

def test_έσοδο_βλέπει_μόνο_κωδικούς_εσόδων():
    cfg = _labels_cfg()
    assert cfg.categories_for("income") == {"category1_3": "1.3 Έσοδα"}
    assert cfg.e3_for("income") == {"E3_561_001": "Πωλήσεις"}

def test_load_config_διαβάζει_τους_κωδικούς_ε3_εσόδων(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('e3_income = ["E3_561_001"]\n'
                 '[e3_labels]\n"E3_561_001" = "Πωλήσεις"\n"E3_587" = "Αποσβέσεις"\n', encoding="utf-8")
    assert load_config(p).e3_for("income") == {"E3_561_001": "Πωλήσεις"}

def test_real_config_e3_income_αναφέρει_μόνο_κωδικούς_του_e3_labels(monkeypatch):
    monkeypatch.delenv("ESODA_EXODA_CONFIG", raising=False)
    # Ένα typo στο e3_income αδειάζει σιωπηλά το dropdown εσόδων και ρίχνει τον
    # κωδικό εσόδου στο dropdown εξόδων.
    cfg = load_config()
    assert cfg.e3_income and set(cfg.e3_income) <= set(cfg.e3_labels)

def test_ESODA_EXODA_CONFIG_δείχνει_άλλο_αρχείο(tmp_path, monkeypatch):
    p = tmp_path / "other.toml"
    p.write_text('[database]\ndbname = "esoda_exoda_dev"\n', encoding="utf-8")
    monkeypatch.setenv("ESODA_EXODA_CONFIG", str(p))
    assert load_config().database["dbname"] == "esoda_exoda_dev"

def test_ρητό_path_υπερισχύει_του_ESODA_EXODA_CONFIG(tmp_path, monkeypatch):
    p = tmp_path / "a.toml"; p.write_text('[database]\ndbname = "a"\n', encoding="utf-8")
    monkeypatch.setenv("ESODA_EXODA_CONFIG", str(tmp_path / "missing.toml"))
    assert load_config(p).database["dbname"] == "a"
