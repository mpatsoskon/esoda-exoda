# ABOUTME: FastAPI routes χαρακτηρισμού εξόδων: οθόνη μήνα (GET /classify),
# ABOUTME: προεπισκόπηση (POST /classify/preview) και υποβολή (POST /classify/send).
import re
import http.client
import xml.etree.ElementTree as ET
from urllib.error import HTTPError
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from ..books_query import deductible_flag
from ..checks import BLOCK, classification_findings
from ..config import load_config
from ..counterparties import CounterpartyError, ensure_counterparty, find_by_vat, save_default
from ..db import connect
from ..export import build_workbook
from ..invoices import counterparty_names, current_expense_lines, received_docs_of_month
from ..refresh import refresh
from ..submissions import record_classification_submissions
from ..taxpayers import current_taxpayer
from ..classify import (ClassifyError, Selection, build_classification_documents,
                        e3_amount, parse_classification_summary, vat_objects)
from .. import mydata_client
from ..mydata_client import send_expenses_classification
from .templating import templates, base_context

router = APIRouter()

_PERIOD = re.compile(r"\d{4}-\d{2}")

def _proposal(conn, tp, doc):
    """Πρόταση από το default του αντισυμβαλλόμενου. (None, None) όταν δεν υπάρχει —
    τότε η οθόνη δεν προτείνει, δεν μαντεύει."""
    cp = find_by_vat(conn, tp.id, doc.issuer_vat)
    d = cp.defaults.get("expense") if cp else None
    return (d.e3_code, d.category_code) if d else (None, None)

def _entry(conn, tp, doc, names, current=None):
    """Μία γραμμή για το template. Η επιλογή των προεπιλεγμένων κωδικών μένει εδώ:
    ό,τι ΙΣΧΥΕΙ σήμερα στην ΑΑΔΕ υπερισχύει της πρότασης του default.

    name: κενό όταν λείπει η επωνυμία — στο RequestDocs λείπει από 45 στα 66, και
    το template το λέει ρητά αντί να επαναλάβει το ΑΦΜ σε δεύτερη στήλη."""
    e3, cat = _proposal(conn, tp, doc)
    if current:
        e3, cat = current[0].e3_type or e3, current[0].category or cat
    return {"doc": doc, "name": names.get(doc.issuer_vat, ""),
            "e3": e3, "category": cat, "current": current or []}


def _out_of_scope(doc) -> str | None:
    """Επιστρέφει τον λόγο εξαίρεσης ή None. Τα καύσιμα ΔΕΝ εξαιρούνται πλέον —
    πάνε από την per-line διαδρομή."""
    if doc.inv_type == "1.5":
        return "τύπος 1.5"
    if not (doc.inv_type.startswith("1.") or doc.inv_type.startswith("2.")):
        return f"τύπος {doc.inv_type}"
    return None

@router.get("/classify", response_class=HTMLResponse)
def classify_screen(request: Request, year: int | None = None,
                    month: int | None = None, period: str = ""):
    """Το period (YYYY-MM) είναι ό,τι στέλνει το input[type=month] της αρχικής. Το
    year/month μένει η κανονική μορφή του URL — είναι αυτό που κρατούν οι σύνδεσμοι
    και τα κρυφά πεδία της προεπισκόπησης."""
    cfg = load_config()
    if period and _PERIOD.fullmatch(period.strip()):
        year, month = (int(x) for x in period.strip().split("-"))
    if year is None or month is None:
        return JSONResponse(
            {"error": "Δώσε έτος και μήνα, π.χ. /classify?year=2026&month=7."},
            status_code=400)
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        all_docs = received_docs_of_month(conn, tp.id, year, month)
        # Η κατάσταση χαρακτηρισμού ΔΕΝ έρχεται από το RequestDocs — η λίστα
        # expensesClassificationsDoc του §6.2 δεν επιστρέφεται ποτέ. Ζει στο RequestE3Info,
        # που η ανανέωση έχει αποθηκεύσει ως snapshots.
        already = current_expense_lines(conn, tp.id, [d.mark for d in all_docs])
        names = counterparty_names(conn, tp.id)
        # Παραστατικά του μήνα που δεν έχουν εμάς ως λήπτη πάνε στην ομάδα «Άλλος
        # λήπτης» αντί να εξαφανίζονται σιωπηλά: ένα έξοδο που δεν φαίνεται πουθενά
        # είναι έξοδο που δεν χαρακτηρίζεται ποτέ, και κανείς δεν το μαθαίνει.
        mine = [d for d in all_docs if d.counterpart_vat == tp.afm]
        other_recipient = [d for d in all_docs if d.counterpart_vat != tp.afm]
        unclassified = [d for d in mine if not _out_of_scope(d) and d.mark not in already]
        classified = [d for d in mine if not _out_of_scope(d) and d.mark in already]
        skipped = [d for d in mine if _out_of_scope(d)]
        # Τα καύσιμα μένουν στις δύο πρώτες ομάδες: χαρακτηρίζονται ανά γραμμή.
        ctx = {**base_context(conn, cfg, tp, "classify", year, month),
               "unclassified": [_entry(conn, tp, d, names) for d in unclassified],
               "classified": [_entry(conn, tp, d, names, already[d.mark]) for d in classified],
               "skipped": [{"doc": d, "name": names.get(d.issuer_vat, ""),
                            "reason": _out_of_scope(d)} for d in skipped],
               "other_recipient": [{"doc": d, "name": names.get(d.issuer_vat, "")}
                                   for d in other_recipient]}
    return templates.TemplateResponse(request, "classify.html", ctx)

