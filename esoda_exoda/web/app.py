# ABOUTME: FastAPI local UI: επιλογή έτους και ανανέωση βιβλίων από myDATA.
# ABOUTME: GET / και POST /refresh για τα βιβλία· /transmit* για διαβίβαση αυτο-δηλούμενων.
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from .templating import templates, base_context
from ..config import load_config
from ..counterparties import foreign_suppliers
from ..db import DbUnavailable, connect, migrate
from ..taxpayers import TaxpayerError, current_taxpayer
from ..fetches import has_fetched
from ..invoices import self_declared_of_year, self_declared_since
from ..refresh import refresh
from ..books_query import book_rows, flagged_afms, month_overview
from ..export import build_workbook
from ..checks import BLOCK, HISTORY_WINDOW, transmission_findings
from ..submissions import list_invoice_submissions, record_invoice_submission
from .. import mydata_client
from ..mydata_client import send_invoices
from ..transmit import (Entry, TransmitError, build_xml, build_xml_14, next_aa,
                        notional_vat, parse_amount, parse_entry_summary,
                        parse_issue_date)
from .classify_routes import router as classify_router
from .counterparty_routes import router as counterparty_router

_HERE = Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app):
    # Άδεια αλλά προσβάσιμη βάση → UndefinedTable 500 χωρίς αυτό. Το TestClient(app) χωρίς
    # `with` ΔΕΝ τρέχει startup, άρα τα tests δεν επηρεάζονται. Αν η βάση είναι κάτω, την
    # αναλαμβάνει η db_down.html στο request — δεν εμποδίζουμε το ξεκίνημα.
    try:
        with connect(load_config()) as conn:
            migrate(conn)
    except DbUnavailable:
        pass
    yield

app = FastAPI(title="ΕΣΟΔΑ-ΕΞΟΔΑ myDATA", lifespan=lifespan)
app.include_router(classify_router)
app.include_router(counterparty_router)
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")

@app.exception_handler(DbUnavailable)
@app.exception_handler(TaxpayerError)
def db_down(request: Request, exc: Exception):
    today = date.today()
    return templates.TemplateResponse(request, "db_down.html", {
        "cfg": load_config(), "taxpayer": None, "screen": "", "year": today.year,
        "month": today.month, "last": None, "error": str(exc)}, status_code=503)

@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    cfg = load_config(); today = date.today()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        ctx = base_context(conn, cfg, tp, "index", today.year, today.month)
        transmissions = list_invoice_submissions(conn, tp.id)
        months = month_overview(conn, cfg, tp, today.year)
    return templates.TemplateResponse(request, "index.html", {
        **ctx, "transmissions": transmissions, "months": months})

def refresh_books(cfg, tp, year: int, month: int | None = None) -> tuple[dict, int]:
    """Ανανεώνει τα βιβλία και επιστρέφει (σώμα, κωδικό). Μόνο διάβασμα από την ΑΑΔΕ. Όλο
    το γράψιμο σε μία συναλλαγή: ένα 429 στη μέση αφήνει τη βάση όπως ήταν."""
    try:
        with connect(cfg) as conn:
            stats = refresh(conn, tp, year, month)
            _, summary = build_workbook(conn, cfg, tp, year)
            income, expenses = book_rows(conn, cfg, tp, year)
    except HTTPError as e:
        if e.code != 429:
            raise
        return {"error": "Όριο κλήσεων myDATA — δοκίμασε ξανά σε λίγα λεπτά."}, 503
    months = {}
    for r in income:
        months.setdefault(r.date.month, {"income": 0, "expenses": 0})["income"] += 1
    for r in expenses:
        months.setdefault(r.date.month, {"income": 0, "expenses": 0})["expenses"] += 1
    return {**stats, "synola": summary, "flagged": flagged_afms(income, expenses), "months": months}, 200

@app.post("/refresh", response_class=HTMLResponse)
def refresh_route(request: Request, year: int = Form(...), month: str = Form("")):
    cfg = load_config()
    m = int(month) if month.strip() else None
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
    body, status = refresh_books(cfg, tp, year, m)
    with connect(cfg) as conn:
        ctx = base_context(conn, cfg, tp, "index", year, m or date.today().month)
    return templates.TemplateResponse(request, "refreshed.html", {**ctx, "r": body},
                                      status_code=status)

@app.get("/export/{year}.xlsx")
def export_year(year: int, month: int | None = None):
    cfg = load_config()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        data, _ = build_workbook(conn, cfg, tp, year, month)
    name = f"{year}.xlsx" if month is None else f"{year}-{month:02d}.xlsx"
    return Response(data, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})

def _transmit_context(conn, cfg, tp, form, error="", status=200):
    today = date.today()
    return {**base_context(conn, cfg, tp, "transmit", today.year, today.month),
            "suppliers": foreign_suppliers(conn, tp.id), "today": today.strftime("%d-%m-%Y"),
            "form": form, "error": error}

@app.get("/transmit", response_class=HTMLResponse)
def transmit_form(request: Request):
    cfg = load_config()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        ctx = _transmit_context(conn, cfg, tp, {})
    return templates.TemplateResponse(request, "transmit.html", ctx)

