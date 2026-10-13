# ABOUTME: Tests του scripts/migrate_from_postgres.py με ψεύτικη πηγή στη θέση της Postgres:
# ABOUTME: έλεγχος schema_version, αντιγραφή με ίδια id, ποσά σε λεπτά, σύγκριση πληθών/αθροισμάτων.
import json
import sqlite3
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest
from esoda_exoda.config import Config
from esoda_exoda.invoices import invoices_in_range
from esoda_exoda.submissions import list_classification_submissions, list_invoice_submissions
from scripts import migrate_from_postgres as mig

AT = datetime(2026, 7, 3, 9, 30, tzinfo=timezone.utc)

def _data():
    """Μια μικρή, συνθετική βάση σχήματος 2, όπως τη δίνει ο psycopg (Decimal, aware
    datetime, bool, jsonb ως list)."""
    return {
        "taxpayer": [dict(id=1, afm="123456783", name="ΔΟΚΙΜΗ", postal_code="10000",
                          city="ΑΛΦΑΠΟΛΗ", environment="production")],
        "counterparty": [dict(id=4, taxpayer_id=1, vat="090000113", country="GR", name="Π ΟΕ",
                              postal_code="", city="", notes="", separate_totals=True,
                              created_at=AT, updated_at=AT)],
        "classification_default": [dict(id=2, counterparty_id=4, direction="expense",
                                        category_code="category2_4", e3_code="E3_585_016",
                                        deductible=None, inv_type="")],
        "mydata_fetch": [dict(id=7, taxpayer_id=1, method="RequestMyExpenses",
                              date_from=date(2026, 7, 1), date_to=date(2026, 7, 31),
                              fetched_at=AT, body="<x/>"),
                         dict(id=9, taxpayer_id=1, method="RequestE3Info",
                              date_from=date(2026, 7, 1), date_to=date(2026, 7, 31),
                              fetched_at=AT, body="<y/>")],
        "invoice": [dict(id=3, taxpayer_id=1, mark="900000000000003", direction="expense",
                         inv_type="1.1", issue_date=date(2026, 7, 3), series="Α", aa="1",
                         issuer_vat="090000113", issuer_name="Π ΟΕ", counterpart_vat="123456783",
                         counterparty_id=4, net=Decimal("100.10"), vat=Decimal("24.02"),
                         withheld=Decimal("0.00"), gross=Decimal("124.12"),
                         other_taxes=Decimal("0.00"), stamp_duty=Decimal("0.00"),
                         fees=Decimal("0.00"), fuel_invoice=False, in_book=True, received=True,
                         self_declared=False, uid="", cancelled_by_mark="",
                         first_seen_fetch_id=7, last_seen_fetch_id=7)],
        "invoice_line": [dict(id=5, invoice_id=3, line_number=1, net=Decimal("100.10"),
                              vat_category=1, vat_amount=Decimal("24.02"),
                              vat_exemption_category=None)],
        "classification_snapshot": [dict(id=6, taxpayer_id=1, mark="900000000000003",
                                         source="e3_info", fetch_id=9,
                                         issue_date=date(2026, 7, 3), fetched_at=AT)],
        "classification_line": [dict(id=8, snapshot_id=6, kind="expense", category="category2_4",
                                     e3_type="E3_585_016", value=Decimal("100.10")),
                                dict(id=10, snapshot_id=6, kind="expense", category="category2_4",
                                     e3_type="E3_585_016", value=None)],
        "vat_code_line": [],
        "invoice_submission": [dict(id=11, taxpayer_id=1, at=AT, inv_type="17.2", series="0",
                                    aa="1", issue_date=date(2026, 7, 3), net=Decimal("1250.40"),
                                    issuer_vat="123456783", issuer_name="", counterparty_id=None,
                                    mark="900000000000011", uid="U", status="Success",
                                    request_xml="<a/>", response_xml="<b/>")],
        "classification_submission": [dict(id=12, taxpayer_id=1, at=AT, year=2026,
                                           invoice_mark="900000000000003",
                                           classification_mark="900000000000012",
                                           status="Success",
                                           errors=[{"code": "", "message": "μήνυμα"}],
                                           per_invoice=True, e3_type="E3_585_016",
                                           category="category2_4", amount=Decimal("100.10"),
                                           request_xml=None, response_xml=None)],
    }

class FakeSource:
    def __init__(self, data=None, versions=(1, 2), extra_rows=0):
        self.data = _data() if data is None else data
        self._versions, self.extra_rows = set(versions), extra_rows
    def versions(self):
        return self._versions
    def rows(self, table, cols):
        return [tuple(r[c] for c in cols) for r in self.data[table]]
    def totals(self, table, amounts):
        rows = self.data[table]
        return (len(rows) + self.extra_rows,
                {c: sum((r[c] for r in rows if r[c] is not None), Decimal(0)) for c in amounts})

@pytest.fixture
def target(tmp_path):
    return tmp_path / "νέα.sqlite3"