@router.post("/classify/preview", response_class=HTMLResponse)
async def classify_preview(request: Request):
    cfg = load_config()
    form = await request.form()
    year, month = int(form["year"]), int(form["month"])
    marks = form.getlist("mark")
    if not marks:
        return JSONResponse({"error": "Δεν επιλέχθηκε κανένα παραστατικό."},
                            status_code=400)
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
        by_mark = {d.mark: d for d in received_docs_of_month(conn, tp.id, year, month)}
        missing = [m for m in marks if m not in by_mark]
        if missing:
            return JSONResponse({"error": f"Άγνωστα MARK: {', '.join(missing)}."},
                                status_code=400)
        foreign = [m for m in marks if by_mark[m].counterpart_vat != tp.afm]
        if foreign:
            return JSONResponse(
                {"error": f"Τα MARK {', '.join(foreign)} δεν έχουν εμάς (ΑΦΜ {tp.afm}) ως "
                          "λήπτη — δεν χαρακτηρίζονται εδώ."},
                status_code=400)
        # Ο τίτλος της οθόνης επιβεβαίωσης βγαίνει από το year/month του form: MARK άλλου
        # μήνα θα εμφανιζόταν κάτω από λάθος μήνα, λίγο πριν την αμετάκλητη υποβολή.
        other_month = [m for m in marks
                       if (by_mark[m].date.year, by_mark[m].date.month) != (year, month)]
        if other_month:
            return JSONResponse(
                {"error": f"Τα MARK {', '.join(other_month)} δεν ανήκουν στον "
                          f"{month:02d}/{year}."},
                status_code=400)
        # Ο έλεγχος εύρους πάει εκεί που χτίζεται το XML: το φίλτρο του GET δεν
        # προστατεύει, μόνο κρύβει. Πίσω από τους τύπους 8.4/9.3 κρύβονται τα μεγαλύτερα
        # ποσά, και το build_classification_xml αρνείται μόνο τον τύπο 1.5.
        out_of_scope = [(m, _out_of_scope(by_mark[m])) for m in marks
                        if _out_of_scope(by_mark[m])]
        if out_of_scope:
            listed = ", ".join(f"{m} ({reason})" for m, reason in out_of_scope)
            return JSONResponse(
                {"error": f"Τα MARK {listed} είναι εκτός εύρους αυτής της μεθόδου — "
                          "χαρακτήρισέ τα από το portal."},
                status_code=400)
        pairs = [(by_mark[m], Selection(mark=m, e3_type=form.get(f"e3_{m}", ""),
                                        category=form.get(f"category_{m}", "")))
                 for m in marks]
        findings = []
        for d, s in pairs:
            cp = find_by_vat(conn, tp.id, d.issuer_vat)
            default = cp.defaults.get("expense") if cp else None
            findings += [(d.issuer_vat, f)
                         for f in classification_findings(cfg, s, d.issuer_vat, default)]
        blocks = [f.message for _, f in findings if f.level == BLOCK]
        if blocks:
            return JSONResponse({"error": " ".join(blocks)}, status_code=400)
        try:
            documents = build_classification_documents(pairs)
        except ClassifyError as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        # §4.1.1: η νέα υποβολή ακυρώνει την προηγούμενη. Ό,τι αντικαθίσταται πρέπει να
        # φαίνεται πριν την αμετάκλητη υποβολή.
        current = current_expense_lines(conn, tp.id, marks)
        ctx = base_context(conn, cfg, tp, "preview", year, month)

    def vat_amount(d, s):
        # Ανά γραμμή (καύσιμα) απαγορεύεται πεδίο ΦΠΑ στο XML (σφάλμα 337) — η
        # προεπισκόπηση δεν πρέπει να δείχνει ποσό που δεν θα σταλεί.
        if d.fuel_invoice:
            return None
        return sum(o.vat_amount for o in vat_objects(d, s.category))

    rows = [{"doc": d, "sel": s, "e3_amount": e3_amount(d, s.category),
             "vat": vat_amount(d, s),
             "replaces": current.get(d.mark) or []}
            for d, s in pairs]
    wanted = {v.split("|")[0] for v in form.getlist("remember")}
    # Δύο έγγραφα, δύο POST: ο χρήστης πρέπει να δει και τα δύο πριν την αμετάκλητη
    # υποβολή, με το πλήθος παραστατικών του καθενός. Ο συγκεντρωτικός πίνακας μένει
    # ενιαίος — ο μήνας είναι ένας, ο τρόπος υποβολής είναι λεπτομέρεια του πρωτοκόλλου.
    counts = {True: sum(1 for d, _ in pairs if not d.fuel_invoice),
              False: sum(1 for d, _ in pairs if d.fuel_invoice)}
    titles = {True: "Ανά παραστατικό", False: "Ανά γραμμή, καύσιμα"}
    by_mode = dict(documents)
    return templates.TemplateResponse(request, "preview.html", {
        **ctx, "rows": rows,
        "warnings": [(vat, f) for vat, f in findings if f.level != BLOCK],
        "documents": [{"title": titles[mode], "count": counts[mode], "xml": xml}
                      for mode, xml in documents],
        "xml_per_invoice": by_mode.get(True, ""),
        "xml_per_line": by_mode.get(False, ""),
        "remember": [f"{d.mark}|{d.issuer_vat}|{s.e3_type}|{s.category}"
                     for d, s in pairs if d.mark in wanted]})

