# ABOUTME: Test της orchestration με injected fetchers (καμία κλήση δικτύου).
# ABOUTME: Επιβεβαιώνει δημιουργία μηνιαίων + ΣΥΝΟΛΑ, τα σύνολα, και το endpoint /refresh.
import http.client
import io
import re
import ssl
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
import openpyxl
import pytest
from fastapi.testclient import TestClient
from esoda_exoda.config import Config
from esoda_exoda.web.app import app

def _wire(monkeypatch, db_cfg):
    from esoda_exoda.web import app as web_app
    monkeypatch.setattr(web_app, "load_config", lambda: db_cfg)

def _fixture_fetch(fixtures_dir):
    files = {"RequestMyIncome": "mydata_income_2025.xml", "RequestMyExpenses": "mydata_expenses_2025.xml",
             "RequestTransmittedDocs": "mydata_transmitted_sample.xml", "RequestDocs": "mydata_received_sample.xml",
             "RequestE3Info": "mydata_e3_info_2026_07.xml", "RequestVatInfo": "mydata_vat_info_2026_07.xml"}
    return lambda m, a, b, *, env: (fixtures_dir / files[m]).read_text(encoding="utf-8")

def test_index_χωρίς_βάση_δείχνει_οδηγία_όχι_500(monkeypatch):
    from esoda_exoda.web import app as web_app
    monkeypatch.setattr(web_app, "load_config",
                        lambda: Config(database_url="postgresql://x:y@127.0.0.1:1/nope?connect_timeout=1"))
    resp = TestClient(app).get("/")
    assert resp.status_code == 503 and "docker compose up" in resp.text

def test_index_χωρίς_φορολογούμενο_λέει_setup(monkeypatch, db, db_cfg):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).get("/")
    assert resp.status_code == 503 and "esoda-exoda setup" in resp.text

