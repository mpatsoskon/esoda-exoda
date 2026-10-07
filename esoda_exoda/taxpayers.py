# ABOUTME: Ο φορολογούμενος (πίνακας taxpayer) και το περιβάλλον myDATA του. Στη Φάση Α
# ABOUTME: υπάρχει ακριβώς ένας· το current_taxpayer είναι το ένα σημείο επιλογής.
from dataclasses import dataclass

ENVIRONMENTS = ("dev", "production")

class TaxpayerError(RuntimeError):
    pass

@dataclass(frozen=True)
class Taxpayer:
    id: int
    afm: str
    name: str
    postal_code: str
    city: str
    environment: str

_COLS = "id, afm, name, postal_code, city, environment"

def is_valid_afm(afm: str) -> bool:
    """Ελληνικός ΑΦΜ: 9 ψηφία, το τελευταίο ψηφίο ελέγχου (mod 11 των βαρών 2^8..2^1)."""
    if len(afm) != 9 or not (afm.isascii() and afm.isdecimal()) or afm == "000000000":
        return False
    digits = [int(c) for c in afm]
    total = sum(d * 2 ** (8 - i) for i, d in enumerate(digits[:8]))
    return total % 11 % 10 == digits[8]

def create_taxpayer(conn, afm: str, *, environment: str, name: str = "",
                    postal_code: str = "", city: str = "") -> Taxpayer:
    row = conn.execute(
        f"insert into taxpayer (afm, name, postal_code, city, environment) "
        f"values (%s, %s, %s, %s, %s) returning {_COLS}",
        (afm, name, postal_code, city, environment)).fetchone()
    return Taxpayer(*row)

def current_taxpayer(conn) -> Taxpayer:
    rows = conn.execute(f"select {_COLS} from taxpayer order by id").fetchall()
    if not rows:
        raise TaxpayerError("Δεν υπάρχει φορολογούμενος στη βάση. Τρέξε `esoda-exoda setup`.")
    if len(rows) > 1:
        raise TaxpayerError("Πολλοί φορολογούμενοι στη βάση — η επιλογή δεν υποστηρίζεται "
                            "ακόμη (Φάση Β).")
    return Taxpayer(*rows[0])
