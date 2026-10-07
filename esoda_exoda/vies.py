# ABOUTME: Αναζήτηση ΑΦΜ στο VIES της ΕΕ (REST, χωρίς κωδικούς): επωνυμία, ΤΚ και πόλη για να
# ABOUTME: συμπληρώνονται αντισυμβαλλόμενοι. Το myDATA δεν δίνει επωνυμία για ελληνικές οντότητες.
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass

BASE = "https://ec.europa.eu/taxation_customs/vies/rest-api/ms"
TIMEOUT = 15

class ViesError(RuntimeError):
    pass

@dataclass(frozen=True)
class ViesResult:
    valid: bool
    name: str = ""
    postal_code: str = ""
    city: str = ""

def _clean(s: str) -> str:
    return " ".join(s.split())

def _name(raw: str) -> str:
    # Οι ελληνικές απαντήσεις δίνουν «ΕΠΩΝΥΜΙΑ||ΤΙΤΛΟΣ»· όπου μια χώρα δεν μοιράζεται
    # στοιχεία, το πεδίο είναι «---».
    if _clean(raw) in ("", "---"):
        return ""
    legal, _, title = raw.partition("||")
    legal, title = _clean(legal), _clean(title)
    return f"{title} — {legal}" if title else legal

def parse(body: dict) -> ViesResult:
    status = body.get("userError")
    if status in ("INVALID", "INVALID_INPUT"):
        return ViesResult(False)
    if status != "VALID":
        raise ViesError(f"Το VIES δεν έδωσε απάντηση ({status or 'άγνωστο σφάλμα'}). "
                        "Δοκίμασε ξανά αργότερα.")
    # Μόνο η ελληνική μορφή «… 10000 - ΑΛΦΑΠΟΛΗ»· σε άλλες μορφές το ΤΚ δεν μαντεύεται.
    m = re.search(r"(\d{5})\s*-\s*([^\n]+?)\s*$", body.get("address") or "")
    return ViesResult(True, _name(body.get("name") or ""),
                      m.group(1) if m else "", _clean(m.group(2)) if m else "")

def lookup(country: str, vat: str, opener=urllib.request.urlopen) -> ViesResult:
    number = vat.replace(" ", "")
    # Ένα πρόθεμα στον αριθμό λέει τη χώρα πιο αξιόπιστα από την αποθηκευμένη: στη βάση
    # υπάρχει γερμανικός ΑΦΜ καταχωρημένος με χώρα GR.
    if number[:2].isalpha():
        country, number = number[:2].upper(), number[2:]
    member = "EL" if country == "GR" else country
    req = urllib.request.Request(f"{BASE}/{member}/vat/{urllib.parse.quote(number)}",
                                 headers={"Accept": "application/json"})
    try:
        with opener(req, timeout=TIMEOUT) as resp:
            body = json.load(resp)
    except (OSError, ValueError) as e:
        raise ViesError(f"Το VIES δεν απάντησε: {e}") from e
    return parse(body)

def fill_empty(fields: dict, r: ViesResult) -> list[str]:
    """Γράφει μόνο σε κενά πεδία: ό,τι έχει ήδη γραφτεί, από χέρι ή από πριν, μένει."""
    filled = []
    for key, value in (("name", r.name), ("postal_code", r.postal_code), ("city", r.city)):
        if value and not fields.get(key):
            fields[key] = value
            filled.append(key)
    return filled
