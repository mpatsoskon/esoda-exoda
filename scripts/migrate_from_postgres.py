# ABOUTME: Μετάπτωση της παλιάς βάσης Postgres σε αρχείο SQLite. Δέχεται μόνο schema_version 2,
# ABOUTME: κρατά τα ίδια id, γράφει τα ποσά σε λεπτά και συγκρίνει πλήθη και αθροίσματα ανά πίνακα.
import argparse
import getpass
import json
import sys
from pathlib import Path

from esoda_exoda.config import load_config
from esoda_exoda.db import migrate, open_db, to_cents

# Σειρά αντιγραφής: κάθε πίνακας μετά από όσους δείχνουν τα foreign keys του.
TABLES = ("taxpayer", "counterparty", "classification_default", "mydata_fetch", "invoice",
          "invoice_line", "classification_snapshot", "classification_line", "vat_code_line",
          "invoice_submission", "classification_submission")
# numeric(12,2) στην Postgres, ακέραια λεπτά στη SQLite.
AMOUNTS = {"invoice": ("net", "vat", "withheld", "gross", "other_taxes", "stamp_duty", "fees"),
           "invoice_line": ("net", "vat_amount"),
           "classification_line": ("value",),
           "vat_code_line": ("value",),
           "invoice_submission": ("net",),
           "classification_submission": ("amount",)}
JSON_COLUMNS = {"classification_submission": ("errors",)}
SCHEMA_VERSION = 2

class Postgres:
    """Η πηγή: μόνο τα τρία ερωτήματα που χρειάζεται η μετάπτωση."""
    def __init__(self, conn):
        self.conn = conn

    def versions(self) -> set[int]:
        exists = self.conn.execute("select to_regclass('public.schema_version')").fetchone()[0]
        if exists is None:
            return set()
        return {r[0] for r in self.conn.execute("select version from schema_version")}

    def rows(self, table, cols):
        return self.conn.execute(f"select {', '.join(cols)} from {table} order by id")

    def totals(self, table, amounts):
        sums = "".join(f", sum({c})" for c in amounts)
        row = self.conn.execute(f"select count(*){sums} from {table}").fetchone()
        return row[0], dict(zip(amounts, row[1:]))

def _columns(conn, table) -> list[str]:
    return [r[1] for r in conn.execute(f"pragma table_info({table})")]

def _convert(table, cols, row) -> list:
    amounts, js = AMOUNTS.get(table, ()), JSON_COLUMNS.get(table, ())
    out = []
    for col, v in zip(cols, row):
        if col in amounts:
            v = to_cents(v)
        elif col in js:
            v = json.dumps(v, ensure_ascii=False)
        out.append(v)
    return out

def _eur(cents) -> str:
    return f"{(cents or 0) / 100:,.2f}".translate(str.maketrans({",": ".", ".": ","}))

def _compare(source, conn, say) -> bool:
    ok = True
    for table in TABLES:
        amounts = AMOUNTS.get(table, ())
        n_src, sums_src = source.totals(table, amounts)
        sums = "".join(f", sum({c})" for c in amounts)
        row = conn.execute(f"select count(*){sums} from {table}").fetchone()
        parts = [f"γραμμές {n_src} → {row[0]}"]
        same = n_src == row[0]
        for col, got in zip(amounts, row[1:]):
            want = to_cents(sums_src[col] or 0)
            parts.append(f"{col} {_eur(want)} → {_eur(got)}")
            same = same and want == (got or 0)
        ok = ok and same
        say(f"{'ΙΔΙΑ   ' if same else 'ΔΙΑΦΟΡΑ'} {table}: " + ", ".join(parts))
    return ok

def _remove(target: Path) -> None:
    for p in (target, Path(f"{target}-wal"), Path(f"{target}-shm")):
        p.unlink(missing_ok=True)

def migrate_from(source, target, say) -> int:
    """Αντιγράφει όλη την πηγή σε νέο αρχείο SQLite. Επιστρέφει 0 μόνο όταν πλήθη και
    αθροίσματα ποσών συμφωνούν σε κάθε πίνακα· αλλιώς σβήνει το νέο αρχείο, ώστε να μη
    μείνει μισή βάση που μοιάζει έτοιμη. Η πηγή δεν αλλάζει ποτέ."""
    target = Path(target)
    if target.exists():
        say(f"Το {target} υπάρχει ήδη — δεν γράφω πάνω σε υπάρχουσα βάση.")
        return 1
    versions = source.versions()
    if not versions or max(versions) != SCHEMA_VERSION or versions != set(range(1, SCHEMA_VERSION + 1)):
        say(f"Η Postgres έχει schema_version {sorted(versions) or 'κανένα'}· η μετάπτωση "
            f"δέχεται μόνο την έκδοση {SCHEMA_VERSION} (με τη στήλη environment). Τρέξε πρώτα "
            "την προηγούμενη έκδοση της εφαρμογής πάνω στην Postgres ώστε να αναβαθμιστεί.")
        return 1
    conn = open_db(target)
    try:
        migrate(conn)
        for table in TABLES:
            cols = _columns(conn, table)
            sql = (f"insert into {table} ({', '.join(cols)}) "
                   f"values ({', '.join('?' * len(cols))})")
            conn.executemany(sql, (_convert(table, cols, r) for r in source.rows(table, cols)))
        conn.commit()
        ok = _compare(source, conn, say)
    except BaseException:
        conn.close()
        _remove(target)
        raise
    conn.close()
    if not ok:
        _remove(target)
        say("Πλήθη ή αθροίσματα δεν συμφωνούν — το νέο αρχείο σβήστηκε. Η Postgres έμεινε ως "
            "είχε.")
        return 1
    say(f"Η μετάπτωση ολοκληρώθηκε: {target}")
    return 0

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Μετάπτωση από Postgres σε SQLite.")
    parser.add_argument("--dsn", default="postgresql://esoda@127.0.0.1:5432/esoda_exoda",
                        help="η παλιά βάση (προεπιλογή: η βάση του docker compose)")
    parser.add_argument("target", nargs="?",
                        help="το νέο αρχείο SQLite (προεπιλογή: το [database] path του config)")
    args = parser.parse_args(argv)
    try:
        import psycopg
    except ImportError:
        print("Λείπει ο psycopg. Εγκατάστησέ τον με: pip install -e .[postgres]")
        return 1
    target = Path(args.target) if args.target else load_config().db_path()
    password = getpass.getpass("Κωδικός της Postgres (κενό: από το DSN ή το PGPASSWORD): ")
    kwargs = {"password": password} if password else {}
    with psycopg.connect(args.dsn, **kwargs) as pg:
        # Ένα στιγμιότυπο για όλη τη μετάπτωση: αν η παλιά εφαρμογή γράφει την ίδια ώρα,
        # αντιγραφή και σύγκριση βλέπουν την ίδια βάση, όχι πίνακες από διαφορετικές στιγμές.
        pg.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        pg.read_only = True
        return migrate_from(Postgres(pg), target, print)

if __name__ == "__main__":
    sys.exit(main())
