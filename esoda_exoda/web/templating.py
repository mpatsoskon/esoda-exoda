# ABOUTME: Το κοινό Jinja2 environment, τα φίλτρα μορφοποίησης και το sidebar context.
# ABOUTME: Ζει χωριστά ώστε app.py και classify_routes.py να μη κάνουν κυκλική εισαγωγή.
from datetime import date, datetime
from pathlib import Path
from fastapi.templating import Jinja2Templates
from ..submissions import last_submission

templates = Jinja2Templates(directory=Path(__file__).resolve().parent / "templates")

# Η μορφοποίηση ζει στα φίλτρα και όχι στα templates: ένα ποσό με τελεία δεκαδικών
# ή μια ISO ημερομηνία μέσα σε ελληνική οθόνη διαβάζεται λάθος.
def eur(x) -> str:
    """Ελληνική μορφή: τελεία χιλιάδων, κόμμα δεκαδικών. Η μορφή που εμφανίζεται
    είναι μορφή που ο parse_amount δέχεται πίσω αναλλοίωτη — αλλιώς η οθόνη δεν
    επιβεβαιώνει τίποτα για το ποσό που θα διαβιβαστεί."""
    return f"{float(x):,.2f}".translate(str.maketrans({",": ".", ".": ","}))

templates.env.filters["eur"] = eur
templates.env.filters["imerominia"] = lambda s: date.fromisoformat(s).strftime("%d/%m/%Y")
templates.env.filters["ora"] = lambda s: datetime.fromisoformat(s).strftime("%d/%m/%Y %H:%M")

def parastatika(n: int) -> str:
    return f"{n} παραστατικό" if n == 1 else f"{n} παραστατικά"

templates.env.filters["parastatika"] = parastatika

def base_context(conn, cfg, taxpayer, screen: str, year: int, month: int) -> dict:
    """Το κοινό context κάθε οθόνης: ταυτότητα φορολογούμενου, θέση στη nav, και η τελευταία
    αμετάκλητη πράξη — το MARK είναι το μόνο χερούλι για ενδεχόμενη ακύρωση."""
    return {"cfg": cfg, "taxpayer": taxpayer, "screen": screen, "year": year, "month": month,
            "last": last_submission(conn, taxpayer.id)}