def test_index_δείχνει_ΑΦΜ_από_τη_βάση_και_link_αντισυμβαλλόμενων(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    html = TestClient(app).get("/").text
    assert "123456783" in html and 'href="/counterparties"' in html and "ΑΛΦΑΠΟΛΗ" in html

def test_index_δείχνει_διαβιβάσεις_και_μήνες(monkeypatch, db, db_cfg, taxpayer):
    from esoda_exoda.submissions import record_invoice_submission
    from esoda_exoda.fetches import store_fetch
    record_invoice_submission(db, taxpayer.id, {"inv_type": "13.3", "series": "1", "aa": "2", "issue_date": "2026-08-01",
                              "net": 12.0, "issuer_vat": "", "issuer_name": ""}, "900000000001054", "U", "", "")
    store_fetch(db, taxpayer.id, "RequestMyExpenses", date(2026, 7, 1), date(2026, 7, 31), "")
    db.commit()
    _wire(monkeypatch, db_cfg)
    html = TestClient(app).get("/").text
    assert "900000000001054" in html and "07/2026" in html and 'href="/export/2026.xlsx"' in html

def test_refresh_μήνα_γράφει_στη_βάση_και_δείχνει_σύνοψη(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import app as web_app
    _wire(monkeypatch, db_cfg)
    monkeypatch.setattr(web_app.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    resp = TestClient(app).post("/refresh", data={"year": "2026", "month": "7"})
    assert resp.status_code == 200
    assert db.execute("select count(*) from mydata_fetch").fetchone()[0] == 6
    assert "ΤΙΠΟΤΑ ΔΕΝ ΣΤΑΛΘΗΚΕ" in resp.text and "01/07/2026" in resp.text

def test_refresh_έτους_χωρίς_μήνα(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import app as web_app
    _wire(monkeypatch, db_cfg)
    seen = []
    fx = _fixture_fetch(fixtures_dir)
    monkeypatch.setattr(web_app.mydata_client, "fetch_xml", lambda m, a, b, *, env: (seen.append((a, b, env)), fx(m, a, b, env=env))[1])
    TestClient(app).post("/refresh", data={"year": "2026", "month": ""})
    assert seen[0] == ("01/01/2026", "31/12/2026", "dev")

def test_refresh_429_κάνει_rollback_και_λέει_πρόταση(monkeypatch, db, db_cfg, taxpayer):
    from esoda_exoda.web import app as web_app
    _wire(monkeypatch, db_cfg)
    def boom(m, a, b, *, env):
        raise HTTPError("u", 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(web_app.mydata_client, "fetch_xml", boom)
    resp = TestClient(app).post("/refresh", data={"year": "2026", "month": "7"})
    assert resp.status_code == 503 and "Όριο κλήσεων" in resp.text
    assert db.execute("select count(*) from mydata_fetch").fetchone()[0] == 0

def test_refresh_αναφέρει_ΑΦΜ_χωρίς_χαρακτηρισμό(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import app as web_app
    _wire(monkeypatch, db_cfg)
    monkeypatch.setattr(web_app.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    html = TestClient(app).post("/refresh", data={"year": "2025", "month": ""}).text
    assert "χωρίς χαρακτηρισμό" in html and "/counterparties" in html

def test_export_κατεβάζει_xlsx(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).get("/export/2026.xlsx")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert "2026.xlsx" in resp.headers["content-disposition"]
    assert openpyxl.load_workbook(io.BytesIO(resp.content)).sheetnames == ["ΕΣΟΔΑ", "ΕΞΟΔΑ", "Ε3", "ΦΠΑ"]

def test_index_has_year_and_month_form_for_classification(monkeypatch, db, db_cfg, taxpayer):
    """Ο χρήστης δεν πρέπει να επεξεργάζεται URL για να διαλέξει μήνα, και ο μήνας
    δεν είναι σταθερός στον κώδικα: η φόρμα ανοίγει στον τρέχοντα."""
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).get("/")
    form = re.search(r'<form[^>]*action="/classify".*?</form>', resp.text, re.S)
    assert form, "λείπει η φόρμα επιλογής μήνα"
    assert 'name="period"' in form.group(0)
    today = date.today()
    assert f'value="{today.year}-{today.month:02d}"' in form.group(0)

def test_transmit_preview_rejects_ambiguous_amount(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview",
                                data={"preset": "κοινόχρηστα",
                                      "issue_date": "31-03-2026", "net": "1.250"})
    assert resp.status_code == 400
    assert "Αμφίσημο" in _visible(resp.text)

def test_serve_serves_app_via_uvicorn(monkeypatch):
    import uvicorn
    from esoda_exoda import cli
    called = {}
    monkeypatch.setattr(uvicorn, "run", lambda target, **kw: called.update(target=target, **kw))
    cli._serve()
    assert called["target"] == "esoda_exoda.web.app:app"
    assert called["host"] == "127.0.0.1"

def _seed_foreign(db, taxpayer, e3="E3_585_010", category="category2_3"):
    from esoda_exoda.counterparties import Counterparty, ClassificationDefault, save_counterparty
    cp = Counterparty(id=None, taxpayer_id=taxpayer.id, vat="NL999999003B01", country="NL",
                      name="FOREIGN SUPPLIER A B.V.", postal_code="1017", city="Amsterdam")
    cp.defaults["expense"] = ClassificationDefault("expense", category, e3, True, "14.3")
    cid = save_counterparty(db, cp); db.commit()
    return cid

def _seed_transmitted(db, taxpayer, aa="3"):
    from esoda_exoda.fetches import store_fetch
    from esoda_exoda.invoices import upsert_self_declared
    from esoda_exoda.classifications import SelfDeclared
    f = store_fetch(db, taxpayer.id, "RequestTransmittedDocs", None, None, "")
    upsert_self_declared(db, taxpayer.id, SelfDeclared(mark="S", uid="", inv_type="17.2", series="0", aa=aa,
                         date=date(2026, 12, 31), net=1, vat=0, e3_type="E3_587", category="category2_8"), f, None)
    db.commit()

def _refreshed_transmitted(db, taxpayer):
    from esoda_exoda.fetches import store_fetch
    store_fetch(db, taxpayer.id, "RequestTransmittedDocs", None, None, ""); db.commit()

def _seed_13_3(db, taxpayer, aa, d, net):
    from esoda_exoda.fetches import store_fetch
    from esoda_exoda.invoices import upsert_self_declared
    from esoda_exoda.classifications import SelfDeclared
    f = store_fetch(db, taxpayer.id, "RequestTransmittedDocs", None, None, "")
    upsert_self_declared(db, taxpayer.id, SelfDeclared(
        mark=f"S{aa}", uid="", inv_type="13.3", series="123456783", aa=aa, date=d, net=net,
        vat=0, e3_type="E3_585_016", category="category2_3"), f, None)
    db.commit()

# Η σημερινή ημερομηνία δεν πυροδοτεί ποτέ τον έλεγχο ημερομηνίας (T3): δεν είναι μελλοντική
# και είναι στο τρέχον έτος.
_TODAY = date.today()
_TODAY_FORM = _TODAY.strftime("%d-%m-%Y")

def test_transmit_form_lists_presets_and_foreign_from_db(monkeypatch, db, db_cfg, taxpayer):
    cid = _seed_foreign(db, taxpayer); _wire(monkeypatch, db_cfg)
    html = TestClient(app).get("/transmit").text
    assert "κοινόχρηστα" in html and f'value="{cid}"' in html and "FOREIGN SUPPLIER A B.V." in html
    assert 'href="/counterparties/new"' in html and 'action="/suppliers"' not in html

def test_transmit_preview_computes_aa_from_db(monkeypatch, db, db_cfg, taxpayer):
    _seed_transmitted(db, taxpayer, "3"); _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview", data={"preset": "αποσβέσεις", "issue_date": "31-12-2026", "net": "1.250,40"})
    assert resp.status_code == 200 and "&lt;aa&gt;4&lt;/aa&gt;" in resp.text
    assert "χωρίς ΦΠΑ" in resp.text and "εκπίπτει" not in resp.text  # vat_category 8 = χωρίς ΦΠΑ

def test_transmit_preview_χωρίς_ανανέωση_ζητά_ανανέωση(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview", data={"preset": "αποσβέσεις", "issue_date": "31-12-2026", "net": "1"})
    assert resp.status_code == 400 and "Ανανέωση" in resp.text

def test_transmit_preview_refuses_blank_aa_for_13x(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview", data={"preset": "κοινόχρηστα", "issue_date": "01-08-2026", "net": "12"})
    assert resp.status_code == 400 and "αριθμός λογαριασμού" in resp.text

def test_foreign_preview_builds_xml_with_notional_vat(monkeypatch, db, db_cfg, taxpayer):
    cid = _seed_foreign(db, taxpayer); _seed_transmitted(db, taxpayer); _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/foreign/preview", data={"supplier": str(cid), "issue_date": "02-09-2026", "net": "100"})
    assert resp.status_code == 200 and "&lt;vatAmount&gt;24.00&lt;/vatAmount&gt;" in resp.text and "VAT_365" in resp.text

def test_foreign_preview_unknown_supplier_is_400(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/foreign/preview", data={"supplier": "999", "issue_date": "02-09-2026", "net": "1"})
    assert resp.status_code == 400 and "Άγνωστος" in resp.text

def test_transmit_send_γράφει_submission_με_xml_και_ανανεώνει(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import app as web_app
    _wire(monkeypatch, db_cfg)
    xml = '<InvoicesDoc><invoice><invoiceHeader><series>0</series><aa>1</aa><issueDate>2026-12-31</issueDate><invoiceType>17.2</invoiceType></invoiceHeader><invoiceSummary><totalNetValue>1250.40</totalNetValue></invoiceSummary></invoice></InvoicesDoc>'
    envs = []
    monkeypatch.setattr(web_app, "send_invoices",
                        lambda x, *, env: (envs.append(env), {"mark": "M1", "uid": "U1", "response_xml": "<ok/>"})[1])
    monkeypatch.setattr(web_app.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    resp = TestClient(app).post("/transmit/send", data={"xml": xml, "year": "2026"})
    assert resp.status_code == 200 and "M1" in resp.text
    assert envs == ["dev"]
    row = db.execute("select inv_type, aa, request_xml, response_xml from invoice_submission").fetchone()
    assert row == ("17.2", "1", xml, "<ok/>")
    assert db.execute("select count(*) from mydata_fetch").fetchone()[0] == 6

def test_transmit_send_returns_mark_when_refresh_fails(monkeypatch, db, db_cfg, taxpayer):
    from esoda_exoda.web import app as web_app
    _wire(monkeypatch, db_cfg)
    monkeypatch.setattr(web_app, "send_invoices", lambda x, *, env: {"mark": "M1", "uid": "U1", "response_xml": ""})
    def boom(m, a, b, *, env): raise RuntimeError("κάτω")
    monkeypatch.setattr(web_app.mydata_client, "fetch_xml", boom)
    resp = TestClient(app).post("/transmit/send", data={"xml": "<InvoicesDoc/>", "year": "2026"})
    assert resp.status_code == 207 and "M1" in resp.text
    assert db.execute("select count(*) from invoice_submission").fetchone()[0] == 1

def test_transmit_send_writes_nothing_on_error(monkeypatch, db, db_cfg, taxpayer):
    from esoda_exoda.web import app as web_app
    from esoda_exoda.transmit import TransmitError
    _wire(monkeypatch, db_cfg)
    def refuse(x, *, env): raise TransmitError("myDATA ValidationError: κάτι")
    monkeypatch.setattr(web_app, "send_invoices", refuse)
    resp = TestClient(app).post("/transmit/send", data={"xml": "<InvoicesDoc/>", "year": "2026"})
    assert resp.status_code == 400
    assert db.execute("select count(*) from invoice_submission").fetchone()[0] == 0

def test_transmit_send_reports_rate_limit(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    from esoda_exoda.web import app as web_app
    def limited(x, *, env): raise HTTPError("u", 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(web_app, "send_invoices", limited)
    resp = TestClient(app).post("/transmit/send", data={"xml": "<InvoicesDoc/>", "year": "2026"})
    assert resp.status_code == 503 and "Όριο κλήσεων" in resp.text

def test_transmit_preview_uses_given_series_and_aa(monkeypatch, db, db_cfg, taxpayer):
    """Τα προηγούμενα 13.3 δηλώθηκαν με Σειρά=ΑΦΜ και ΑΑ=αριθμό λογαριασμού παρόχου,
    οπότε η φόρμα πρέπει να μπορεί να συνεχίσει την ίδια αρίθμηση."""
    _refreshed_transmitted(db, taxpayer)
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview",
                                data={"preset": "κοινόχρηστα",
                                      "issue_date": "01-08-2026", "net": "12,00",
                                      "series": " 123456783 ", "aa": " 8000000020 "})
    assert resp.status_code == 200
    assert "&lt;series&gt;123456783&lt;/series&gt;" in resp.text
    assert "&lt;aa&gt;8000000020&lt;/aa&gt;" in resp.text
    assert "Σειρά 123456783 / ΑΑ 8000000020" in resp.text

def test_transmit_preview_blank_series_and_aa_keep_defaults(monkeypatch, db, db_cfg, taxpayer):
    """Στις αποσβέσεις (17.2) το ΑΑ είναι δική μας αρίθμηση, οπότε το κενό σημαίνει
    «το επόμενο»."""
    _seed_transmitted(db, taxpayer, "0"); _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview",
                                data={"preset": "αποσβέσεις",
                                      "issue_date": "31-03-2026", "net": "120",
                                      "series": "  ", "aa": ""})
    assert resp.status_code == 200
    assert "&lt;series&gt;0&lt;/series&gt;" in resp.text
    assert "&lt;aa&gt;1&lt;/aa&gt;" in resp.text

def test_transmit_preview_με_χειροκίνητο_ΑΑ_χωρίς_ανανέωση_ζητά_ανανέωση(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview", data={
        "preset": "κοινόχρηστα", "issue_date": _TODAY_FORM, "net": "12,00",
        "series": "123456783", "aa": "8000000020"})
    assert resp.status_code == 400 and "Ανανέωση" in resp.text

def test_transmit_preview_μπλοκάρει_διπλή_διαβίβαση(monkeypatch, db, db_cfg, taxpayer):
    _seed_13_3(db, taxpayer, "8000000010", _TODAY, 12); _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview", data={
        "preset": "κοινόχρηστα", "issue_date": _TODAY_FORM, "net": "36,00",
        "series": "123456783", "aa": " 8000000010 "})
    assert resp.status_code == 400
    assert "Υπάρχει ήδη διαβιβασμένο 13.3" in _visible(resp.text)
    assert "ασυνήθιστη" not in resp.text                  # block: καμία σελίδα αποστολής
    assert 'value=" 8000000010 "' in resp.text            # ό,τι γράφτηκε, δεν χάνεται

def test_transmit_preview_διπλή_17_2_με_κενή_σειρά(monkeypatch, db, db_cfg, taxpayer):
    _seed_transmitted(db, taxpayer, "3"); _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview", data={
        "preset": "αποσβέσεις", "issue_date": "31-12-2026", "net": "1", "series": "", "aa": "3"})
    assert resp.status_code == 400 and "Σειρά 0 / ΑΑ 3" in _visible(resp.text)

def test_transmit_preview_προειδοποιεί_και_ζητά_επιβεβαίωση(monkeypatch, db, db_cfg, taxpayer):
    _seed_13_3(db, taxpayer, "1", _TODAY, 12); _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview", data={
        "preset": "κοινόχρηστα", "issue_date": _TODAY_FORM, "net": "36,00",
        "series": "123456783", "aa": "2"})
    assert resp.status_code == 200
    assert 'class="msg m-warn"' in resp.text and "ασυνήθιστη" in resp.text
    form = re.search(r'<form method="post" action="/transmit/send">.*?</form>', resp.text, re.S).group(0)
    assert 'name="ack" required' in form

def test_transmit_preview_χωρίς_προειδοποίηση_χωρίς_checkbox(monkeypatch, db, db_cfg, taxpayer):
    _seed_13_3(db, taxpayer, "1", _TODAY, 12); _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview", data={
        "preset": "κοινόχρηστα", "issue_date": _TODAY_FORM, "net": "13,00",
        "series": "123456783", "aa": "2"})
    assert resp.status_code == 200
    assert 'name="ack"' not in resp.text and 'class="msg m-warn"' not in resp.text

def test_foreign_preview_προειδοποιεί_για_ε3_ημεδαπής(monkeypatch, db, db_cfg, taxpayer):
    cid = _seed_foreign(db, taxpayer, e3="E3_585_009"); _seed_transmitted(db, taxpayer)
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/foreign/preview", data={
        "supplier": str(cid), "issue_date": _TODAY_FORM, "net": "100"})
    assert resp.status_code == 200
    assert "E3_585_009 (υπηρεσίες ημεδαπής)" in resp.text and 'name="ack" required' in resp.text