def _transmit_form_again(request, cfg, tp, error, form):
    """Άρνηση χωρίς να χαθεί ό,τι πληκτρολογήθηκε."""
    with connect(cfg) as conn:
        ctx = _transmit_context(conn, cfg, tp, form, error)
    return templates.TemplateResponse(request, "transmit.html", ctx, status_code=400)

def _next_aa(conn, tp, inv_type: str, year: int) -> int | None:
    """None όταν δεν έχει γίνει ποτέ ανανέωση: ένα ΑΑ από άδεια βάση θα ήταν πάντα 1 και
    θα συγκρουόταν με ό,τι έχει ήδη σταλεί."""
    if not has_fetched(conn, tp.id, "RequestTransmittedDocs"):
        return None
    return next_aa(self_declared_of_year(conn, tp.id, year), inv_type, year)

_REFRESH_FIRST = ("Κάνε πρώτα Ανανέωση βιβλίων, ώστε το επόμενο ΑΑ να βγει από ό,τι έχει "
                  "σταλεί.")

def _transmission_findings(cfg, tp, *, inv_type, series, aa, issue_date, net, supplier=None):
    # Από 365 ημέρες πριν: καλύπτει και το ίδιο έτος (διπλή διαβίβαση) και το παράθυρο
    # σύγκρισης ποσού, αφού η 1η Ιανουαρίου δεν απέχει ποτέ πάνω από 365 ημέρες.
    with connect(cfg) as conn:
        history = self_declared_since(conn, tp.id, issue_date - HISTORY_WINDOW)
    return transmission_findings(cfg, inv_type=inv_type, series=series, aa=aa,
                                 issue_date=issue_date, net=net, history=history,
                                 today=date.today(), supplier=supplier)

@app.post("/transmit/preview", response_class=HTMLResponse)
def transmit_preview(request: Request, preset: str = Form(...),
                     issue_date: str = Form(...), net: str = Form(...),
                     series: str = Form(""), aa: str = Form("")):
    cfg = load_config()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
    p = cfg.presets[preset]
    form = {"preset": preset, "issue_date": issue_date, "net": net,
            "series": series, "aa": aa}
    try:
        d = parse_issue_date(issue_date)
        net_value = parse_amount(net)
    except TransmitError as e:
        return _transmit_form_again(request, cfg, tp, str(e), form)
    aa_value = aa.strip()
    if not aa_value:
        # Στα 13.x το ΑΑ είναι ο αριθμός λογαριασμού του παρόχου, όχι δική μας
        # αρίθμηση: το next_aa θα επινοούσε αριθμό σε αμετάκλητη διαβίβαση. Η
        # άρνηση προηγείται της κλήσης στο myDATA, για να μη χαθεί κλήση.
        if p["inv_type"].startswith("13."):
            return _transmit_form_again(
                request, cfg, tp,
                "Συμπλήρωσε το ΑΑ: στα κοινόχρηστα είναι ο αριθμός λογαριασμού του "
                "παρόχου και δεν παράγεται από αρίθμηση.", form)
        with connect(cfg) as conn:
            n = _next_aa(conn, tp, p["inv_type"], d.year)
        if n is None:
            return _transmit_form_again(request, cfg, tp, _REFRESH_FIRST, form)
        aa_value = str(n)
    else:
        # Η διπλή διαβίβαση ελέγχεται απέναντι σε ό,τι έφερε η ανανέωση. Χωρίς καμία
        # ανανέωση, ένα ΑΑ που έχει ήδη σταλεί θα περνούσε ως καινούργιο.
        with connect(cfg) as conn:
            fetched = has_fetched(conn, tp.id, "RequestTransmittedDocs")
        if not fetched:
            return _transmit_form_again(request, cfg, tp, _REFRESH_FIRST, form)
    entry = Entry(inv_type=p["inv_type"], series=series.strip() or "0",
                  aa=aa_value,
                  issue_date=d, net=net_value, vat=0.0,
                  vat_category=p["vat_category"],
                  e3_type=p["e3_type"], category=p["category"])
    try:
        xml = build_xml(entry, tp.afm, tp.postal_code, tp.city)
    except TransmitError as e:
        return _transmit_form_again(request, cfg, tp, str(e), form)
    findings = _transmission_findings(cfg, tp, inv_type=entry.inv_type, series=entry.series,
                                      aa=entry.aa, issue_date=d, net=entry.net)
    blocks = [f.message for f in findings if f.level == BLOCK]
    if blocks:
        return _transmit_form_again(request, cfg, tp, " ".join(blocks), form)
    with connect(cfg) as conn:
        ctx = base_context(conn, cfg, tp, "transmit", d.year, d.month)
    return templates.TemplateResponse(request, "transmit_preview.html", {
        **ctx, "xml": xml, "warnings": [f for f in findings if f.level != BLOCK],
        "label": cfg.type_labels.get(entry.inv_type, entry.inv_type),
        "issue_date": d, "net": entry.net, "series": entry.series, "aa": entry.aa,
        "deductible": entry.category != "category2_5", "vat": None, "supplier": None,
        "vat_category": entry.vat_category})

