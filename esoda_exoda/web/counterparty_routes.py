# ABOUTME: Οθόνη αντισυμβαλλόμενων: λίστα (πρώτοι όσοι παράγουν ΑΓΝΩΣΤΟ), φόρμα δημιουργίας
# ABOUTME: και επεξεργασίας με τον προεπιλεγμένο χαρακτηρισμό ανά direction.
from datetime import date
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from ..config import load_config
from ..counterparties import (Counterparty, ClassificationDefault, CounterpartyError,
                              get_counterparty, list_counterparties, save_counterparty)
from ..db import connect
from ..taxpayers import current_taxpayer
from ..vies import ViesError, fill_empty, lookup as vies_lookup
from .templating import templates, base_context

router = APIRouter()

def _ctx(conn, cfg, tp, **extra):
    today = date.today()
    return {**base_context(conn, cfg, tp, "counterparties", today.year, today.month), **extra}

@router.get("/counterparties", response_class=HTMLResponse)
def counterparties(request: Request, saved: int | None = None):
    cfg = load_config()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        ctx = _list_ctx(conn, cfg, tp, saved=saved)
    return templates.TemplateResponse(request, "counterparties.html", ctx)

def _list_ctx(conn, cfg, tp, **extra):
    rows = list_counterparties(conn, tp.id)
    return _ctx(conn, cfg, tp, rows=rows, nameless=sum(1 for r in rows if not r["cp"].name), **extra)

def _form_of(cp: Counterparty) -> dict:
    e, i = cp.defaults.get("expense"), cp.defaults.get("income")
    return {"vat": cp.vat, "country": cp.country, "name": cp.name, "postal_code": cp.postal_code,
            "city": cp.city, "notes": cp.notes, "separate_totals": cp.separate_totals,
            "exp_category": e.category_code if e else "", "exp_e3": e.e3_code if e else "",
            "exp_deductible": "" if not e or e.deductible is None else ("ΝΑΙ" if e.deductible else "ΌΧΙ"),
            "exp_inv_type": e.inv_type if e else "",
            "inc_category": i.category_code if i else "", "inc_e3": i.e3_code if i else ""}

def _cp_of(form: dict, taxpayer_id: int, cp_id: int | None) -> Counterparty:
    cp = Counterparty(id=cp_id, taxpayer_id=taxpayer_id, vat=form["vat"].strip(),
                      country=form["country"].strip().upper(), name=form["name"].strip(),
                      postal_code=form["postal_code"].strip(), city=form["city"].strip(),
                      notes=form["notes"].strip(), separate_totals=bool(form.get("separate_totals")))
    if form["exp_category"] or form["exp_e3"]:
        ded = {"ΝΑΙ": True, "ΌΧΙ": False}.get(form["exp_deductible"])
        cp.defaults["expense"] = ClassificationDefault("expense", form["exp_category"], form["exp_e3"],
                                                       ded, form["exp_inv_type"])
    if form["inc_category"] or form["inc_e3"]:
        cp.defaults["income"] = ClassificationDefault("income", form["inc_category"], form["inc_e3"], None)
    return cp

def _render_form(request, conn, cfg, tp, form, cp_id, error="", status=200,
                 notice="", notice_warn=False):
    return templates.TemplateResponse(request, "counterparty.html",
                                      _ctx(conn, cfg, tp, form=form, cp_id=cp_id, error=error,
                                           notice=notice, notice_warn=notice_warn),
                                      status_code=status)

@router.get("/counterparties/new", response_class=HTMLResponse)
def new_form(request: Request):
    cfg = load_config()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        empty = _form_of(Counterparty(id=None, taxpayer_id=tp.id, vat=""))
        return _render_form(request, conn, cfg, tp, empty, None)

@router.get("/counterparties/{cp_id}", response_class=HTMLResponse)
def edit_form(request: Request, cp_id: int):
    cfg = load_config()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        cp = get_counterparty(conn, cp_id)
        if cp is None or cp.taxpayer_id != tp.id:
            return HTMLResponse("Άγνωστος αντισυμβαλλόμενος.", status_code=404)
        return _render_form(request, conn, cfg, tp, _form_of(cp), cp_id)

async def _read_form(request: Request) -> dict:
    form = {k: (v if isinstance(v, str) else "") for k, v in (await request.form()).items()}
    for k in ("vat", "country", "name", "postal_code", "city", "notes", "exp_category", "exp_e3",
              "exp_deductible", "exp_inv_type", "inc_category", "inc_e3"):
        form.setdefault(k, "")
    return form

def _not_ours(conn, tp, cp_id: int | None) -> bool:
    return cp_id is not None and (get_counterparty(conn, cp_id) or Counterparty(None, -1, "")).taxpayer_id != tp.id