def test_foreign_preview_προειδοποιεί_για_πιθανό_διπλότυπο(monkeypatch, db, db_cfg, taxpayer):
    from esoda_exoda.fetches import store_fetch
    from esoda_exoda.invoices import upsert_self_declared
    from esoda_exoda.classifications import SelfDeclared
    cid = _seed_foreign(db, taxpayer)
    f = store_fetch(db, taxpayer.id, "RequestTransmittedDocs", None, None, "")
    upsert_self_declared(db, taxpayer.id, SelfDeclared(
        mark="S14", uid="", inv_type="14.3", series="0", aa="1", date=_TODAY, net=100, vat=0,
        e3_type="E3_585_010", category="category2_3", issuer_vat="NL999999003B01"), f, None)
    db.commit(); _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/foreign/preview", data={
        "supplier": str(cid), "issue_date": _TODAY_FORM, "net": "100"})
    assert resp.status_code == 200
    assert "Υπάρχει ήδη διαβιβασμένο 14.3" in resp.text and "ΑΑ 1)" in resp.text
    form = re.search(r'<form method="post" action="/transmit/send">.*?</form>', resp.text, re.S).group(0)
    assert 'name="ack" required' in form

def test_foreign_preview_μπλοκάρει_κωδικό_εσόδου_προμηθευτή(monkeypatch, db, db_cfg, taxpayer):
    cid = _seed_foreign(db, taxpayer, category="category1_3"); _seed_transmitted(db, taxpayer)
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/foreign/preview", data={
        "supplier": str(cid), "issue_date": _TODAY_FORM, "net": "100"})
    assert resp.status_code == 400 and "κωδικό εσόδου" in _visible(resp.text)

# ── Χαρακτηρισμός (/classify) ──────────────────────────────────────────────
# Κάθε test φορτώνει τα ληφθέντα/χαρακτηρισμούς στη βάση με refresh/add_snapshot,
# ποτέ με monkeypatch fetcher: το route δεν κάνει πια κανένα fetch_* — η
# καμία_κλήση_δικτύου (autouse) θα έσκαγε αν το route έκανε GET στην ΑΑΔΕ.

def _wire_classify(monkeypatch, db_cfg):
    from esoda_exoda.web import classify_routes
    monkeypatch.setattr(classify_routes, "load_config", lambda: db_cfg)

def _seed_july(db, taxpayer, fixtures_dir, with_e3=True):
    from esoda_exoda.refresh import refresh
    fx = _fixture_fetch(fixtures_dir)
    empty = "<RequestedE3Info/>"
    refresh(db, taxpayer, 2026, 7, fetch_xml=lambda m, a, b: (fx(m, a, b, env=taxpayer.environment) if with_e3 or m != "RequestE3Info" else empty))
    db.commit()

def test_classify_screen_groups_by_status(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.counterparties import ensure_counterparty, save_default
    _seed_july(db, taxpayer, fixtures_dir, with_e3=False)
    save_default(db, ensure_counterparty(db, taxpayer.id, "990000155"), "expense", "category2_4", "E3_585_016", True); db.commit()
    _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).get("/classify?year=2026&month=7")
    assert resp.status_code == 200
    assert "ΠΡΟΜΗΘΕΥΤΗΣ Γ ΟΕ" in resp.text          # όνομα από counterparty, γεμισμένο από το RequestDocs
    assert 'value="900000000001047"' in resp.text  # καύσιμα: χαρακτηρίσιμα per-line
    assert "category2_4" in resp.text              # πρόταση από το default του αντισυμβαλλόμενου

def test_classify_screen_δεν_καλεί_την_ΑΑΔΕ(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    # Το autouse fixture σκάει σε κάθε κλήση urllib — αν το route έκανε GET, το test θα έπεφτε.
    assert TestClient(app).get("/classify?year=2026&month=7").status_code == 200

def test_classify_screen_needs_year_and_month(monkeypatch, db_cfg):
    from esoda_exoda.web import classify_routes
    monkeypatch.setattr(classify_routes, "load_config", lambda: db_cfg)
    resp = TestClient(app).get("/classify")
    assert resp.status_code == 400
    assert "μήνα" in resp.json()["error"]

def _screen_with_e3(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, e3_lines=None,
                    mark="900000000001048", issue_date=date(2026, 7, 22)):
    from esoda_exoda.fetches import store_fetch
    from esoda_exoda.invoices import add_snapshot
    _seed_july(db, taxpayer, fixtures_dir, with_e3=False)
    if e3_lines:
        f = store_fetch(db, taxpayer.id, "RequestE3Info", date(2026, 7, 1), date(2026, 7, 31), "")
        add_snapshot(db, taxpayer.id, mark, "e3_info", f, issue_date, lines=e3_lines)
        db.commit()
    _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).get("/classify?year=2026&month=7")
    assert resp.status_code == 200
    return resp.text

_PLACEHOLDER = '<option value="" selected>— διάλεξε —</option>'

