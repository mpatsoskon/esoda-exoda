# ABOUTME: Tests σύνδεσης, συναλλαγής, migrations, τύπων και ποσών του db.py, πάνω σε
# ABOUTME: προσωρινό αρχείο SQLite ανά test.
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from esoda_exoda import db as db_mod
from esoda_exoda.config import Config

def test_migrate_εφαρμόζει_το_σχήμα_μία_φορά(db_conn_factory):
    with db_conn_factory() as conn:
        first = db_mod.migrate(conn)
    conn = db_conn_factory()
    second = db_mod.migrate(conn)
    n = conn.execute("select count(*) from schema_version").fetchone()[0]
    conn.close()
    assert first == [1] and second == [] and n == 1

def test_migration_που_σκάει_δεν_αφήνει_τίποτα_μισό(db_conn_factory, tmp_path, monkeypatch):
    mig = tmp_path / "migrations"
    mig.mkdir()
    (mig / "001_schema.sql").write_text(
        "create table schema_version (version integer primary key);", encoding="utf-8")
    (mig / "002_bad.sql").write_text(
        "create table half (id integer);\ninsert into nope values (1);", encoding="utf-8")
    monkeypatch.setattr(db_mod, "MIGRATIONS_DIR", mig)
    conn = db_conn_factory()
    with pytest.raises(RuntimeError, match="002_bad.sql"):
        db_mod.migrate(conn)
    tables = {r[0] for r in conn.execute("select name from sqlite_master where type = 'table'")}
    versions = [r[0] for r in conn.execute("select version from schema_version")]
    conn.close()
    assert "half" not in tables and versions == [1]

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

def test_απρόσιτο_αρχείο_γίνεται_DbUnavailable(tmp_path):
    cfg = Config(data_dir=tmp_path, database={"path": "δεν-υπάρχει/βάση.sqlite3"})
    with pytest.raises(db_mod.DbUnavailable) as e:
        with db_mod.connect(cfg):
            pass
    assert "δεν-υπάρχει" in str(e.value) and "docker" not in str(e.value)

def test_foreign_keys_ενεργά_σε_κάθε_σύνδεση(db, taxpayer):
    assert db.execute("pragma foreign_keys").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("insert into counterparty (taxpayer_id, vat) values (999, '1')")

def test_on_delete_cascade_δουλεύει(db, taxpayer):
    cid = db.execute("insert into counterparty (taxpayer_id, vat) values (?, '090000113') "
                     "returning id", (taxpayer.id,)).fetchone()[0]
    db.execute("insert into classification_default (counterparty_id, direction, category_code, "
               "e3_code) values (?, 'expense', 'category2_4', 'E3_585_016')", (cid,))
    db.execute("delete from counterparty where id = ?", (cid,))
    assert db.execute("select count(*) from classification_default").fetchone()[0] == 0

def test_wal(db):
    assert db.execute("pragma journal_mode").fetchone()[0] == "wal"

def test_date_timestamptz_boolean_γυρίζουν_ως_python_τύποι(db, taxpayer):
    fid = db.execute(
        "insert into mydata_fetch (taxpayer_id, method, date_from, body) "
        "values (?, 'RequestMyExpenses', ?, '') returning id",
        (taxpayer.id, date(2026, 7, 1))).fetchone()[0]
    d, at = db.execute("select date_from, fetched_at from mydata_fetch where id = ?",
                       (fid,)).fetchone()
    assert d == date(2026, 7, 1)
    assert isinstance(at, datetime) and at.tzinfo is not None
    assert abs((at - datetime.now(timezone.utc)).total_seconds()) < 60
    db.execute("insert into counterparty (taxpayer_id, vat, separate_totals) "
               "values (?, '090000113', ?)", (taxpayer.id, True))
    db.execute("insert into counterparty (taxpayer_id, vat) values (?, '090000010')",
               (taxpayer.id,))
    flags = [r[0] for r in db.execute("select separate_totals from counterparty order by id")]
    assert flags == [True, False]

def test_nullable_boolean_μένει_None(db, taxpayer):
    cid = db.execute("insert into counterparty (taxpayer_id, vat) values (?, '090000113') "
                     "returning id", (taxpayer.id,)).fetchone()[0]
    db.execute("insert into classification_default (counterparty_id, direction, category_code, "
               "e3_code, deductible) values (?, 'expense', 'c', 'e', null)", (cid,))
    assert db.execute("select deductible from classification_default").fetchone()[0] is None