_FIELD_LABELS = {"name": "επωνυμία", "postal_code": "ΤΚ", "city": "πόλη"}

def _vies_notice(r, filled: list[str]) -> tuple[str, bool]:
    if not r.valid:
        return "Ο ΑΦΜ δεν βρέθηκε στο VIES.", True
    if not r.name:
        return "Ο ΑΦΜ είναι έγκυρος στο VIES, αλλά η χώρα του δεν δίνει επωνυμία και διεύθυνση.", True
    if not filled:
        return f"Το VIES βρήκε «{r.name}»· τα πεδία είχαν ήδη τιμές και δεν άλλαξαν.", False
    return ("Από VIES: συμπληρώθηκαν " + ", ".join(_FIELD_LABELS[k] for k in filled)
            + ". Έλεγξε και πάτα Αποθήκευση."), False

async def _vies_form(request: Request, cp_id: int | None):
    """Γεμίζει μόνο τα κενά πεδία της φόρμας και την ξαναδείχνει· δεν αποθηκεύει τίποτα."""
    cfg = load_config()
    form = await _read_form(request)
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        if _not_ours(conn, tp, cp_id):
            return HTMLResponse("Άγνωστος αντισυμβαλλόμενος.", status_code=404)
        if not form["vat"].strip():
            return _render_form(request, conn, cfg, tp, form, cp_id,
                                notice="Συμπλήρωσε πρώτα τον ΑΦΜ.", notice_warn=True)
        try:
            r = vies_lookup(form["country"].strip().upper() or "GR", form["vat"].strip())
        except ViesError as e:
            return _render_form(request, conn, cfg, tp, form, cp_id, notice=str(e), notice_warn=True)
        notice, warn = _vies_notice(r, fill_empty(form, r))
        return _render_form(request, conn, cfg, tp, form, cp_id, notice=notice, notice_warn=warn)

# Πριν από τα /counterparties/{cp_id}: αλλιώς το «vies» θα διαβαζόταν ως cp_id.
@router.post("/counterparties/vies", response_class=HTMLResponse)
async def vies_new(request: Request):
    return await _vies_form(request, None)

@router.post("/counterparties/vies-fill", response_class=HTMLResponse)
def vies_fill(request: Request):
    """Για κάθε αντισυμβαλλόμενο χωρίς όνομα: ρωτά το VIES και αποθηκεύει μόνο τα κενά πεδία."""
    cfg = load_config()
    filled, missing, failed = 0, [], []
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        nameless = [r["cp"] for r in list_counterparties(conn, tp.id) if not r["cp"].name]
        for cp in nameless:
            try:
                r = vies_lookup(cp.country, cp.vat)
            except ViesError as e:
                failed.append((cp.vat, str(e))); continue
            form = _form_of(cp)
            fill_empty(form, r)
            if not form["name"]:
                missing.append(cp.vat); continue
            try:
                save_counterparty(conn, _cp_of(form, tp.id, cp.id)); conn.commit()
                filled += 1
            except CounterpartyError as e:
                conn.rollback(); failed.append((cp.vat, str(e)))
        ctx = _list_ctx(conn, cfg, tp, saved=None, vies={
            "filled": filled, "total": len(nameless), "missing": missing, "failed": failed})
    return templates.TemplateResponse(request, "counterparties.html", ctx)

@router.post("/counterparties/{cp_id}/vies", response_class=HTMLResponse)
async def vies_edit(request: Request, cp_id: int):
    return await _vies_form(request, cp_id)

async def _save(request: Request, cp_id: int | None):
    cfg = load_config()
    form = await _read_form(request)
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        if _not_ours(conn, tp, cp_id):
            return HTMLResponse("Άγνωστος αντισυμβαλλόμενος.", status_code=404)
        cp = _cp_of(form, tp.id, cp_id)
        try:
            new_id = save_counterparty(conn, cp)
            # Κενά πεδία προεπιλογής σημαίνουν «καμία προεπιλογή»: η υπάρχουσα σβήνει.
            for direction in ("expense", "income"):
                if direction not in cp.defaults:
                    conn.execute("delete from classification_default where counterparty_id = %s "
                                 "and direction = %s", (new_id, direction))
        except CounterpartyError as e:
            conn.rollback()
            return _render_form(request, conn, cfg, tp, form, cp_id, str(e), 400)
    target = f"/counterparties/{new_id}" if cp_id is None else f"/counterparties?saved={new_id}"
    return RedirectResponse(target, status_code=303)

@router.post("/counterparties")
async def create(request: Request):
    return await _save(request, None)

@router.post("/counterparties/{cp_id}")
async def update(request: Request, cp_id: int):
    return await _save(request, cp_id)