def test_dropdown_shows_placeholder_when_there_is_no_proposal(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    html = _screen_with_e3(monkeypatch, db, db_cfg, taxpayer, fixtures_dir)
    assert _PLACEHOLDER in html

def test_dropdown_shows_placeholder_when_the_code_in_force_is_unknown(
        monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Κωδικός εκτός config (π.χ. χαρακτηρισμένο από το portal) δεν πρέπει να αφήνει
    τον browser να υποβάλει το πρώτο option — κωδικό που δεν διάλεξε κανείς."""
    html = _screen_with_e3(monkeypatch, db, db_cfg, taxpayer, fixtures_dir,
                           e3_lines=[("expense", "category2_4", "E3_581_003", 75.0)])
    assert _PLACEHOLDER in html
    assert 'value="E3_585_009" selected' not in html

def test_dropdown_keeps_a_known_code_without_placeholder(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    html = _screen_with_e3(monkeypatch, db, db_cfg, taxpayer, fixtures_dir,
                           e3_lines=[("expense", "category2_4", "E3_585_016", 75.0)])
    classified = _group(html, "Χαρακτηρισμένα", "Εκτός εύρους")
    assert 'value="E3_585_016" selected' in classified

def test_classify_screen_leaves_dropdown_empty_without_proposal(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Χωρίς πρόταση ο browser θα υπέβαλλε το πρώτο option, κωδικό που δεν διάλεξε
    κανείς. Το κενό option ως selected κάνει την υποβολή κενή."""
    html = _screen_with_e3(monkeypatch, db, db_cfg, taxpayer, fixtures_dir)
    assert _PLACEHOLDER in html
    assert 'value="E3_585_009" selected' not in html
    assert 'value="category2_3" selected' not in html

def test_classify_screen_δείχνει_μόνο_κωδικούς_εξόδων(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    html = _screen_with_e3(monkeypatch, db, db_cfg, taxpayer, fixtures_dir)
    assert 'value="E3_585_016"' in html and 'value="category2_4"' in html
    assert 'value="E3_561_001"' not in html and 'value="category1_3"' not in html

def test_classify_preview_refuses_empty_e3_code(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Το κενό που στέλνει το placeholder option πρέπει να κόβεται με 400."""
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7",
        "mark": ["900000000001048"],
        "e3_900000000001048": "",
        "category_900000000001048": "category2_4"})
    assert resp.status_code == 400
    assert "κωδικό Ε3" in resp.json()["error"]

def _preview_classification(e3, category, mark="900000000001048"):
    return TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7", "mark": [mark],
        f"e3_{mark}": e3, f"category_{mark}": category})

def test_classify_preview_μπλοκάρει_κωδικό_εσόδου(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = _preview_classification("E3_561_001", "category2_4")
    assert resp.status_code == 400
    error = resp.json()["error"]
    assert "κωδικός εσόδου" in error and "900000000001048" in error

def test_classify_preview_προειδοποιεί_για_αλλοδαπής_σε_ελληνικό_εκδότη(
        monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = _preview_classification("E3_585_010", "category2_3")
    assert resp.status_code == 200
    assert 'class="msg m-warn"' in resp.text
    assert "ΑΦΜ 990000155 — E3_585_010 (υπηρεσίες αλλοδαπής)" in resp.text
    form = re.search(r'<form method="post" action="/classify/send">.*?</form>', resp.text, re.S).group(0)
    assert 'name="ack" required' in form

def test_classify_preview_χωρίς_προειδοποίηση_χωρίς_checkbox(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = _preview_classification("E3_585_016", "category2_4")
    assert resp.status_code == 200
    assert 'name="ack"' not in resp.text and 'class="msg m-warn"' not in resp.text

def test_classify_preview_shows_xml_and_totals(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7",
        "mark": ["900000000001048"],
        "e3_900000000001048": "E3_585_016",
        "category_900000000001048": "category2_4"})
    assert resp.status_code == 200
    assert "&lt;invoiceMark&gt;900000000001048&lt;/invoiceMark&gt;" in resp.text
    assert "75,00" in resp.text

def test_classify_preview_builds_per_line_xml_for_fuel(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Τα καύσιμα χαρακτηρίζονται ανά γραμμή: χωρίς postPerInvoice, χωρίς πεδία ΦΠΑ."""
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7",
        "mark": ["900000000001047"],
        "e3_900000000001047": "E3_585_016",
        "category_900000000001047": "category2_4"})
    assert resp.status_code == 200
    assert "postPerInvoice" not in resp.text
    assert "vatAmount" not in resp.text
    # Το ΦΠΑ ανά γραμμή δεν υποβάλλεται — η προεπισκόπηση δεν πρέπει να δείχνει
    # το ποσό ΦΠΑ του παραστατικού (10,80) σαν να επρόκειτο να σταλεί.
    assert "10,80" not in resp.text

_FOREIGN_COUNTERPART_XML = """<?xml version="1.0" encoding="utf-8"?>
<RequestedDoc xmlns="http://www.aade.gr/myDATA/invoice/v1.0">
  <invoicesDoc>
    <invoice>
      <mark>900000000001006</mark>
      <issuer>
        <vatNumber>888888888</vatNumber>
        <name>ΠΡΟΜΗΘΕΥΤΗΣ Δ</name>
      </issuer>
      <counterpart>
        <vatNumber>999999999</vatNumber>
      </counterpart>
      <invoiceHeader>
        <series>Α</series>
        <aa>1</aa>
        <issueDate>2026-07-05</issueDate>
        <invoiceType>1.1</invoiceType>
      </invoiceHeader>
      <invoiceDetails>
        <lineNumber>1</lineNumber>
        <netValue>10.00</netValue>
        <vatCategory>1</vatCategory>
        <vatAmount>2.40</vatAmount>
      </invoiceDetails>
      <invoiceSummary>
        <totalNetValue>10.00</totalNetValue>
        <totalVatAmount>2.40</totalVatAmount>
      </invoiceSummary>
    </invoice>
  </invoicesDoc>
</RequestedDoc>"""

def _seed_received_xml(db, taxpayer, received_xml):
    """Ίδιο μοτίβο με _seed_july, με δικό του RequestDocs — τα υπόλοιπα endpoints
    γυρίζουν κενό, αρκετό για τα parsers που αγνοούν κενή σελίδα."""
    from esoda_exoda.refresh import refresh
    refresh(db, taxpayer, 2026, 7,
           fetch_xml=lambda m, a, b: received_xml if m == "RequestDocs" else "")
    db.commit()

def test_classify_screen_lists_foreign_counterpart_instead_of_hiding_it(monkeypatch, db, db_cfg, taxpayer):
    """Παραστατικό του μήνα που δεν έχει εμάς ως λήπτη δεν πρέπει να εξαφανίζεται
    σιωπηλά — πάει στην ομάδα «Άλλος λήπτης», ορατό, χωρίς checkbox."""
    _seed_received_xml(db, taxpayer, _FOREIGN_COUNTERPART_XML); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).get("/classify?year=2026&month=7")
    assert resp.status_code == 200
    assert "Άλλος λήπτης" in resp.text
    assert "999999999" in resp.text
    assert "ΠΡΟΜΗΘΕΥΤΗΣ Δ" in resp.text
    assert "name='mark' value='900000000001006'" not in resp.text

def test_classify_preview_refuses_foreign_counterpart(monkeypatch, db, db_cfg, taxpayer):
    """Το preview πρέπει να αρνείται ρητά ένα MARK που δεν έχει εμάς ως λήπτη,
    όχι μόνο να το αποκρύπτει στην οθόνη επιλογής."""
    _seed_received_xml(db, taxpayer, _FOREIGN_COUNTERPART_XML); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7",
        "mark": ["900000000001006"],
        "e3_900000000001006": "E3_585_016",
        "category_900000000001006": "category2_4"})
    assert resp.status_code == 400
    assert "λήπτη" in resp.json()["error"]

def test_classify_preview_refuses_mark_of_another_month(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Το by_mark βγαίνει πλέον ήδη φιλτραρισμένο στον μήνα του form (received_docs_of_month):
    ένα MARK άλλου μήνα απλώς δεν υπάρχει εκεί, άρα η άρνηση είναι «Άγνωστο MARK»."""
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "3",
        "mark": ["900000000001048"],
        "e3_900000000001048": "E3_585_016",
        "category_900000000001048": "category2_4"})
    assert resp.status_code == 400
    assert "Άγνωστα MARK" in resp.json()["error"]

_OUT_OF_SCOPE_TYPE_XML = _FOREIGN_COUNTERPART_XML.replace(
    "<vatNumber>999999999</vatNumber>", "<vatNumber>123456783</vatNumber>").replace(
    "<invoiceType>1.1</invoiceType>", "<invoiceType>8.4</invoiceType>")

def test_classify_preview_refuses_out_of_scope_type(monkeypatch, db, db_cfg, taxpayer):
    """Η οθόνη δείχνει τους τύπους 8.4/9.3 ως «εκτός εύρους» χωρίς checkbox, αλλά ο
    έλεγχος πρέπει να υπάρχει και εκεί που χτίζεται το XML — αλλιώς μόνο κρύβει."""
    _seed_received_xml(db, taxpayer, _OUT_OF_SCOPE_TYPE_XML); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7",
        "mark": ["900000000001006"],
        "e3_900000000001006": "E3_585_016",
        "category_900000000001006": "category2_4"})
    assert resp.status_code == 400
    assert "8.4" in resp.json()["error"]
    assert "portal" in resp.json()["error"]

def test_classify_send_γράφει_submission_default_και_ανανεώνει(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    from esoda_exoda.counterparties import find_by_vat
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    xml = ('<ExpensesClassificationsDoc><expensesInvoiceClassification><invoiceMark>900000000001048</invoiceMark>'
           '<invoiceClassificationDetails><expensesClassificationDetailData><classificationType>E3_585_016</classificationType>'
           '<classificationCategory>category2_4</classificationCategory><amount>115.00</amount></expensesClassificationDetailData>'
           '</invoiceClassificationDetails></expensesInvoiceClassification></ExpensesClassificationsDoc>')
    envs = []
    monkeypatch.setattr(classify_routes, "send_expenses_classification",
                        lambda x, per_invoice=True, *, env: (envs.append(env), [{"invoice_mark": "900000000001048", "classification_mark": "C1",
                                                       "status": "Success", "errors": []}], "<r/>")[1:])
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": xml,
                                                        "remember": ["900000000001048|990000155|E3_585_016|category2_4"]})
    assert resp.status_code == 200 and "C1" in resp.text
    assert envs and set(envs) == {"dev"}
    row = db.execute("select status, e3_type, amount, request_xml, response_xml from classification_submission").fetchone()
    assert row[0] == "Success" and row[1] == "E3_585_016" and float(row[2]) == 115.0 and row[3] == xml and row[4] == "<r/>"
    assert find_by_vat(db, taxpayer.id, "990000155").defaults["expense"].category_code == "category2_4"

def test_classify_send_remember_αλλάζει_υπάρχον_default(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    from esoda_exoda.counterparties import ensure_counterparty, find_by_vat, save_default
    _seed_july(db, taxpayer, fixtures_dir)
    save_default(db, ensure_counterparty(db, taxpayer.id, "990000155"), "expense", "category2_3", "E3_585_009", True); db.commit()
    _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification",
                        lambda x, per_invoice=True, *, env: ([{"invoice_mark": "M", "classification_mark": "C", "status": "Success", "errors": []}], ""))
    TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<ExpensesClassificationsDoc/>",
                                                 "remember": ["M|990000155|E3_585_016|category2_5"]})
    d = find_by_vat(db, taxpayer.id, "990000155").defaults["expense"]
    assert (d.category_code, d.deductible) == ("category2_5", False)

def test_classify_send_logs_e3_category_and_amount(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Η καταγραφή πρέπει να απαντά «τι χαρακτηρισμό υπέβαλα και για πόσα» χωρίς
    σταυρωτή αναφορά με το XML, που δεν αποθηκεύεται πουθενά αλλού."""
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "900000000001048", "classification_mark": "1000000000000001",
         "status": "Success", "errors": []}], "<raw/>"))
    xml = """<ExpensesClassificationsDoc><expensesInvoiceClassification>
      <invoiceMark>900000000001048</invoiceMark>
      <invoicesExpensesClassificationDetails><lineNumber>1</lineNumber>
        <expensesClassificationDetailData>
          <classificationType>E3_585_016</classificationType>
          <classificationCategory>category2_4</classificationCategory>
          <amount>75.00</amount>
        </expensesClassificationDetailData>
      </invoicesExpensesClassificationDetails>
    </expensesInvoiceClassification></ExpensesClassificationsDoc>"""
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": xml})
    assert resp.status_code == 200
    row = db.execute("select e3_type, category, amount from classification_submission").fetchone()
    assert row[0] == "E3_585_016" and row[1] == "category2_4" and float(row[2]) == 75.0

