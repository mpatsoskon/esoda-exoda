# ABOUTME: Γραμμή εντολών: χωρίς όρισμα σηκώνει την εφαρμογή· `setup` καταχωρεί τον
# ABOUTME: φορολογούμενο, το περιβάλλον myDATA και τα κλειδιά (keyring) μία φορά· `keys`
# ABOUTME: ξαναδίνει μόνο τα κλειδιά σε υπάρχουσα εγκατάσταση.
import argparse
import dataclasses
import getpass
from . import credentials
from .config import load_config
from .db import DbUnavailable, connect, dsn_from_parts, migrate
from .taxpayers import (ENVIRONMENTS, TaxpayerError, create_taxpayer, current_taxpayer,
                        is_valid_afm)

def _serve() -> None:
    import uvicorn
    uvicorn.run("esoda_exoda.web.app:app", host="127.0.0.1", port=8000)

def _ask_afm(ask, say) -> str:
    while True:
        afm = ask("ΑΦΜ: ").strip()
        if is_valid_afm(afm):
            return afm
        say("Ο ΑΦΜ δεν είναι έγκυρος (9 ψηφία με σωστό ψηφίο ελέγχου). Ξαναδοκίμασε.")

def _ask_environment(ask, say) -> str:
    while True:
        env = ask("Περιβάλλον myDATA (dev / production): ").strip()
        if env in ENVIRONMENTS:
            return env
        say("Γράψε ακριβώς «dev» ή «production».")

def _ask_nonempty(ask, prompt, say, what) -> str:
    while True:
        value = ask(prompt).strip()
        if value:
            return value
        say(f"Το {what} δεν μπορεί να είναι κενό. Ξαναδοκίμασε.")

def _cfg_with_db_password(cfg, ask_secret):
    """Χωρίς database_url (κανονική χρήση) ζητά τον κωδικό βάσης και χτίζει in-memory
    config· ο κωδικός γράφεται στο keyring μόνο αφού ολοκληρωθεί όλη η είσοδος."""
    if cfg.database_url:
        return cfg, None
    db_password = ask_secret("Κωδικός βάσης (POSTGRES_PASSWORD): ")
    return dataclasses.replace(
        cfg, database_url=dsn_from_parts(cfg.database, db_password)), db_password

def run_setup(cfg, ask, ask_secret, say) -> int:
    db_password = None
    try:
        cfg, db_password = _cfg_with_db_password(cfg, ask_secret)
        try:
            with connect(cfg) as conn:
                migrate(conn)
                if conn.execute("select count(*) from taxpayer").fetchone()[0]:
                    say("Υπάρχει ήδη φορολογούμενος σε αυτή τη βάση — δεν άλλαξε τίποτα. "
                        "Για να ξαναδώσεις κλειδιά myDATA τρέξε `esoda-exoda keys`.")
                    return 1
        except DbUnavailable as e:
            say(f"{e} — δεν άλλαξε τίποτα.")
            return 1
        afm = _ask_afm(ask, say)
        name = ask("Επωνυμία: ").strip()
        postal_code = ask("ΤΚ: ").strip()
        city = ask("Πόλη: ").strip()
        env = _ask_environment(ask, say)
        if env == "production":
            say("ΠΡΟΣΟΧΗ: στο production κάθε διαβίβαση στο myDATA είναι αμετάκλητη.")
            if ask("Γράψε ξανά τον ΑΦΜ για επιβεβαίωση: ").strip() != afm:
                say("Η επιβεβαίωση δεν ταιριάζει — δεν άλλαξε τίποτα.")
                return 1
        user_id = _ask_nonempty(ask, f"myDATA user id ({env}): ", say, "user id")
        key = _ask_nonempty(ask_secret, f"myDATA subscription key ({env}): ", say, "κλειδί")
    except (KeyboardInterrupt, EOFError):
        say("\nΑκυρώθηκε — δεν άλλαξε τίποτα.")
        return 1
    if db_password is not None:
        credentials.set_db_password(db_password)
    credentials.set_credentials(env, user_id, key)
    with connect(cfg) as conn:
        create_taxpayer(conn, afm, environment=env, name=name, postal_code=postal_code, city=city)
    say(f"Έτοιμο ({env}). Ξεκίνα την εφαρμογή με `esoda-exoda`.")
    return 0

def run_keys(cfg, ask, ask_secret, say) -> int:
    db_password = None
    try:
        cfg, db_password = _cfg_with_db_password(cfg, ask_secret)
        try:
            with connect(cfg) as conn:
                tp = current_taxpayer(conn)
        except DbUnavailable as e:
            say(f"{e} — δεν άλλαξε τίποτα.")
            return 1
        except TaxpayerError as e:
            say(f"{e} Δεν υπάρχει εγκατάσταση για να ξαναδώσεις κλειδιά — δεν άλλαξε τίποτα.")
            return 1
        say(f"Κλειδιά myDATA για το περιβάλλον {tp.environment}, ΑΦΜ {tp.afm}.")
        user_id = _ask_nonempty(ask, f"myDATA user id ({tp.environment}): ", say, "user id")
        key = _ask_nonempty(ask_secret, f"myDATA subscription key ({tp.environment}): ",
                            say, "κλειδί")
    except (KeyboardInterrupt, EOFError):
        say("\nΑκυρώθηκε — δεν άλλαξε τίποτα.")
        return 1
    if db_password is not None:
        credentials.set_db_password(db_password)
    credentials.set_credentials(tp.environment, user_id, key)
    say(f"Τα κλειδιά αποθηκεύτηκαν ({tp.environment}).")
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="esoda-exoda")
    parser.add_argument("command", nargs="?", choices=["setup", "keys"],
                        help="setup: αρχικό στήσιμο· keys: νέα κλειδιά/κωδικός βάσης σε "
                             "υπάρχουσα εγκατάσταση· χωρίς εντολή ξεκινά η εφαρμογή")
    args = parser.parse_args(argv)
    if args.command == "setup":
        return run_setup(load_config(), input, getpass.getpass, print)
    if args.command == "keys":
        return run_keys(load_config(), input, getpass.getpass, print)
    _serve()
    return 0