def test_αντιγραφή_κρατά_id_ποσά_σε_λεπτά_και_τύπους(target):
    out = []
    assert mig.migrate_from(FakeSource(), target, out.append) == 0
    conn = sqlite3.connect(target)
    assert conn.execute("select id, net, vat, gross from invoice").fetchall() == [(3, 10010, 2402, 12412)]
    assert conn.execute("select value from classification_line order by id").fetchall() == [(10010,), (None,)]
    assert conn.execute("select errors from classification_submission").fetchone()[0] == \
        json.dumps([{"code": "", "message": "μήνυμα"}], ensure_ascii=False)
    assert conn.execute("select fetched_at from mydata_fetch where id = 7").fetchone()[0] == \
        "2026-07-03T09:30:00.000Z"
    assert conn.execute("select separate_totals, environment from counterparty, taxpayer").fetchone() == (1, "production")
    # Νέες γραμμές συνεχίζουν μετά το μεγαλύτερο id, όπως το serial.
    new = conn.execute("insert into mydata_fetch (taxpayer_id, method, body) values (1, 'x', '') "
                       "returning id").fetchone()[0]
    conn.close()
    assert new == 10
    assert sum(line.startswith("ΙΔΙΑ") for line in out) == len(mig.TABLES)

def test_η_εφαρμογή_διαβάζει_τη_μεταφερμένη_βάση(target):
    assert mig.migrate_from(FakeSource(), target, lambda s: None) == 0
    from esoda_exoda.db import connect
    cfg = Config(data_dir=target.parent, database={"path": target.name})
    with connect(cfg) as conn:
        [row] = invoices_in_range(conn, 1, 2026, 7)
        [sub] = list_invoice_submissions(conn, 1)
        [cls] = list_classification_submissions(conn, 1, 2026)
    assert (row.net, row.vat) == (100.1, 24.02) and [l.value for l in row.e3_lines] == [100.1, 0.0]
    assert sub["net"] == 1250.4 and cls["amount"] == 100.1
    assert cls["errors"] == [{"code": "", "message": "μήνυμα"}] and cls["per_invoice"] is True

def test_τυπώνει_πλήθη_και_αθροίσματα_ανά_πίνακα(target):
    out = []
    mig.migrate_from(FakeSource(), target, out.append)
    text = "\n".join(out)
    for table in ("taxpayer", "invoice", "invoice_line", "classification_line",
                  "invoice_submission", "classification_submission"):
        assert table in text
    assert "1.250,40" in text and "100,10" in text

@pytest.mark.parametrize("versions", [(1,), (1, 2, 3), ()])
def test_αρνείται_άλλη_έκδοση_σχήματος(target, versions):
    out = []
    assert mig.migrate_from(FakeSource(versions=versions), target, out.append) == 1
    assert not target.exists() and any("schema_version" in line for line in out)

def test_διαφορά_στα_πλήθη_αποτυγχάνει_και_σβήνει_το_αρχείο(target):
    out = []
    assert mig.migrate_from(FakeSource(extra_rows=1), target, out.append) == 1
    assert not target.exists()
    assert any("ΔΙΑΦΟΡΑ" in line for line in out)

def test_σφάλμα_στη_μέση_δεν_αφήνει_μισό_αρχείο(target):
    data = _data()
    data["invoice"][0]["counterparty_id"] = 999  # foreign key που δεν υπάρχει
    with pytest.raises(sqlite3.IntegrityError):
        mig.migrate_from(FakeSource(data), target, lambda s: None)
    assert not target.exists()
    assert not list(target.parent.glob("*.sqlite3*"))

def test_δεν_γράφει_πάνω_σε_υπάρχουσα_βάση(target):
    target.write_bytes(b"x")
    out = []
    assert mig.migrate_from(FakeSource(), target, out.append) == 1
    assert target.read_bytes() == b"x" and any("υπάρχει ήδη" in line for line in out)

def test_καλύπτει_κάθε_πίνακα_του_σχήματος(db):
    tables = {r[0] for r in db.execute("select name from sqlite_master where type = 'table' "
                                       "and name not in ('schema_version', 'sqlite_sequence')")}
    assert [t for t in mig.TABLES] and set(mig.TABLES) == tables

def test_main_διαβάζει_από_ένα_στιγμιότυπο_μόνο_για_ανάγνωση(target, monkeypatch):
    # Ψεύτικο module psycopg: το test τρέχει και χωρίς το optional dependency.
    import enum, sys, types
    class IsolationLevel(enum.IntEnum):
        READ_COMMITTED = 2
        REPEATABLE_READ = 3
    seen = {}
    class Conn:
        isolation_level, read_only = None, False
        def __enter__(self): return self
        def __exit__(self, *a): return False
    fake = types.SimpleNamespace(IsolationLevel=IsolationLevel, connect=lambda dsn, **kw: Conn())
    monkeypatch.setitem(sys.modules, "psycopg", fake)
    monkeypatch.setattr(mig.getpass, "getpass", lambda prompt: "")
    def run(source, path, say):
        seen.update(isolation=source.conn.isolation_level, read_only=source.conn.read_only,
                    path=path)
        return 0
    monkeypatch.setattr(mig, "migrate_from", run)
    assert mig.main(["--dsn", "postgresql://x@127.0.0.1/y", str(target)]) == 0
    assert seen == {"isolation": IsolationLevel.REPEATABLE_READ, "read_only": True,
                    "path": target}