def test_classify_send_logs_even_when_xml_is_unreadable(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Η υποβολή έγινε ήδη· ένα XML που δεν διαβάζεται δεν ρίχνει το route."""
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "1", "classification_mark": "11", "status": "Success", "errors": []}], "<raw/>"))
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<x"})
    assert resp.status_code == 200
    assert db.execute("select classification_mark from classification_submission").fetchone()[0] == "11"

def test_classify_send_reports_partial_failure_without_hiding_successes(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "1", "classification_mark": "11", "status": "Success", "errors": []},
        {"invoice_mark": "2", "classification_mark": "", "status": "ValidationError",
         "errors": [{"code": "339", "message": "Invalid combination"}]}], "<raw/>"))
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<x/>"})
    assert resp.status_code == 200 and "11" in resp.text and "339" in resp.text

def test_classify_send_survives_refresh_failure(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "1", "classification_mark": "11", "status": "Success", "errors": []}], "<raw/>"))
    def boom(*a, **kw):
        raise OSError("το Excel είναι ανοιχτό")
    monkeypatch.setattr(classify_routes, "refresh", boom)
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<x/>"})
    assert resp.status_code == 207
    assert "11" in resp.text and "το Excel είναι ανοιχτό" in resp.text
    assert db.execute("select classification_mark from classification_submission").fetchone()[0] == "11"

def test_classify_send_remembers_only_successful_marks(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    from esoda_exoda.counterparties import find_by_vat
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "1", "classification_mark": "11", "status": "Success", "errors": []},
        {"invoice_mark": "2", "classification_mark": "", "status": "ValidationError",
         "errors": [{"code": "339", "message": "x"}]}], "<raw/>"))
    TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_invoice": "<x/>",
        "remember": ["1|990000155|E3_585_016|category2_4",
                     "2|090000150|E3_585_016|category2_4"]})
    assert find_by_vat(db, taxpayer.id, "990000155").defaults["expense"].category_code == "category2_4"
    assert find_by_vat(db, taxpayer.id, "090000150") is None

def test_classify_send_flags_unclear_results_without_treating_as_success(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """statusCode Success χωρίς classificationMark δεν είναι επιτυχία: δεν μπαίνει
    στα succeeded, αλλά καταγράφεται στη βάση και προειδοποιεί ρητά τον χρήστη."""
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "3", "classification_mark": "", "status": "Success", "errors": []}], "<raw/>"))
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<x/>"})
    assert resp.status_code == 200
    text = _visible(resp.text)
    assert "3" in text
    row = db.execute("select invoice_mark, status from classification_submission").fetchone()
    assert row == ("3", "Success")

def test_classify_send_reports_rate_limit(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    def fake_send(xml, per_invoice=True, *, env):
        raise HTTPError("https://mydatapi.aade.gr", 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(classify_routes, "send_expenses_classification", fake_send)
    called = {"refresh": False}
    def fake_refresh(*a, **kw):
        called["refresh"] = True
    monkeypatch.setattr(classify_routes, "refresh", fake_refresh)
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<x/>"})
    assert resp.status_code == 503
    assert "Όριο κλήσεων myDATA" in _visible(resp.text)
    assert called["refresh"] is False
    assert db.execute("select count(*) from classification_submission").fetchone()[0] == 0

def test_classify_send_reports_unreadable_response_without_claiming_failure(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Η υποβολή έγινε· μια αδιάβαστη απάντηση δεν είναι ούτε επιτυχία ούτε αποτυχία —
    και αφήνει ίχνος στη βάση, γιατί εκεί είναι η μόνη περίπτωση που το χρειάζεται."""
    import xml.etree.ElementTree as ET
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    def fake_send(xml, per_invoice=True, *, env):
        raise ET.ParseError("not well-formed")
    monkeypatch.setattr(classify_routes, "send_expenses_classification", fake_send)
    called = {"refresh": False}
    def fake_refresh(*a, **kw):
        called["refresh"] = True
    monkeypatch.setattr(classify_routes, "refresh", fake_refresh)
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<x/>"})
    assert resp.status_code == 502
    assert "portal" in _visible(resp.text)
    assert called["refresh"] is False
    assert db.execute("select status from classification_submission").fetchone()[0] == "ΑΓΝΩΣΤΟ"

def test_classify_send_reports_empty_result_list_without_claiming_failure(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([], "<raw/>"))
    called = {"refresh": False}
    def fake_refresh(*a, **kw):
        called["refresh"] = True
    monkeypatch.setattr(classify_routes, "refresh", fake_refresh)
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<x/>"})
    assert resp.status_code == 502
    assert "portal" in _visible(resp.text)
    assert called["refresh"] is False
    assert db.execute("select status from classification_submission").fetchone()[0] == "ΑΓΝΩΣΤΟ"

def test_classify_send_returns_207_when_log_write_fails(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "1", "classification_mark": "11", "status": "Success", "errors": []}], "<raw/>"))
    def fail(*a, **kw):
        raise RuntimeError("disk full")
    monkeypatch.setattr(classify_routes, "record_classification_submissions", fail)
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7", "xml_per_invoice": "<x/>"})
    assert resp.status_code == 207
    text = _visible(resp.text)
    assert "11" in text and "disk full" in text
    assert db.execute("select count(*) from classification_submission").fetchone()[0] == 0

def test_classify_send_config_error_on_remember_becomes_warning(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    from esoda_exoda.counterparties import CounterpartyError
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "1", "classification_mark": "11", "status": "Success", "errors": []}], "<raw/>"))
    def fake_save(*a, **kw):
        raise CounterpartyError("ο ΑΦΜ υπάρχει ήδη με άλλες τιμές")
    monkeypatch.setattr(classify_routes, "save_default", fake_save)
    resp = TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_invoice": "<x/>",
        "remember": ["1|990000155|E3_585_016|category2_4"]})
    assert resp.status_code == 200
    text = _visible(resp.text)
    assert "11" in text and "ο ΑΦΜ υπάρχει ήδη" in text

def test_classify_send_ignores_malformed_remember_value(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification", lambda xml, per_invoice=True, *, env: ([
        {"invoice_mark": "1", "classification_mark": "11", "status": "Success", "errors": []}], "<raw/>"))
    resp = TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_invoice": "<x/>",
        "remember": ["1|990000155|E3_585_016"]})
    assert resp.status_code == 200
    text = _visible(resp.text)
    assert "11" in text and "Αγνοήθηκε άκυρη τιμή" in text

