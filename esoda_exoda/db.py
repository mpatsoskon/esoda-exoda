# ABOUTME: Σύνδεση με PostgreSQL (psycopg 3), συναλλαγή ανά αίτημα και migrations
# ABOUTME: από αριθμημένα .sql. Καμία γνώση του σχήματος εδώ — μόνο ο μηχανισμός.
import re
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
import psycopg
from . import credentials

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
_MIGRATION = re.compile(r"^(\d{3})_.+\.sql$")

class DbUnavailable(RuntimeError):
    pass

def dsn(cfg) -> str:
    """Το database_url (tests) υπερισχύει· αλλιώς [database] + κωδικός από keyring, ώστε
    το config.toml να μη φέρει ποτέ κωδικό."""
    if cfg.database_url:
        return cfg.database_url
    d = cfg.database
    try:
        pw = credentials.get_db_password()
    except RuntimeError as e:
        # Χωρίς κωδικό στο keyring δεν φτιάχνεται DSN· DbUnavailable ώστε να δείξει η db_down,
        # όχι 500.
        raise DbUnavailable(str(e)) from e
    return dsn_from_parts(d, pw)

def dsn_from_parts(database: dict, password: str) -> str:
    user = quote(str(database.get('user', 'esoda')), safe="")
    return (f"postgresql://{user}:{quote(password, safe='')}@"
            f"{database.get('host', '127.0.0.1')}:{database.get('port', 5432)}/"
            f"{database.get('dbname', 'esoda_exoda')}")

@contextmanager
def connect(cfg):
    """Μία συναλλαγή: commit στην έξοδο, rollback σε εξαίρεση. Έτσι μια ανανέωση που
    σκάει στην πέμπτη κλήση αφήνει τη βάση όπως ήταν."""
    try:
        conn = psycopg.connect(dsn(cfg))
    except psycopg.OperationalError as e:
        raise DbUnavailable(
            f"Η βάση δεν απαντά ({e}). Τρέξε `docker compose up -d` και ξαναφόρτωσε.") from e
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()

def _applied(conn) -> set[int]:
    exists = conn.execute(
        "select 1 from information_schema.tables where table_name = 'schema_version' "
        "and table_schema = 'public'"
    ).fetchone()
    if not exists:
        return set()
    return {r[0] for r in conn.execute("select version from schema_version")}

def migrate(conn) -> list[int]:
    """Εφαρμόζει ό,τι λείπει, με αύξουσα σειρά, κάθε migration σε δική της συναλλαγή.
    Επιστρέφει τις εκδόσεις που εφαρμόστηκαν τώρα."""
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
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("insert into schema_version (version) values (%s)", (version,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise RuntimeError(f"Η migration {path.name} απέτυχε: {e}") from e
        applied.append(version)
    return applied
