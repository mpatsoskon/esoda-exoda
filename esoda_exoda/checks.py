# ABOUTME: Έλεγχοι πριν την αμετάκλητη υποβολή στο myDATA: τι μπλοκάρει και τι προειδοποιεί.
# ABOUTME: Καθαρές συναρτήσεις· τα preview routes φέρνουν τα δεδομένα και δείχνουν τα ευρήματα.
from dataclasses import dataclass
from datetime import date, timedelta
from .web.templating import eur

BLOCK = "block"
WARN = "warn"

@dataclass(frozen=True)
class Finding:
    level: str
    message: str
    mark: str = ""

# Ένας ολόκληρος λογαριασμός αντί για το 1/3 του είναι ×3: βγαίνει έξω από το εύρος ακόμη
# κι όταν δύο 13.3 του ίδιου μήνα συγκρίνονται μαζί.
_ABOVE_MAX = 1.5
_BELOW_MIN = 0.5
HISTORY_WINDOW = timedelta(days=365)

def _is_income_code(cfg, category: str, e3: str) -> bool:
    return category.startswith("category1_") or e3 in cfg.e3_income

def transmission_findings(cfg, *, inv_type: str, series: str, aa: str, issue_date: date,
                          net: float, history: list, today: date,
                          supplier=None) -> list[Finding]:
    out = []
    live = [h for h in history if not h.cancelled and h.inv_type == inv_type]
    if any(h.series == series and h.aa == aa and h.issue_date.year == issue_date.year
           for h in live):
        out.append(Finding(BLOCK,
            f"Υπάρχει ήδη διαβιβασμένο {inv_type} με Σειρά {series} / ΑΑ {aa} μέσα στο "
            f"{issue_date.year}. Δεύτερη διαβίβαση θα διπλασίαζε το έξοδο. Αν το ακύρωσες "
            "από το portal, κάνε πρώτα Ανανέωση βιβλίων."))
    window = [h.net for h in live
              if issue_date - HISTORY_WINDOW <= h.issue_date <= issue_date
              and (supplier is None or h.issuer_vat == supplier.vat)]
    if window and (net > _ABOVE_MAX * max(window) or net < _BELOW_MIN * min(window)):
        out.append(Finding(WARN,
            f"Καθαρή αξία {eur(net)} €, ασυνήθιστη για {inv_type}: τους τελευταίους 12 μήνες "
            f"διαβιβάστηκαν από {eur(min(window))} έως {eur(max(window))} €."))
    # Με αυτόματο ΑΑ (14.x, 17.2 με κενό ΑΑ) ή λάθος πληκτρολογημένο, μια δεύτερη διαβίβαση
    # του ίδιου παραστατικού παίρνει νέο ΑΑ και ο T1 δεν τη βλέπει. Ίδια σειρά και ΑΑ τα
    # μπλοκάρει ήδη ο T1.
    for h in live:
        if ((h.issue_date.year, h.issue_date.month) == (issue_date.year, issue_date.month)
                and round(h.net, 2) == round(net, 2)
                and (h.series, h.aa) != (series, aa)
                and (supplier is None or h.issuer_vat == supplier.vat)):
            out.append(Finding(WARN,
                f"Υπάρχει ήδη διαβιβασμένο {inv_type} των {eur(h.net)} € στις "
                f"{h.issue_date:%d/%m/%Y} (Σειρά {h.series} / ΑΑ {h.aa}). Αν είναι το ίδιο "
                "παραστατικό, μην το ξαναστείλεις."))
    if issue_date > today:
        out.append(Finding(WARN, f"Η ημερομηνία {issue_date:%d/%m/%Y} είναι μετά τη σημερινή."))
    if issue_date.year != today.year:
        out.append(Finding(WARN, f"Η ημερομηνία {issue_date:%d/%m/%Y} είναι σε άλλο έτος "
                                 f"από το τρέχον ({today.year})."))
    if supplier is not None:
        if _is_income_code(cfg, supplier.category, supplier.e3):
            out.append(Finding(BLOCK,
                f"Η προεπιλογή του προμηθευτή {supplier.name} έχει κωδικό εσόδου "
                f"({supplier.category} / {supplier.e3}). Διόρθωσέ τη στη φόρμα "
                "αντισυμβαλλόμενου."))
        if supplier.e3 == "E3_585_009":
            out.append(Finding(WARN,
                f"Ο {supplier.name} είναι προμηθευτής εξωτερικού, αλλά ο κωδικός Ε3 είναι "
                "E3_585_009 (υπηρεσίες ημεδαπής). Για υπηρεσίες αλλοδαπής υπάρχει ο E3_585_010."))
    return out

def classification_findings(cfg, sel, issuer_vat: str, default) -> list[Finding]:
    e3, cat, out = sel.e3_type, sel.category, []
    if _is_income_code(cfg, cat, e3):
        out.append(Finding(BLOCK, f"{sel.mark}: κωδικός εσόδου ({cat} / {e3}) σε "
                                  "χαρακτηρισμό εξόδου.", sel.mark))
    if (e3 == "E3_587") != (cat == "category2_8"):
        out.append(Finding(WARN, f"Ο κωδικός {e3} δεν ταιριάζει με την κατηγορία {cat}: "
                                 "οι αποσβέσεις είναι E3_587 με 2.8.", sel.mark))
    if e3.startswith(("E3_882", "E3_883")) != (cat == "category2_7"):
        out.append(Finding(WARN, f"Ο κωδικός {e3} δεν ταιριάζει με την κατηγορία {cat}: "
                                 "οι αγορές παγίων είναι E3_882/E3_883 με 2.7.", sel.mark))
    if default is not None and ((default.e3_code and e3 != default.e3_code)
                            or (default.category_code and cat != default.category_code)):
        out.append(Finding(WARN, "Διαφέρει από την προεπιλογή του αντισυμβαλλόμενου "
                                 f"({default.e3_code} / {default.category_code}).", sel.mark))
    if e3 == "E3_585_010" and len(issuer_vat) == 9 and issuer_vat.isdigit():
        out.append(Finding(WARN, "E3_585_010 (υπηρεσίες αλλοδαπής) σε εκδότη με ελληνικό ΑΦΜ.",
                           sel.mark))
    return out