@app.post("/transmit/foreign/preview", response_class=HTMLResponse)
def foreign_preview(request: Request, supplier: str = Form(...),
                    issue_date: str = Form(...), net: str = Form(...)):
    cfg = load_config()
    form = {"supplier": supplier, "g_issue_date": issue_date, "g_net": net}
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        sid = int(supplier) if supplier.isdigit() else -1
        sup = dict(foreign_suppliers(conn, tp.id)).get(sid)
    if sup is None:
        return _transmit_form_again(request, cfg, tp,
                                    f"Άγνωστος προμηθευτής «{supplier}».", form)
    try:
        d = parse_issue_date(issue_date)
        # Στρογγυλοποίηση εδώ, ώστε το πλασματικό ΦΠΑ και το σύνολο να υπολογιστούν
        # πάνω στην ίδια καθαρή αξία που διαβιβάζεται με δύο δεκαδικά.
        net_value = round(parse_amount(net), 2)
    except TransmitError as e:
        return _transmit_form_again(request, cfg, tp, str(e), form)
    with connect(cfg) as conn:
        n = _next_aa(conn, tp, sup.inv_type, d.year)
    if n is None:
        return _transmit_form_again(request, cfg, tp, _REFRESH_FIRST, form)
    aa = str(n)
    xml = build_xml_14(sup, d, net_value, aa, tp.afm, tp.postal_code, tp.city)
    findings = _transmission_findings(cfg, tp, inv_type=sup.inv_type, series="0", aa=aa,
                                      issue_date=d, net=net_value, supplier=sup)
    blocks = [f.message for f in findings if f.level == BLOCK]
    if blocks:
        return _transmit_form_again(request, cfg, tp, " ".join(blocks), form)
    with connect(cfg) as conn:
        ctx = base_context(conn, cfg, tp, "transmit", d.year, d.month)
    return templates.TemplateResponse(request, "transmit_preview.html", {
        **ctx, "xml": xml, "warnings": [f for f in findings if f.level != BLOCK],
        "label": f"{sup.inv_type} — {sup.name} ({sup.country})",
        "issue_date": d, "net": net_value, "series": "0", "aa": aa,
        "deductible": True, "vat": notional_vat(net_value), "supplier": sup,
        "vat_category": None})

def submit_invoice(cfg, tp, xml: str, year: int) -> tuple[dict, int]:
    """Διαβιβάζει και επιστρέφει (σώμα, κωδικό κατάστασης). Ζει χωριστά από το route
    ώστε η σημασιολογία μετά την αμετάκλητη αποστολή να ελέγχεται χωρίς HTTP."""
    try:
        result = send_invoices(xml, env=tp.environment)
    except TransmitError as e:
        return {"error": str(e)}, 400
    except HTTPError as e:
        if e.code != 429:
            raise
        return {"error": "Όριο κλήσεων myDATA — δοκίμασε ξανά σε λίγα λεπτά."}, 503
    entry = parse_entry_summary(xml)
    try:
        # Δική της συναλλαγή: το MARK είναι αμετάκλητο και πρέπει να γραφτεί πριν από
        # οτιδήποτε άλλο μπορεί να αποτύχει.
        with connect(cfg) as conn:
            record_invoice_submission(conn, tp.id, entry, result["mark"], result["uid"],
                                      xml, result.get("response_xml", ""))
    except Exception as e:
        return {"mark": result["mark"], "uid": result["uid"],
                "log_error": f"Η διαβίβαση πέτυχε (MARK {result['mark']}) αλλά απέτυχε η "
                             f"καταγραφή στη βάση: {e}. Σημείωσέ το χειρόγραφα."}, 207
    try:
        month = date.fromisoformat(entry["issue_date"]).month if entry["issue_date"] else None
        with connect(cfg) as conn:
            refresh(conn, tp, year, month)
            _, summary = build_workbook(conn, cfg, tp, year)
    except Exception as e:
        return {"mark": result["mark"], "uid": result["uid"],
                "refresh_error": f"Η διαβίβαση πέτυχε (MARK {result['mark']}) αλλά απέτυχε η "
                                 f"ανανέωση των βιβλίων: {e}. Τρέξε ξανά την Ανανέωση."}, 207
    return {"mark": result["mark"], "uid": result["uid"], "synola": summary,
            "note": f"Σημείωσε το MARK {result['mark']} — τυχόν ακύρωση γίνεται μόνο από το "
                    "myDATA portal, με βάση αυτό το MARK."}, 200

@app.post("/transmit/send", response_class=HTMLResponse)
def transmit_send(request: Request, xml: str = Form(...), year: int = Form(...)):
    cfg = load_config()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
    body, status = submit_invoice(cfg, tp, xml, year)
    with connect(cfg) as conn:
        ctx = base_context(conn, cfg, tp, "transmit", year, date.today().month)
    return templates.TemplateResponse(request, "transmit_sent.html", {
        **ctx, "r": body}, status_code=status)
