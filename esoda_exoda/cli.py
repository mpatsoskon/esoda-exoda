# ABOUTME: Γραμμή εντολών: χωρίς όρισμα σηκώνει την εφαρμογή· `setup` καταχωρεί τον
# ABOUTME: φορολογούμενο, το περιβάλλον myDATA και τα κλειδιά (keyring) μία φορά· `keys`
# ABOUTME: ξαναδίνει μόνο τα κλειδιά myDATA· `backup <αρχείο>` αντιγράφει τη βάση.
import argparse
import getpass
import sqlite3
from . import credentials
from .config import load_config
from .db import DbUnavailable, backup, connect, migrate
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

def run_setup(cfg, ask, ask_secret, say) -> int:
    try:
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
    credentials.set_credentials(env, user_id, key)
    with connect(cfg) as conn:
        create_taxpayer(conn, afm, environment=env, name=name, postal_code=postal_code, city=city)
    say(f"Έτοιμο ({env}). Ξεκίνα την εφαρμογή με `esoda-exoda`.")
    return 0

def run_keys(cfg, ask, ask_secret, say) -> int:
    try:
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
    credentials.set_credentials(tp.environment, user_id, key)
    say(f"Τα κλειδιά αποθηκεύτηκαν ({tp.environment}).")
    return 0

def run_backup(cfg, target: str, say) -> int:
    try:
        path = backup(cfg, target)
    except (DbUnavailable, FileExistsError, OSError, sqlite3.Error) as e:
        say(f"{e} — δεν έγινε αντίγραφο.")
        return 1
    say(f"Αντίγραφο της βάσης στο {path}.")
    return 0

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="esoda-exoda")
    parser.add_argument("command", nargs="?", choices=["setup", "keys", "backup"],
                        help="setup: αρχικό στήσιμο· keys: νέα κλειδιά myDATA σε υπάρχουσα "
                             "εγκατάσταση· backup <αρχείο>: αντίγραφο της βάσης· χωρίς εντολή "
                             "ξεκινά η εφαρμογή")
    parser.add_argument("target", nargs="?", help="το αρχείο του αντιγράφου (για backup)")
    args = parser.parse_args(argv)
    if args.target is not None and args.command != "backup":
        parser.error("μόνο το backup δέχεται αρχείο")
    if args.command == "backup":
        if not args.target:
            parser.error("το backup θέλει αρχείο, π.χ. esoda-exoda backup αντίγραφο.sqlite3")
        return run_backup(load_config(), args.target, print)
    if args.command == "setup":
        return run_setup(load_config(), input, getpass.getpass, print)
    if args.command == "keys":
        return run_keys(load_config(), input, getpass.getpass, print)
    _serve()
    return 0
