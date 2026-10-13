# ABOUTME: Σύνδεση με SQLite (ένα αρχείο), συναλλαγή ανά αίτημα, migrations από αριθμημένα
# ABOUTME: .sql, backup και μετατροπή ποσών σε ακέραια λεπτά. Καμία γνώση του σχήματος εδώ.
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION = re.compile(r"^(\d{3})_.+\.sql$")
# Δευτερόλεπτα αναμονής όταν άλλη σύνδεση γράφει. Μεταβλητή του module ώστε τα tests να
# τη μικραίνουν.
BUSY_TIMEOUT = 5.0
# RETURNING (3.35) και window functions (3.25) χρειάζονται αυτή την έκδοση.
_MIN_SQLITE = (3, 35, 0)

class DbUnavailable(RuntimeError):
    pass

# Τύποι: η SQLite κρατά date/timestamptz ως κείμενο ISO-8601 και boolean ως 0/1. Οι converters
# (PARSE_DECLTYPES, από τον δηλωμένο τύπο της στήλης) δίνουν πίσω date, datetime με ζώνη και
# bool, ώστε ο κώδικας να καλεί .year/.astimezone() και τα templates `is true` όπως πριν.
def _adapt_datetime(d: datetime) -> str:
    if d.tzinfo is None:
        raise ValueError("timestamptz χωρίς ζώνη ώρας")
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def _convert_timestamptz(b: bytes) -> datetime:
    # Πάντα UTC στη βάση· πίσω σε τοπική ώρα για την οθόνη.
    return datetime.fromisoformat(b.decode()).astimezone()

sqlite3.register_adapter(date, date.isoformat)
sqlite3.register_adapter(datetime, _adapt_datetime)
sqlite3.register_converter("date", lambda b: date.fromisoformat(b.decode()))
sqlite3.register_converter("timestamptz", _convert_timestamptz)
sqlite3.register_converter("boolean", lambda b: int(b) != 0)

# Ποσά: ακέραια λεπτά στη βάση, ώστε κάθε εγγραφή και κάθε sum() να είναι ακριβή, όπως
# ήταν το numeric(12,2). Ο κώδικας δουλεύει σε float ευρώ· η μετατροπή γίνεται μόνο εδώ.
def to_cents(amount) -> int | None:
    """Ευρώ (float, int, Decimal ή str) → ακέραια λεπτά, στρογγυλεμένα όπως το
    numeric(12,2): μισό λεπτό προς τα έξω από το μηδέν. Το str(float) δίνει τη συντομότερη
    δεκαδική μορφή, άρα 0.1 + 0.2 γίνεται 30 και όχι 30.000000000000004."""
    if amount is None:
        return None
    return int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))

def from_cents(cents: int | None) -> float | None:
    return None if cents is None else cents / 100

def open_db(path, timeout: float | None = None) -> sqlite3.Connection:
    """Νέα σύνδεση με τις ρυθμίσεις που θέλει κάθε χρήση: converters, foreign keys (αλλιώς
    τα `on delete cascade` δεν κάνουν τίποτα) και WAL (η οθόνη διαβάζει όσο γράφει η
    ανανέωση)."""
    if sqlite3.sqlite_version_info < _MIN_SQLITE:
        raise DbUnavailable(f"Η SQLite {sqlite3.sqlite_version} είναι παλιά· χρειάζεται "
                            f"{'.'.join(map(str, _MIN_SQLITE))} ή νεότερη.")
    try:
        conn = sqlite3.connect(path, timeout=BUSY_TIMEOUT if timeout is None else timeout,
                               detect_types=sqlite3.PARSE_DECLTYPES)
    except sqlite3.OperationalError as e:
        raise DbUnavailable(f"Δεν ανοίγει το αρχείο της βάσης {path} ({e}). Έλεγξε το "
                            "[database] path και το data_dir στο config.toml.") from e
    try:
        conn.execute("pragma foreign_keys = on")
        conn.execute("pragma journal_mode = wal")
    except sqlite3.Error:
        conn.close()
        raise
    return conn

@contextmanager
def connect(cfg):
    """Μία συναλλαγή: commit στην έξοδο, rollback σε εξαίρεση. Έτσι μια ανανέωση που
    σκάει στην πέμπτη κλήση αφήνει τη βάση όπως ήταν."""
    conn = open_db(cfg.db_path())
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

def begin_immediate(cfg) -> sqlite3.Connection:
    """Σύνδεση που κρατά ήδη το κλείδωμα εγγραφής (BEGIN IMMEDIATE). Για πριν από κάθε
    αμετάκλητο POST: αν άλλη σύνδεση γράφει (π.χ. ανανέωση σε εξέλιξη), σκάει ΕΔΩ με
    DbUnavailable, πριν φύγει οτιδήποτε προς την ΑΑΔΕ, αντί να σκάσει μετά η καταγραφή του
    MARK. Ο καλών κάνει commit και close."""
    conn = open_db(cfg.db_path())
    try:
        conn.execute("begin immediate")
    except sqlite3.OperationalError as e:
        conn.close()
        raise DbUnavailable(f"Η βάση είναι πιασμένη από άλλη εργασία (π.χ. ανανέωση): {e}.") from e
    return conn

def _applied(conn) -> set[int]:
    exists = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = 'schema_version'"
    ).fetchone()
    if not exists:
        return set()
    return {r[0] for r in conn.execute("select version from schema_version")}

def migrate(conn) -> list[int]:
    """Εφαρμόζει ό,τι λείπει, με αύξουσα σειρά, κάθε migration σε δική της συναλλαγή.
    Επιστρέφει τις εκδόσεις που εφαρμόστηκαν τώρα. Το executescript κάνει commit ό,τι
    εκκρεμεί πριν τρέξει, γι' αυτό το begin/commit μπαίνει μέσα στο ίδιο το script."""
    conn.commit()
    done = _applied(conn)
    applied = []
    for path in sorted(MIGRATIONS_DIR.iterdir()):
        m = _MIGRATION.match(path.name)
        if not m:
            continue
        version = int(m.group(1))
        if version in done:
            continue
        try:
            conn.executescript(
                f"begin;\n{path.read_text(encoding='utf-8')}\n;"
                f"insert into schema_version (version) values ({version});\ncommit;")
        except Exception as e:
            if conn.in_transaction:
                conn.rollback()
            raise RuntimeError(f"Η migration {path.name} απέτυχε: {e}") from e
        applied.append(version)
    return applied

def backup(cfg, target) -> Path:
    """Αντίγραφο της βάσης σε νέο αρχείο με το Connection.backup() της SQLite: σωστό και όσο
    τρέχει η εφαρμογή, ενώ η απλή αντιγραφή του αρχείου σε WAL μπορεί να χάσει δεδομένα."""
    source, target = cfg.db_path(), Path(target).resolve()
    if not source.is_file():
        raise DbUnavailable(f"Δεν υπάρχει βάση στο {source}.")
    if target.exists():
        raise FileExistsError(f"Το {target} υπάρχει ήδη· διάλεξε νέο όνομα αρχείου.")
    src = open_db(source)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)
        finally:
            dst.close()
    except BaseException:
        # Ένα μισό αντίγραφο (π.χ. γέμισε ο δίσκος) μοιάζει με κανονική βάση· δεν μένει.
        for p in (target, Path(f"{target}-journal")):
            p.unlink(missing_ok=True)
        raise
    finally:
        src.close()
    return target
