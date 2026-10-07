# ABOUTME: Tests σύνδεσης, συναλλαγής και migrations του db.py πάνω σε πραγματικό
# ABOUTME: Postgres (ESODA_EXODA_TEST_DSN). Χωρίς DSN αποτυγχάνουν, δεν κάνουν skip.
import pytest
from esoda_exoda import db as db_mod
from esoda_exoda.config import Config

def test_migrate_εφαρμόζει_το_σχήμα_μία_φορά(db_conn_factory):
    # Αλφαβητικά προηγούνται test files (test_counterparties…) που έχουν ήδη εφαρμόσει το
    # σχήμα μέσω του _migrated· καθάρισέ το πρώτα, αλλιώς το πρώτο migrate βρίσκει τα πάντα
    # στη θέση τους και επιστρέφει [].
    with db_conn_factory() as conn:
        with conn.cursor() as cur:
            cur.execute("drop schema public cascade; create schema public")
        conn.commit()
        first = db_mod.migrate(conn)
    with db_conn_factory() as conn:
        second = db_mod.migrate(conn)
        n = conn.execute("select count(*) from schema_version").fetchone()[0]
    assert first == [1, 2] and second == [] and n == 2

def test_connect_κάνει_rollback_σε_εξαίρεση(db_cfg, db):
    with pytest.raises(RuntimeError):
        with db_mod.connect(db_cfg) as conn:
            conn.execute("insert into taxpayer (afm, environment) values ('1', 'dev')")
            raise RuntimeError("σκάσε")
    assert db.execute("select count(*) from taxpayer").fetchone()[0] == 0

def test_connect_κάνει_commit_στην_έξοδο(db_cfg, db):
    with db_mod.connect(db_cfg) as conn:
        conn.execute("insert into taxpayer (afm, environment) values ('1', 'dev')")
    assert db.execute("select count(*) from taxpayer").fetchone()[0] == 1

def test_απρόσιτη_βάση_γίνεται_DbUnavailable():
    cfg = Config(database_url="postgresql://x:y@127.0.0.1:1/nope?connect_timeout=1")
    with pytest.raises(db_mod.DbUnavailable) as e:
        with db_mod.connect(cfg):
            pass
    assert "docker compose up" in str(e.value)

def test_dsn_από_database_url_υπερισχύει():
    cfg = Config(database_url="postgresql://a:b@h/d", database={"host": "other"})
    assert db_mod.dsn(cfg) == "postgresql://a:b@h/d"

def test_dsn_από_database_και_keyring(monkeypatch):
    from esoda_exoda import credentials
    monkeypatch.setattr(credentials, "get_db_password", lambda: "s3cr3t")
    cfg = Config(database={"host": "127.0.0.1", "port": 5432, "dbname": "esoda_exoda",
                           "user": "esoda"})
    assert db_mod.dsn(cfg) == "postgresql://esoda:s3cr3t@127.0.0.1:5432/esoda_exoda"

def test_dsn_από_μέρη_κάνει_quote_σε_ειδικούς_χαρακτήρες():
    from psycopg.conninfo import conninfo_to_dict
    d = {"host": "127.0.0.1", "port": 5432, "dbname": "esoda_exoda", "user": "us:er"}
    parts = conninfo_to_dict(db_mod.dsn_from_parts(d, "p@s/s%1"))
    assert (parts["host"], parts["port"], parts["dbname"], parts["user"], parts["password"]) == (
        "127.0.0.1", "5432", "esoda_exoda", "us:er", "p@s/s%1")

def test_migration_002_δίνει_production_στον_υπάρχοντα_φορολογούμενο(db_conn_factory):
    """Η υπάρχουσα εγκατάσταση έφερε τα δεδομένα της από το παραγωγικό endpoint· η
    αναβάθμιση δεν πρέπει να ζητήσει τίποτα από τον χρήστη."""
    first_sql = (db_mod.MIGRATIONS_DIR / "001_schema.sql").read_text(encoding="utf-8")
    try:
        with db_conn_factory() as conn:
            conn.execute("drop schema public cascade; create schema public")
            conn.execute(first_sql)
            conn.execute("insert into schema_version (version) values (1)")
            conn.execute("insert into taxpayer (afm) values ('123456783')")
            conn.commit()
            assert db_mod.migrate(conn) == [2]
            env = conn.execute("select environment from taxpayer").fetchone()[0]
        assert env == "production"
    finally:
        # Επαναφορά του πλήρους σχήματος για τα επόμενα tests της συνεδρίας.
        with db_conn_factory() as conn:
            conn.execute("drop schema public cascade; create schema public")
            conn.commit()
            db_mod.migrate(conn)
