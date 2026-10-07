# ABOUTME: Παράγει τις σειρές βιβλίου (SheetRow) από τη βάση: παραστατικό + τρέχων χαρακτηρισμός
# ABOUTME: + προεπιλογή αντισυμβαλλόμενου. Αντικαθιστά mapping.py και mydata_client.fetch_docs.
from datetime import datetime
from .counterparties import ClassificationDefault
from .fetches import refresh_dates
from .invoices import InvoiceRow, invoices_in_range
from .models import SheetRow, UNKNOWN_DEDUCTION
from .taxpayers import Taxpayer

def deductible_flag(category_code: str) -> str:
    """Το category2_5 είναι η μόνη κατηγορία εξόδων χωρίς δικαίωμα έκπτωσης ΦΠΑ. Ανοιχτό
    ερώτημα προς τον λογιστή για νέες κατηγορίες — εδώ είναι το ένα σημείο που θα αλλάξει."""
    return "ΌΧΙ" if category_code == "category2_5" else "ΝΑΙ"

def _defaults(conn, ids: set[int]) -> dict[tuple[int, str], ClassificationDefault]:
    if not ids:
        return {}
    rows = conn.execute(
        "select counterparty_id, direction, category_code, e3_code, deductible, inv_type "
        "from classification_default where counterparty_id = any(%s)", (list(ids),)).fetchall()
    return {(r[0], r[1]): ClassificationDefault(*r[1:]) for r in rows}

def _base(cfg, r: InvoiceRow, afm: str, col_j) -> dict:
    return dict(type=cfg.type_labels.get(r.inv_type, r.inv_type), series=r.series, aa=r.aa,
                date=r.issue_date, afm=afm, net=r.net, vat=r.vat, total=round(r.net + r.vat, 2),
                col_j=col_j)

def _labels(cfg, category: str, e3_type: str) -> dict:
    return dict(charact="ΝΑΙ", category=cfg.category_labels.get(category, category),
                kind=cfg.e3_labels.get(e3_type, e3_type), flagged=False)

def _income_row(cfg, r: InvoiceRow, d: ClassificationDefault | None) -> SheetRow:
    base = _base(cfg, r, r.counterpart_vat, r.withheld)
    if r.transmitted and r.transmitted.kind == "income":
        return SheetRow(**base, **_labels(cfg, r.transmitted.category, r.transmitted.e3_type))
    if d:
        return SheetRow(**base, **_labels(cfg, d.category_code, d.e3_code))
    return SheetRow(**base, charact="", category="", kind="", flagged=True)

def _expense_row(cfg, taxpayer: Taxpayer, r: InvoiceRow, d: ClassificationDefault | None) -> SheetRow:
    afm = r.issuer_vat or r.counterpart_vat or taxpayer.afm
    if r.transmitted and r.transmitted.kind == "expense":
        c = r.transmitted
        return SheetRow(**_base(cfg, r, afm, deductible_flag(c.category)), **_labels(cfg, c.category, c.e3_type))
    if r.e3_lines:
        l = r.e3_lines[0]
        return SheetRow(**_base(cfg, r, afm, deductible_flag(l.category)), **_labels(cfg, l.category, l.e3_type))
    if d:
        # Χωρίς επίσημο χαρακτηρισμό, η προεπιλογή του αντισυμβαλλόμενου. Χωρίς απόφαση
        # για το «εκπίπτει», ΑΓΝΩΣΤΟ — ένα σιωπηλό ΝΑΙ έδωσε λάθος υπόλοιπο ΦΠΑ το 2026.
        flag = UNKNOWN_DEDUCTION if d.deductible is None else ("ΝΑΙ" if d.deductible else "ΌΧΙ")
        return SheetRow(**_base(cfg, r, afm, flag), **_labels(cfg, d.category_code, d.e3_code))
    return SheetRow(**_base(cfg, r, afm, UNKNOWN_DEDUCTION), charact="", category="", kind="", flagged=True)

def book_rows(conn, cfg, taxpayer: Taxpayer, year: int, month: int | None = None):
    rows = invoices_in_range(conn, taxpayer.id, year, month)
    defaults = _defaults(conn, {r.counterparty_id for r in rows if r.counterparty_id})
    income, expenses = [], []
    for r in rows:
        if r.direction == "income":
            if r.in_book:
                income.append(_income_row(cfg, r, defaults.get((r.counterparty_id, "income"))))
            continue
        # Στα βιβλία μπαίνει ό,τι λέει το βιβλίο εξόδων, και τα αυτο-δηλωθέντα που το βιβλίο
        # δεν δείχνει (13.x/17.x), εκτός από ακυρωμένα. Ένα ληφθέν χωρίς βιβλίο δεν μπαίνει.
        if r.in_book or (r.self_declared and not r.cancelled_by_mark):
            expenses.append(_expense_row(cfg, taxpayer, r, defaults.get((r.counterparty_id, "expense"))))
    key = lambda x: (x.date, x.series, x.aa)
    return sorted(income, key=key), sorted(expenses, key=key)

def flagged_afms(income, expenses) -> list[str]:
    return sorted({r.afm for r in (*income, *expenses) if r.flagged})

def month_overview(conn, cfg, taxpayer: Taxpayer, year: int) -> list[dict]:
    income, expenses = book_rows(conn, cfg, taxpayer, year)
    dates = refresh_dates(conn, taxpayer.id, year)
    months = sorted({r.date.month for r in (*income, *expenses)} | set(dates))
    return [{"month": m,
             "income": sum(1 for r in income if r.date.month == m),
             "expenses": sum(1 for r in expenses if r.date.month == m),
             "unknown": sum(1 for r in expenses if r.date.month == m and r.col_j == UNKNOWN_DEDUCTION),
             "last_refresh": dates.get(m)} for m in months]