def test_classify_preview_shows_both_documents_for_mixed_selection(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Δύο αιτήματα, μία οθόνη: ο χρήστης βλέπει ακριβώς ό,τι θα φύγει, και τώρα
    φεύγουν δύο πράγματα."""
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7",
        "mark": ["900000000001048", "900000000001047"],
        "e3_900000000001048": "E3_585_016",
        "category_900000000001048": "category2_4",
        "e3_900000000001047": "E3_585_016",
        "category_900000000001047": "category2_4"})
    assert resp.status_code == 200
    assert resp.text.count("<pre>") == 2
    text = _visible(resp.text)
    assert "Ανά παραστατικό (1 παραστατικό)" in text
    assert "Ανά γραμμή, καύσιμα (1 παραστατικό)" in text
    assert 'name="xml_per_invoice" value=""' not in resp.text
    assert 'name="xml_per_line" value=""' not in resp.text
    assert "postPerInvoice" not in resp.text

def test_classify_preview_shows_only_per_invoice_document_without_fuel(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7",
        "mark": ["900000000001048"],
        "e3_900000000001048": "E3_585_016",
        "category_900000000001048": "category2_4"})
    assert resp.status_code == 200
    assert resp.text.count("<pre>") == 1
    assert "Ανά παραστατικό (1 παραστατικό)" in _visible(resp.text)
    assert "Ανά γραμμή" not in resp.text
    assert 'name="xml_per_line" value=""' in resp.text

def test_classify_preview_shows_only_per_line_document_for_fuel_only(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7",
        "mark": ["900000000001047"],
        "e3_900000000001047": "E3_585_016",
        "category_900000000001047": "category2_4"})
    assert resp.status_code == 200
    assert resp.text.count("<pre>") == 1
    assert "Ανά γραμμή, καύσιμα (1 παραστατικό)" in _visible(resp.text)
    assert "Ανά παραστατικό" not in resp.text
    assert 'name="xml_per_invoice" value=""' in resp.text

def test_classify_send_posts_both_documents_with_the_right_per_invoice_flag(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    calls = []
    def fake_send(xml, per_invoice=True, *, env):
        calls.append((xml, per_invoice))
        mark = "1" if per_invoice else "2"
        return [{"invoice_mark": mark, "classification_mark": "1" + mark,
                 "status": "Success", "errors": []}], "<raw/>"
    monkeypatch.setattr(classify_routes, "send_expenses_classification", fake_send)
    resp = TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_invoice": "<a/>", "xml_per_line": "<b/>"})
    assert resp.status_code == 200
    assert calls == [("<a/>", True), ("<b/>", False)]
    text = _visible(resp.text)
    assert "11" in text and "12" in text

def test_classify_send_keeps_first_marks_when_second_request_is_rate_limited(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Τα classification_mark του πρώτου POST είναι αμετάκλητα εκδομένα. Ένα 429 στο
    δεύτερο δεν επιτρέπεται να τα εξαφανίσει: μπαίνουν στην απάντηση μαζί με ρητή
    περιγραφή του τι δεν στάλθηκε."""
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    def fake_send(xml, per_invoice=True, *, env):
        if per_invoice:
            return [{"invoice_mark": "1", "classification_mark": "11",
                     "status": "Success", "errors": []}], "<raw/>"
        raise HTTPError("https://mydatapi.aade.gr", 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(classify_routes, "send_expenses_classification", fake_send)
    resp = TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_invoice": "<a/>", "xml_per_line": "<b/>"})
    assert resp.status_code == 207
    text = _visible(resp.text)
    assert "11" in text
    assert "Όριο κλήσεων myDATA" in text
    assert "καύσιμα" in text
    rows = db.execute("select classification_mark from classification_submission").fetchall()
    assert [r[0] for r in rows] == ["11"]

def test_classify_send_refuses_when_no_document_was_submitted(monkeypatch, db, db_cfg, taxpayer):
    from esoda_exoda.web import classify_routes
    _wire_classify(monkeypatch, db_cfg)
    def boom(*a, **kw):
        raise AssertionError("δεν πρέπει να γίνει καμία υποβολή")
    monkeypatch.setattr(classify_routes, "send_expenses_classification", boom)
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7"})
    assert resp.status_code == 400
    assert "XML" in _visible(resp.text)

# Η διάκριση που μετράει δεν είναι «σφάλμα δικτύου ή όχι» αλλά «έφυγε το POST ή δεν
# έφυγε». Το URLError καλύπτει μόνο το ακίνδυνο μισό (το αίτημα δεν έφυγε). Τα
# υπόλοιπα σκάνε στο getresponse()/read(), που το urllib ΔΕΝ τυλίγει: το POST έχει
# φύγει και ο χαρακτηρισμός μπορεί να έχει καταχωρηθεί χωρίς να το ξέρουμε. Με
# timeout=120 και κανένα retry, το read timeout είναι η πιθανότερη αστοχία.
_SEND_FAILURES = [
    ("timeout", lambda: TimeoutError("timed out")),
    ("connection_reset", lambda: ConnectionResetError("η σύνδεση έκλεισε απότομα")),
    ("remote_disconnected",
     lambda: http.client.RemoteDisconnected("Remote end closed connection")),
    ("incomplete_read", lambda: http.client.IncompleteRead(b"", 10)),
    ("urlerror", lambda: URLError("δεν βρέθηκε ο host")),
    # Το SSLError είναι OSError αλλά ούτε ConnectionError ούτε URLError ούτε
    # HTTPException: ίδια κατηγορία, άλλη πόρτα.
    ("ssl_eof", lambda: ssl.SSLEOFError("EOF occurred in violation of protocol")),
    # Σκέτο OSError: κλειδώνει τη γενίκευση, ώστε να μη γυρίσει κανείς σε απαρίθμηση
    # τύπων ένα πρόβλημα που ορίζεται από το πότε συμβαίνει.
    ("oserror", lambda: OSError("κάτι socket-level που δεν προβλέψαμε")),
    ("http_500", lambda: HTTPError("https://mydatapi.aade.gr", 500,
                                   "Internal Server Error", {}, None)),
]
_SEND_FAILURE_IDS = [name for name, _ in _SEND_FAILURES]

@pytest.mark.parametrize("make_error", [f for _, f in _SEND_FAILURES],
                         ids=_SEND_FAILURE_IDS)
def test_classify_send_keeps_first_marks_when_second_request_breaks(
        make_error, monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Ό,τι σκάει στο δεύτερο αίτημα, τα classification_mark του πρώτου είναι
    αμετάκλητα εκδομένα: μένουν ορατά στην απάντηση και γραμμένα στη βάση."""
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    def fake_send(xml, per_invoice=True, *, env):
        if per_invoice:
            return [{"invoice_mark": "1", "classification_mark": "11",
                     "status": "Success", "errors": []}], "<raw/>"
        raise make_error()
    monkeypatch.setattr(classify_routes, "send_expenses_classification", fake_send)
    resp = TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_invoice": "<a/>", "xml_per_line": "<b/>"})
    assert resp.status_code == 207
    text = _visible(resp.text)
    assert "11" in text
    assert "καύσιμα" in text
    assert "portal" in text
    statuses = [r[0] for r in db.execute(
        "select status from classification_submission order by id").fetchall()]
    assert "Success" in statuses and "ΑΓΝΩΣΤΟ" in statuses

@pytest.mark.parametrize("make_error", [f for _, f in _SEND_FAILURES],
                         ids=_SEND_FAILURE_IDS)
def test_classify_send_logs_unknown_outcome_when_the_only_request_breaks(
        make_error, monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Το «στάλθηκε, δεν ξέρω» δεν επιτρέπεται να ζει μόνο στο HTTP response: όταν
    κλείσει ο browser, η γραμμή στη βάση είναι ό,τι μένει."""
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    def fake_send(xml, per_invoice=True, *, env):
        raise make_error()
    monkeypatch.setattr(classify_routes, "send_expenses_classification", fake_send)
    called = {"refresh": False}
    def fake_refresh(*a, **kw):
        called["refresh"] = True
    monkeypatch.setattr(classify_routes, "refresh", fake_refresh)
    resp = TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_invoice": "<a/>"})
    assert resp.status_code == 502
    assert "portal" in _visible(resp.text)
    assert called["refresh"] is False
    row = db.execute("select status, per_invoice from classification_submission").fetchone()
    assert row == ("ΑΓΝΩΣΤΟ", True)

_UNKNOWN_REQUEST_XML = """<ExpensesClassificationsDoc><expensesInvoiceClassification>
  <invoiceMark>900000000001048</invoiceMark>
  <invoicesExpensesClassificationDetails><lineNumber>1</lineNumber>
    <expensesClassificationDetailData>
      <classificationType>E3_585_016</classificationType>
      <classificationCategory>category2_4</classificationCategory>
      <amount>75.00</amount>
    </expensesClassificationDetailData>
  </invoicesExpensesClassificationDetails>
</expensesInvoiceClassification></ExpensesClassificationsDoc>"""

def test_classify_send_logs_marks_of_the_unknown_request_from_its_xml(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Η γραμμή «ΑΓΝΩΣΤΟ» πρέπει να λέει ΠΟΙΑ παραστατικά μπορεί να καταχωρήθηκαν —
    αλλιώς ο χρήστης δεν ξέρει τι να ψάξει στο portal."""
    import xml.etree.ElementTree as ET
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    def fake_send(xml, per_invoice=True, *, env):
        raise ET.ParseError("not well-formed")
    monkeypatch.setattr(classify_routes, "send_expenses_classification", fake_send)
    resp = TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_line": _UNKNOWN_REQUEST_XML})
    assert resp.status_code == 502
    row = db.execute("select invoice_mark, status, per_invoice, e3_type, amount, errors "
                     "from classification_submission").fetchone()
    assert row[0] == "900000000001048"
    assert row[1] == "ΑΓΝΩΣΤΟ"
    assert row[2] is False
    assert row[3] == "E3_585_016"
    assert float(row[4]) == 75.0
    assert "διαβάζεται" in str(row[5])

def test_classify_send_says_resend_only_once_when_both_requests_are_rate_limited(
        monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    def fake_send(xml, per_invoice=True, *, env):
        raise HTTPError("https://mydatapi.aade.gr", 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(classify_routes, "send_expenses_classification", fake_send)
    resp = TestClient(app).post("/classify/send", data={
        "year": "2026", "month": "7", "xml_per_invoice": "<a/>", "xml_per_line": "<b/>"})
    assert resp.status_code == 503
    error = _visible(resp.text)
    assert error.count("Ξαναστείλε") == 1
    assert db.execute("select count(*) from classification_submission").fetchone()[0] == 0

_FUEL_E3_LINES = [("expense", "category2_5", "E3_585_016", 55.8)]

def _classify_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir,
                     e3_lines=_FUEL_E3_LINES, mark="900000000001047",
                     issue_date=date(2026, 7, 21)):
    """Προεπιλογή: μόνο το τιμολόγιο καυσίμων (900000000001047) έχει snapshot e3_info —
    category2_5/E3_585_016/55.80, ίδιο σχήμα με το παλιό _FUEL_E3 dict. Το
    900000000001048 μένει αχαρακτήριστο εκτός αν το test δώσει δικό του e3_lines/mark."""
    from esoda_exoda.fetches import store_fetch
    from esoda_exoda.invoices import add_snapshot
    _seed_july(db, taxpayer, fixtures_dir, with_e3=False)
    if e3_lines:
        f = store_fetch(db, taxpayer.id, "RequestE3Info", date(2026, 7, 1), date(2026, 7, 31), "")
        add_snapshot(db, taxpayer.id, mark, "e3_info", f, issue_date, lines=e3_lines)
        db.commit()
    _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).get("/classify?year=2026&month=7")
    assert resp.status_code == 200
    return resp.text

def _group(html, title, next_title):
    return html.split(title)[1].split(next_title)[0]

def test_οθόνη_δείχνει_τα_ήδη_χαρακτηρισμένα_ως_χαρακτηρισμένα(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    # Το τιμολόγιο καυσίμων 900000000001047 είναι category2_5 στην ΑΑΔΕ (fixture E3Info).
    # Πριν τη διόρθωση εμφανιζόταν ως αχαρακτήριστο και η υποβολή θα το έκανε 2.4.
    html = _classify_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir)
    classified = _group(html, "Χαρακτηρισμένα", "Εκτός εύρους")
    unclassified = _group(html, "Αχαρακτήριστα", "Χαρακτηρισμένα")
    assert "900000000001047" in classified
    assert "900000000001047" not in unclassified
    assert "900000000001048" in unclassified

def test_οθόνη_δείχνει_τον_πραγματικό_κωδικό_που_ισχύει(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    html = _classify_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir)
    classified = _group(html, "Χαρακτηρισμένα", "Εκτός εύρους")
    assert "ΙΣΧΥΕΙ ΤΩΡΑ" in html
    assert "category2_5" in classified
    assert "E3_585_016" in classified

def test_τα_ήδη_χαρακτηρισμένα_δεν_είναι_προεπιλεγμένα(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    html = _classify_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir)
    classified = _group(html, "Χαρακτηρισμένα", "Εκτός εύρους")
    assert "checked" not in classified

def test_χαρακτηρισμός_εσόδου_δεν_μετράει_ως_χαρακτηρισμένο_έξοδο(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    # Ένα category1_3 (χωρίς καμία γραμμή category2_*) δεν κάνει ένα ληφθέν έξοδο
    # «χαρακτηρισμένο».
    html = _classify_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir,
                            e3_lines=[("income", "category1_3", "E3_561_001", 55.8)])
    unclassified = _group(html, "Αχαρακτήριστα", "Χαρακτηρισμένα")
    assert "900000000001047" in unclassified

def test_οθόνη_προεπιλέγει_τον_κωδικό_εξόδου_σε_μεικτό_mark(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    # Μεικτό MARK, category1_3 (έσοδο) πρώτο και category2_5 (έξοδο) δεύτερο: η οθόνη
    # δεν πρέπει να προεπιλέξει τον κωδικό εσόδου στα dropdowns εξόδων, ούτε να τον
    # αναφέρει στο «Ισχύει τώρα» σαν να αντικαθίσταται.
    html = _classify_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir,
                            e3_lines=[("income", "category1_3", "E3_561_001", 100.0),
                                     ("expense", "category2_5", "E3_585_016", 55.8)])
    classified = _group(html, "Χαρακτηρισμένα", "Εκτός εύρους")
    assert "selected>2.5" in classified
    assert 'value="E3_561_001" selected' not in classified
    assert 'value="category1_3" selected' not in classified

def _classify_preview(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, category, e3_lines=None,
                      mark="900000000001048", issue_date=date(2026, 7, 22)):
    from esoda_exoda.fetches import store_fetch
    from esoda_exoda.invoices import add_snapshot
    _seed_july(db, taxpayer, fixtures_dir, with_e3=False)
    if e3_lines:
        f = store_fetch(db, taxpayer.id, "RequestE3Info", date(2026, 7, 1), date(2026, 7, 31), "")
        add_snapshot(db, taxpayer.id, mark, "e3_info", f, issue_date, lines=e3_lines)
        db.commit()
    _wire_classify(monkeypatch, db_cfg)
    return TestClient(app).post("/classify/preview", data={
        "year": "2026", "month": "7", "mark": [mark],
        f"e3_{mark}": "E3_585_016",
        f"category_{mark}": category})

def test_προεπισκόπηση_προειδοποιεί_για_αντικατάσταση(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    r = _classify_preview(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, "category2_4",
                          e3_lines=[("expense", "category2_5", "E3_585_016", 75.0)])
    assert r.status_code == 200
    assert "ΑΝΤΙΚΑΘΙΣΤΑΤΑΙ" in r.text
    assert "category2_5" in r.text   # ο παλιός
    assert "category2_4" in r.text   # ο νέος

def test_προεπισκόπηση_δεν_προειδοποιεί_για_αχαρακτήριστο(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    r = _classify_preview(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, "category2_4")
    assert r.status_code == 200
    assert "ΑΝΤΙΚΑΘΙΣΤΑΤΑΙ" not in r.text

def test_προεπισκόπηση_αγνοεί_χαρακτηρισμό_εσόδου(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    # category1_3 στο ίδιο MARK δεν είναι χαρακτηρισμός εξόδου — τίποτα δεν αντικαθίσταται.
    r = _classify_preview(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, "category2_4",
                          e3_lines=[("income", "category1_3", "E3_561_001", 75.0)])
    assert r.status_code == 200
    assert "ΑΝΤΙΚΑΘΙΣΤΑΤΑΙ" not in r.text

def test_stylesheet_makes_no_external_calls():
    """Η εφαρμογή τρέχει τοπικά και δεν επιτρέπεται να δείχνει αλλιώς χωρίς δίκτυο:
    οι γραμματοσειρές σερβίρονται από το static/fonts, όχι από CDN."""
    from esoda_exoda.web import app as web_app
    css = (Path(web_app.__file__).parent / "static" / "app.css").read_text(encoding="utf-8")
    assert "@font-face" in css
    assert not re.search(r"url\(\s*['\"]?(https?:)?//", css), "εξωτερικό url() στο app.css"

def test_every_font_file_the_stylesheet_asks_for_exists():
    from esoda_exoda.web import app as web_app
    static = Path(web_app.__file__).parent / "static"
    css = (static / "app.css").read_text(encoding="utf-8")
    refs = re.findall(r"url\('(/static/[^']+)'\)", css)
    assert refs, "το app.css δεν δηλώνει καμία γραμματοσειρά"
    for ref in refs:
        assert (static / ref.removeprefix("/static/")).is_file(), f"λείπει το {ref}"

def test_classify_screen_renders_inside_the_dashboard_shell(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Η οθόνη μήνα κληρονομεί το ίδιο κέλυφος: η ταυτότητα του αποστολέα και το
    κατώφλι του αμετάκλητου μένουν ορατά και εδώ."""
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).get("/classify?year=2026&month=7")
    assert resp.status_code == 200
    assert "/static/app.css" in resp.text
    assert "123456783" in resp.text
    assert "ΑΜΕΤΑΚΛΗΤΟ" in resp.text
    assert 'href="/classify?year=2026&amp;month=7" aria-current="page"' in resp.text

def test_classify_screen_says_the_preview_does_not_send(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Πριν από κάθε αμετάκλητο βήμα η οθόνη λέει ρητά τι κάνει το κουμπί."""
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).get("/classify?year=2026&month=7")
    assert "Δεν στέλνει" in resp.text

def _visible(html):
    """Ό,τι διαβάζει ο χρήστης, χωρίς tags: τα tests της οθόνης δεν πρέπει να
    σπάνε επειδή ένα κείμενο τυλίχτηκε σε span."""
    return re.sub(r"<[^>]+>", "", html)

def test_preview_renders_inside_the_shell_before_the_gate(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Η οθόνη ελέγχου είναι το τελευταίο βήμα που γυρίζει πίσω: η πορεία το λέει,
    και το κατώφλι του αμετάκλητου είναι ακόμη μπροστά."""
    r = _classify_preview(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, "category2_4")
    assert r.status_code == 200
    assert "/static/app.css" in r.text
    assert "ΑΜΕΤΑΚΛΗΤΟ" in r.text
    text = _visible(r.text)
    assert "Έλεγξε πριν σταλεί" in text
    assert "δεν υπάρχει επαναφορά" in text

def test_preview_send_button_is_the_only_irrevocable_control(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Ένα και μόνο κουμπί στέλνει, και ξεχωρίζει από ό,τι γυρίζει πίσω."""
    r = _classify_preview(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, "category2_4")
    assert r.text.count('class="send"') == 1
    assert 'action="/classify/send"' in r.text

def test_preview_offers_a_way_back_to_the_month(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Οθόνη ελέγχου χωρίς έξοδο πιέζει τον χρήστη προς τα εμπρός."""
    r = _classify_preview(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, "category2_4")
    assert 'href="/classify?year=2026&amp;month=7"' in r.text

def _sent_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, results, **extra):
    from esoda_exoda.web import classify_routes
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    monkeypatch.setattr(classify_routes.mydata_client, "fetch_xml", _fixture_fetch(fixtures_dir))
    monkeypatch.setattr(classify_routes, "send_expenses_classification",
                        lambda xml, per_invoice=True, *, env: (results, "<raw/>"))
    if "refresh" in extra:
        monkeypatch.setattr(classify_routes, "refresh", extra["refresh"])
    return TestClient(app).post("/classify/send",
                                data={"xml_per_invoice": "<x/>", "year": "2026", "month": "7"})

_ONE_OK = [{"invoice_mark": "900000000001048", "classification_mark": "900000000001055",
            "status": "Success", "errors": []}]

def test_sent_screen_renders_past_the_gate_with_the_mark(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Το MARK χαρακτηρισμού είναι το μόνο χερούλι για έλεγχο, οπότε δεν παρουσιάζεται
    ως ωμό JSON."""
    resp = _sent_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, _ONE_OK)
    assert resp.status_code == 200
    assert "/static/app.css" in resp.text
    assert "900000000001055" in resp.text
    text = _visible(resp.text)
    assert "Στάλθηκε" in text
    assert "succeeded" not in text     # καμία διαρροή ονομάτων πεδίων JSON

def test_sent_screen_shows_failures_without_hiding_successes(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    results = _ONE_OK + [{"invoice_mark": "900000000001047", "classification_mark": "",
                          "status": "ValidationError",
                          "errors": [{"code": "339", "message": "Invalid combination"}]}]
    resp = _sent_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, results)
    text = _visible(resp.text)
    assert "900000000001055" in text        # η επιτυχία μένει ορατή
    assert "339" in text and "Invalid combination" in text

def test_sent_screen_surfaces_a_refresh_failure_as_207(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    """Η υποβολή πέτυχε και είναι αμετάκλητη· η αποτυχία του refresh δεν επιτρέπεται
    να κρύψει το MARK."""
    def boom(*a, **kw):
        raise OSError("το Excel είναι ανοιχτό")
    resp = _sent_screen(monkeypatch, db, db_cfg, taxpayer, fixtures_dir, _ONE_OK, refresh=boom)
    assert resp.status_code == 207
    text = _visible(resp.text)
    assert "900000000001055" in text
    assert "το Excel είναι ανοιχτό" in text

def test_sent_screen_renders_a_refusal_as_a_sentence(monkeypatch, db, db_cfg, taxpayer):
    _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).post("/classify/send", data={"year": "2026", "month": "7"})
    assert resp.status_code == 400
    assert "Δεν στάλθηκε κανένα XML χαρακτηρισμού" in _visible(resp.text)

def test_transmit_form_shows_the_issue_date_as_dd_mm_yyyy(monkeypatch, db, db_cfg, taxpayer):
    """Το ορατό πεδίο δηλώνει ρητά dd-mm-yyyy: το input[type=date] αποδίδει σε μορφή
    του browser (σε en-US η 2 Σεπτεμβρίου φαινόταν «9/2/2026») και η σελίδα δεν
    μπορεί να το αλλάξει. Το native ημερολόγιο μένει, πίσω από το κουμπί."""
    _wire(monkeypatch, db_cfg)
    page = TestClient(app).get("/transmit").text
    assert 'name="issue_date" type="text"' in page
    assert 'placeholder="dd-mm-yyyy"' in page
    assert r'pattern="\d{2}-\d{2}-\d{4}"' in page
    assert 'type="date" class="pick"' in page    # το ημερολόγιο υπάρχει ακόμη
    assert f'value="{date.today():%d-%m-%Y}"' in page

def test_transmit_preview_accepts_the_dd_mm_yyyy_the_form_sends(monkeypatch, db, db_cfg, taxpayer):
    _refreshed_transmitted(db, taxpayer)
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview",
                                data={"preset": "κοινόχρηστα", "issue_date": "01-08-2026",
                                      "net": "12,00", "series": "123456783",
                                      "aa": "8000000020"})
    assert resp.status_code == 200
    assert "&lt;issueDate&gt;2026-08-01&lt;/issueDate&gt;" in resp.text
    assert "01/08/2026" in _visible(resp.text)

def test_transmit_preview_refuses_a_date_in_another_format(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview",
                                data={"preset": "κοινόχρηστα", "issue_date": "01/08/2026",
                                      "net": "12,00", "series": "1", "aa": "2"})
    assert resp.status_code == 400
    assert "dd-mm-yyyy" in _visible(resp.text)

def test_transmit_preview_refusal_keeps_what_was_typed(monkeypatch, db, db_cfg, taxpayer):
    """Άρνηση δεν επιτρέπεται να σβήσει τη φόρμα: ο χρήστης δεν ξαναπληκτρολογεί."""
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/transmit/preview",
                                data={"preset": "κοινόχρηστα",
                                      "issue_date": "2026-08-01", "net": "1.250",
                                      "series": "123456783", "aa": ""})
    assert resp.status_code == 400
    assert "Αμφίσημο" in _visible(resp.text)
    assert 'value="1.250"' in resp.text          # η καθαρή αξία όπως γράφτηκε
    assert 'value="123456783"' in resp.text      # η σειρά
    assert 'value="2026-08-01"' in resp.text     # η ημερομηνία

def test_transmit_screens_share_the_shell_and_the_gate(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    page = TestClient(app).get("/transmit").text
    assert "/static/app.css" in page
    assert "ΑΜΕΤΑΚΛΗΤΟ" in page
    assert 'href="/transmit" aria-current="page"' in page

def test_index_uses_a_month_picker_for_the_classification_period(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    page = TestClient(app).get("/").text
    form = re.search(r'<form[^>]*action="/classify".*?</form>', page, re.S).group(0)
    assert 'type="month"' in form
    assert 'name="period"' in form
    assert 'name="month"' not in form      # ένα πεδίο, όχι δύο

def test_classify_accepts_a_period_from_the_month_picker(monkeypatch, db, db_cfg, taxpayer, fixtures_dir):
    _seed_july(db, taxpayer, fixtures_dir); _wire_classify(monkeypatch, db_cfg)
    resp = TestClient(app).get("/classify?period=2026-07")
    assert resp.status_code == 200
    assert "07/2026" in _visible(resp.text)

def test_κάθε_σελίδα_δείχνει_dev(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    from esoda_exoda.web import counterparty_routes
    monkeypatch.setattr(counterparty_routes, "load_config", lambda: db_cfg)
    for path in ("/", "/counterparties"):
        html = TestClient(app).get(path).text
        assert 'class="envbar envbar--dev"' in html and "DEV (sandbox ΑΑΔΕ)" in html

def test_production_δείχνει_αμετάκλητες(monkeypatch, db, db_cfg):
    from esoda_exoda.taxpayers import create_taxpayer
    create_taxpayer(db, "123456783", environment="production"); db.commit()
    _wire(monkeypatch, db_cfg)
    html = TestClient(app).get("/").text
    assert "envbar--production" in html and "PRODUCTION — οι διαβιβάσεις είναι αμετάκλητες" in html

def test_σελίδα_σφάλματος_χωρίς_ένδειξη(monkeypatch, db, db_cfg):
    _wire(monkeypatch, db_cfg)
    assert "envbar" not in TestClient(app).get("/").text