def test_timestamptz_με_ζώνη_αποθηκεύεται_σε_UTC(db, taxpayer):
    from datetime import timedelta
    athens = timezone(timedelta(hours=3))
    db.execute("insert into invoice_submission (taxpayer_id, mark, at) values (?, '9', ?)",
               (taxpayer.id, datetime(2026, 7, 3, 12, 0, tzinfo=athens)))
    raw = db.execute("select cast(at as text) from invoice_submission").fetchone()[0]
    at = db.execute("select at from invoice_submission").fetchone()[0]
    assert raw == "2026-07-03T09:00:00.000Z"
    assert at == datetime(2026, 7, 3, 9, 0, tzinfo=timezone.utc)

def test_timestamptz_χωρίς_ζώνη_απορρίπτεται(db, taxpayer):
    with pytest.raises((ValueError, sqlite3.ProgrammingError)):
        db.execute("insert into invoice_submission (taxpayer_id, mark, at) values (?, '9', ?)",
                   (taxpayer.id, datetime(2026, 7, 3, 12, 0)))

def test_η_βάση_αρνείται_άγνωστο_περιβάλλον_και_κενό(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("insert into taxpayer (afm, environment) values ('1', 'prod')")
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("insert into taxpayer (afm) values ('1')")

# --- Ποσά σε ακέραια λεπτά ------------------------------------------------------------

@pytest.mark.parametrize("amount, cents", [
    (0, 0), (12.34, 1234), (0.1 + 0.2, 30), (1250.40, 125040), (-3.5, -350),
    (1.005, 101), (-1.005, -101), (0.004, 0), (Decimal("99999999.99"), 9999999999),
    ("7.10", 710), (100, 10000)])
def test_to_cents(amount, cents):
    got = db_mod.to_cents(amount)
    assert got == cents and type(got) is int

def test_to_cents_και_from_cents_None():
    assert db_mod.to_cents(None) is None and db_mod.from_cents(None) is None

@pytest.mark.parametrize("cents, amount", [(0, 0.0), (1234, 12.34), (-350, -3.5), (125040, 1250.4)])
def test_from_cents(cents, amount):
    got = db_mod.from_cents(cents)
    assert got == amount and type(got) is float

def test_στρογγυλά_ποσά_επιβιώνουν_το_ταξίδι():
    for c in range(-1000, 100001, 7):
        assert db_mod.to_cents(db_mod.from_cents(c)) == c

def test_οι_στήλες_ποσών_είναι_ακέραιες(db):
    amounts = {("invoice", c) for c in ("net", "vat", "withheld", "gross", "other_taxes",
                                         "stamp_duty", "fees")}
    amounts |= {("invoice_line", "net"), ("invoice_line", "vat_amount"),
                ("classification_line", "value"), ("vat_code_line", "value"),
                ("invoice_submission", "net"), ("classification_submission", "amount")}
    for table, col in amounts:
        types = {r[1]: r[2] for r in db.execute(f"pragma table_info({table})")}
        assert types[col] == "INTEGER", (table, col)
    real = [(t, r[1]) for (t,) in db.execute("select name from sqlite_master where type = 'table'")
            for r in db.execute(f"pragma table_info({t})") if r[2] in ("REAL", "NUMERIC", "FLOAT")]
    assert real == []

def test_άθροισμα_στη_βάση_είναι_ακριβές(db, taxpayer):
    # 0,10 € δέκα χιλιάδες φορές: σε REAL το sum() βγαίνει 999.9999999999...
    fid = db.execute("insert into mydata_fetch (taxpayer_id, method, body) values (?, 'x', '') "
                     "returning id", (taxpayer.id,)).fetchone()[0]
    sid = db.execute("insert into classification_snapshot (taxpayer_id, mark, source, fetch_id) "
                     "values (?, '9', 'vat_info', ?) returning id", (taxpayer.id, fid)).fetchone()[0]
    db.executemany("insert into vat_code_line (snapshot_id, code, value) values (?, 'Vat333', ?)",
                   [(sid, db_mod.to_cents(0.1))] * 10000)
    total = db.execute("select sum(value) from vat_code_line").fetchone()[0]
    assert total == 100000 and db_mod.from_cents(total) == 1000.0
    assert sum([0.1] * 10000) != 1000.0  # η παγίδα που αποφεύγουμε