_MODE_LABELS = {True: "ανά παραστατικό", False: "ανά γραμμή, καύσιμα"}

# Ένα αίτημα που έφυγε και δεν έδωσε διαβάσιμη απάντηση δεν είναι ούτε επιτυχία ούτε
# αποτυχία: ο χαρακτηρισμός μπορεί να έχει καταχωρηθεί. Το log είναι ό,τι μένει όταν
# κλείσει ο browser, οπότε η άγνοια πρέπει να γραφτεί μέσα του, με MARK και αιτία.
_UNKNOWN = "ΑΓΝΩΣΤΟ"

def _xml_summary(xml: str) -> dict[str, dict]:
    try:
        return parse_classification_summary(xml)
    except ET.ParseError:
        # Η υποβολή έγινε ήδη· ένα XML που δεν διαβάζεται δεν επιτρέπεται να ρίξει
        # το route και να χάσει τα classification_mark.
        return {}

def submit_classifications(cfg, tp, year: int, month: int, xml_per_invoice: str = "",
                           xml_per_line: str = "",
                           remember: list[str] | None = None) -> tuple[dict, int]:
    """Υποβάλλει και επιστρέφει (σώμα, κωδικό κατάστασης). Ζει χωριστά από το route
    ώστε η σημασιολογία των αστοχιών — απομόνωση ανά αίτημα, ΑΓΝΩΣΤΟ, 207/502/503 —
    να ελέγχεται χωρίς HTTP.

    Δύο αιτήματα: το postPerInvoice είναι query parameter, άρα τα καύσιμα (ανά
    γραμμή) δεν χωρούν στο ίδιο POST με τα κανονικά παραστατικά."""
    remember = remember or []
    pending = [(mode, xml) for mode, xml in ((True, xml_per_invoice),
                                             (False, xml_per_line)) if xml.strip()]
    if not pending:
        return {"error": "Δεν στάλθηκε κανένα XML χαρακτηρισμού."}, 400

    # Κάθε αίτημα χειρίζεται χωριστά: αν το πρώτο πετύχει και το δεύτερο αποτύχει, τα
    # classification_mark του πρώτου έχουν ήδη εκδοθεί και είναι αμετάκλητα — δεν
    # επιτρέπεται να χαθούν πίσω από ένα σφάλμα του δεύτερου.
    results, sent_xmls, unknown, send_errors, rate_limited = [], [], [], [], 0
    raw_by_mode, xml_by_mode = {}, {}
    for mode, xml in pending:
        label = _MODE_LABELS[mode]
        try:
            part, raw = send_expenses_classification(xml, per_invoice=mode, env=tp.environment)
        except HTTPError as e:
            if e.code == 429:
                # Ο rate limiter απορρίπτει πριν την επεξεργασία: τίποτα δεν
                # καταχωρήθηκε, και αυτή είναι η μόνη βέβαιη αστοχία.
                rate_limited += 1
                send_errors.append(f"Όριο κλήσεων myDATA — το αίτημα «{label}» δεν "
                                   "στάλθηκε και τίποτα δεν καταχωρήθηκε.")
                continue
            reason = f"HTTP {e.code} ({e.reason})"
        except (OSError, http.client.HTTPException) as e:
            # Η κατηγορία ορίζεται από το ΠΟΤΕ, όχι από το τι: αστοχία μετά την
            # αποστολή του POST. Το urllib τυλίγει σε URLError μόνο τα OSError του
            # h.request(...) — το αίτημα που δεν έφυγε. Ό,τι σκάει στο
            # getresponse()/read() (read timeout, RemoteDisconnected, IncompleteRead,
            # SSLError) φτάνει γυμνό, και είναι ακριβώς η επικίνδυνη περίπτωση: το POST
            # έφυγε. Με timeout=120 και κανένα retry, το read timeout είναι η
            # πιθανότερη αστοχία δικτύου. Το OSError καλύπτει socket, URLError, timeout
            # και SSL· το HTTPException δεν είναι OSError, γι' αυτό μένει χωριστά.
            reason = str(e) or type(e).__name__
        except ET.ParseError as e:
            reason = f"η απάντηση του myDATA δεν διαβάζεται ({e})"
        else:
            raw_by_mode[mode] = raw
            xml_by_mode[mode] = xml
            if part:
                results.extend({**r, "per_invoice": mode} for r in part)
                sent_xmls.append(xml)
                continue
            # Άδειο envelope απάντησης — καμία γραμμή ανά παραστατικό.
            reason = "το myDATA δεν επέστρεψε κανένα αποτέλεσμα ανά παραστατικό"
        send_errors.append(
            f"Το αίτημα «{label}» δεν ολοκληρώθηκε ({reason}). ΔΕΝ γνωρίζουμε αν οι "
            "χαρακτηρισμοί του καταχωρήθηκαν — έλεγξε στο myDATA portal πριν το "
            "ξαναστείλεις, αλλιώς κινδυνεύεις με διπλό χαρακτηρισμό.")
        unknown.append((mode, xml, reason))
    if rate_limited:
        send_errors.append("Ξαναστείλε σε λίγα λεπτά μόνο τα αιτήματα που δεν "
                           "στάλθηκαν, από την οθόνη του μήνα.")

    # Μία καταγραφή που δεν λέει τι χαρακτηρίστηκε και για πόσα δεν διαβάζεται χωρίς
    # σταυρωτή αναφορά. Τα στοιχεία υπάρχουν στα XML που μόλις στάλθηκαν.
    summary = {}
    for xml in sent_xmls:
        summary.update(_xml_summary(xml))
    records = [{**r, **summary.get(r["invoice_mark"], {})} for r in results]
    for mode, xml, reason in unknown:
        marks = _xml_summary(xml)
        if marks:
            records.extend({"invoice_mark": mark, "classification_mark": "",
                            "status": _UNKNOWN, "per_invoice": mode,
                            "errors": [{"code": "", "message": reason}], **info}
                           for mark, info in marks.items())
        else:
            # Χωρίς MARK το ίχνος είναι φτωχό, αλλά η σιωπή είναι χειρότερη.
            records.append({"invoice_mark": "", "classification_mark": "",
                            "status": _UNKNOWN, "per_invoice": mode,
                            "errors": [{"code": "", "message": reason}]})
    log_error = None
    if records:
        try:
            with connect(cfg) as conn:
                record_classification_submissions(conn, tp.id, year, records,
                                                  xml_by_mode, raw_by_mode)
        except Exception as e:
            # Οι χαρακτηρισμοί υποβλήθηκαν ήδη· τα classification_mark είναι το μόνο
            # χερούλι για έλεγχο, οπότε πρέπει να φτάσουν στον χρήστη έστω κι όταν
            # αποτύχει η καταγραφή.
            log_error = (f"Η υποβολή έγινε αλλά απέτυχε η καταγραφή στη βάση: {e}. "
                         "Σημείωσε τα classification_mark χειρόγραφα.")

    if not results:
        # Κανένα αίτημα δεν έφερε αποτέλεσμα ανά παραστατικό: δεν υπάρχει τίποτα να
        # ανανεωθεί ούτε να θυμηθεί.
        error = " ".join(send_errors + ([log_error] if log_error else []))
        return {"error": error}, 503 if rate_limited == len(pending) else 502

    # Ένα "Success" χωρίς classificationMark δεν είναι επιτυχία — το myDATA δεν
    # έδωσε αναγνωριστικό, οπότε ο χαρακτηρισμός δεν έχει επαληθεύσιμο χερούλι.
    succeeded = [{"invoice_mark": r["invoice_mark"],
                  "classification_mark": r["classification_mark"]}
                 for r in results if r["status"] == "Success" and r["classification_mark"]]
    failed = [r for r in results if r["status"] != "Success"]
    unclear = [r for r in results
              if r["status"] == "Success" and not r["classification_mark"]]
    body = {"succeeded": succeeded, "failed": failed, "unclear": unclear}
    if send_errors:
        body["send_errors"] = send_errors
    if log_error:
        body["log_error"] = log_error
    ok_marks = {s["invoice_mark"] for s in succeeded}

    warnings = []
    if unclear:
        marks = ", ".join(r["invoice_mark"] for r in unclear)
        warnings.append(
            "Η υποβολή φαίνεται πετυχημένη αλλά το myDATA δεν επέστρεψε "
            f"classification_mark για: {marks}. Έλεγξε στο myDATA portal.")

    # «Θυμήσου για αυτόν τον ΑΦΜ»: μόνο για όσα πέτυχαν πραγματικά. Το CounterpartyError
    # είναι προειδοποίηση, όχι σφάλμα — ο χαρακτηρισμός έχει ήδη υποβληθεί.
    for item in remember:
        parts = item.split("|")
        if len(parts) != 4:
            warnings.append(f"Αγνοήθηκε άκυρη τιμή «θυμήσου»: {item}")
            continue
        mark, afm, e3_code, cat_code = parts
        if mark not in ok_marks:
            continue
        try:
            with connect(cfg) as conn:
                cid = ensure_counterparty(conn, tp.id, afm)
                save_default(conn, cid, "expense", cat_code, e3_code,
                            deductible_flag(cat_code) == "ΝΑΙ")
        except CounterpartyError as e:
            warnings.append(str(e))
    if warnings:
        body["warnings"] = warnings

    try:
        with connect(cfg) as conn:
            refresh(conn, tp, year, month)
            body["synola"] = build_workbook(conn, cfg, tp, year)[1]
    except Exception as e:
        body["refresh_error"] = (
            f"Οι χαρακτηρισμοί υποβλήθηκαν ({len(succeeded)} επιτυχίες) αλλά απέτυχε "
            f"η ανανέωση των βιβλίων: {e}. Πάτα «Ανανέωση» χειροκίνητα.")
        return body, 207
    if log_error or send_errors:
        return body, 207
    return body, 200

@router.post("/classify/send", response_class=HTMLResponse)
def classify_send(request: Request, year: int = Form(...), month: int = Form(...),
                  xml_per_invoice: str = Form(default=""),
                  xml_per_line: str = Form(default=""),
                  remember: list[str] = Form(default=[])):
    cfg = load_config()
    with connect(cfg) as conn:
        tp = current_taxpayer(conn)
    body, status = submit_classifications(cfg, tp, year, month, xml_per_invoice,
                                          xml_per_line, remember)
    with connect(cfg) as conn:
        ctx = base_context(conn, cfg, tp, "sent", year, month)
    return templates.TemplateResponse(request, "sent.html", {**ctx, "r": body},
                                      status_code=status)
