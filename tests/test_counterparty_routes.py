# ABOUTME: Tests της οθόνης αντισυμβαλλόμενων: λίστα με πρώτα όσους λείπει προεπιλογή,
# ABOUTME: δημιουργία/επεξεργασία, επικυρώσεις 14.x, διαγραφή προεπιλογής με κενά πεδία.
import re
from datetime import date
from fastapi.testclient import TestClient
from esoda_exoda.counterparties import ensure_counterparty, get_counterparty, find_by_vat, save_default
from esoda_exoda.fetches import store_fetch
from esoda_exoda.invoices import upsert_book_record
from esoda_exoda.models import Record
from esoda_exoda.web.app import app

def _wire(monkeypatch, db_cfg):
    from esoda_exoda.web import counterparty_routes
    monkeypatch.setattr(counterparty_routes, "load_config", lambda: db_cfg)

def test_λίστα_βάζει_πρώτους_όσους_λείπει_προεπιλογή(monkeypatch, db, db_cfg, taxpayer):
    a = ensure_counterparty(db, taxpayer.id, "A", "Άλφα"); save_default(db, a, "expense", "category2_4", "E3_585_016", True)
    b = ensure_counterparty(db, taxpayer.id, "B", "Βήτα")
    f = store_fetch(db, taxpayer.id, "RequestMyExpenses", date(2026, 1, 1), date(2026, 12, 31), "")
    upsert_book_record(db, taxpayer.id, Record("B", date(2026, 7, 3), "1.1", 10, 2.4, 0, 12.4, "M"), "expense", f, b); db.commit()
    _wire(monkeypatch, db_cfg)
    html = TestClient(app).get("/counterparties").text
    assert html.index("Βήτα") < html.index("Άλφα") and "2.4" in html and "03/07/2026" in html

def test_νέος_προμηθευτής_εξωτερικού(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app, follow_redirects=False).post("/counterparties", data={
        "vat": "NL999999003B01", "country": "NL", "name": "FOREIGN SUPPLIER A B.V.", "postal_code": "1017", "city": "Amsterdam",
        "notes": "", "exp_category": "category2_3", "exp_e3": "E3_585_010", "exp_deductible": "ΝΑΙ", "exp_inv_type": "14.3",
        "inc_category": "", "inc_e3": ""})
    assert resp.status_code == 303
    cp = find_by_vat(db, taxpayer.id, "NL999999003B01")
    assert cp.defaults["expense"].inv_type == "14.3" and "income" not in cp.defaults

def test_άκυρη_χώρα_για_14_3_ξαναδίνει_τη_φόρμα(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    resp = TestClient(app).post("/counterparties", data={
        "vat": "X", "country": "US", "name": "ACME", "postal_code": "1", "city": "NY", "notes": "",
        "exp_category": "category2_3", "exp_e3": "E3_585_010", "exp_deductible": "ΝΑΙ", "exp_inv_type": "14.3",
        "inc_category": "", "inc_e3": ""})
    assert resp.status_code == 400 and "ΕΕ" in resp.text and 'value="ACME"' in resp.text
    assert find_by_vat(db, taxpayer.id, "X") is None

def test_επεξεργασία_ονόματος_separate_totals_και_διαγραφή_προεπιλογής(monkeypatch, db, db_cfg, taxpayer):
    cid = ensure_counterparty(db, taxpayer.id, "990000106", "ΠΕΛΑΤΗΣ Α ΑΕ")
    save_default(db, cid, "income", "category1_3", "E3_561_001", None); db.commit()
    _wire(monkeypatch, db_cfg)
    page = TestClient(app).get(f"/counterparties/{cid}").text
    assert 'value="ΠΕΛΑΤΗΣ Α ΑΕ"' in page and "category1_3" in page
    resp = TestClient(app, follow_redirects=False).post(f"/counterparties/{cid}", data={
        "vat": "990000106", "country": "GR", "name": "ΠΕΛΑΤΗΣ Α", "postal_code": "", "city": "", "notes": "πελάτης",
        "separate_totals": "on", "exp_category": "", "exp_e3": "", "exp_deductible": "", "exp_inv_type": "",
        "inc_category": "", "inc_e3": ""})
    assert resp.status_code == 303
    cp = get_counterparty(db, cid)
    assert cp.name == "ΠΕΛΑΤΗΣ Α" and cp.separate_totals and cp.notes == "πελάτης" and cp.defaults == {}

def test_άγνωστο_id_404(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    assert TestClient(app).get("/counterparties/999").status_code == 404

def _options(html, select_id):
    start = html.index(f'<select id="{select_id}"')
    return re.findall(r'<option value="([^"]*)"', html[start:html.index("</select>", start)])

def test_φόρμα_δείχνει_σε_κάθε_πλευρά_μόνο_τους_κωδικούς_της(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    html = TestClient(app).get("/counterparties/new").text
    assert _options(html, "exp_category") == ["", "category2_3", "category2_4", "category2_5", "category2_8"]
    assert _options(html, "exp_e3") == ["", "E3_585_009", "E3_585_010", "E3_585_016", "E3_587"]
    assert _options(html, "inc_category") == ["", "category1_3"]
    assert _options(html, "inc_e3") == ["", "E3_561_001"]

def test_αποθηκευμένος_κωδικός_άλλης_πλευράς_μένει_επιλεγμένος(monkeypatch, db, db_cfg, taxpayer):
    # Αν χανόταν από τη φόρμα, μια αποθήκευση χωρίς αλλαγές θα έσβηνε σιωπηλά την προεπιλογή.
    cid = ensure_counterparty(db, taxpayer.id, "A", "Άλφα")
    save_default(db, cid, "expense", "category1_3", "E3_561_001", True); db.commit()
    _wire(monkeypatch, db_cfg)
    html = TestClient(app).get(f"/counterparties/{cid}").text
    assert '<option value="category1_3" selected>' in html and '<option value="E3_561_001" selected>' in html

# ── Συμπλήρωση από VIES ────────────────────────────────────────────────────

from esoda_exoda.vies import ViesError, ViesResult

GR_COMPANY = ViesResult(True, "ΒΗΤΑ — ΠΡΟΜΗΘΕΥΤΗΣ Β ΑΝΩΝΥΜΗ ΕΤΑΙΡΕΙΑ", "10003", "ΓΑΜΜΑΠΟΛΗ")
_EMPTY_FORM = {"vat": "", "country": "GR", "name": "", "postal_code": "", "city": "", "notes": "",
               "exp_category": "", "exp_e3": "", "exp_deductible": "", "exp_inv_type": "",
               "inc_category": "", "inc_e3": ""}

def _fake_vies(monkeypatch, answers):
    from esoda_exoda.web import counterparty_routes
    calls = []
    def lookup(country, vat):
        calls.append((country, vat))
        a = answers[vat]
        if isinstance(a, Exception):
            raise a
        return a
    monkeypatch.setattr(counterparty_routes, "vies_lookup", lookup)
    return calls

def test_vies_στη_φόρμα_συμπληρώνει_μόνο_τα_κενά_και_δεν_αποθηκεύει(monkeypatch, db, db_cfg, taxpayer):
    cid = ensure_counterparty(db, taxpayer.id, "090000113"); db.commit()
    _wire(monkeypatch, db_cfg); calls = _fake_vies(monkeypatch, {"090000113": GR_COMPANY})
    resp = TestClient(app).post(f"/counterparties/{cid}/vies",
                                data={**_EMPTY_FORM, "vat": "090000113", "city": "ΔΕΛΤΑΠΟΛΗ"})
    assert resp.status_code == 200 and calls == [("GR", "090000113")]
    assert f'value="{GR_COMPANY.name}"' in resp.text and 'value="10003"' in resp.text
    assert 'value="ΔΕΛΤΑΠΟΛΗ"' in resp.text and "ΓΑΜΜΑΠΟΛΗ" not in resp.text
    assert f'action="/counterparties/{cid}"' in resp.text
    assert get_counterparty(db, cid).name == ""

def test_vies_στη_φόρμα_νέου_δεν_δημιουργεί_αντισυμβαλλόμενο(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg); _fake_vies(monkeypatch, {"090000113": GR_COMPANY})
    resp = TestClient(app).post("/counterparties/vies", data={**_EMPTY_FORM, "vat": "090000113"})
    assert resp.status_code == 200 and f'value="{GR_COMPANY.name}"' in resp.text
    assert 'action="/counterparties"' in resp.text and find_by_vat(db, taxpayer.id, "090000113") is None

def test_vies_στη_φόρμα_λέει_όταν_δεν_βρέθηκε_ή_δεν_απάντησε(monkeypatch, db, db_cfg, taxpayer):
    _wire(monkeypatch, db_cfg)
    _fake_vies(monkeypatch, {"1": ViesResult(False), "2": ViesResult(True),
                             "3": ViesError("Το VIES δεν απάντησε: timed out")})
    client = TestClient(app)
    assert "δεν βρέθηκε" in client.post("/counterparties/vies", data={**_EMPTY_FORM, "vat": "1"}).text
    assert "δεν δίνει" in client.post("/counterparties/vies", data={**_EMPTY_FORM, "vat": "2"}).text
    assert "timed out" in client.post("/counterparties/vies", data={**_EMPTY_FORM, "vat": "3"}).text

def test_η_φόρμα_έχει_κουμπί_vies_που_δεν_θέλει_όνομα(monkeypatch, db, db_cfg, taxpayer):
    cid = ensure_counterparty(db, taxpayer.id, "090000113"); db.commit()
    _wire(monkeypatch, db_cfg)
    page = TestClient(app).get(f"/counterparties/{cid}").text
    assert re.search(rf'<button[^>]*formaction="/counterparties/{cid}/vies"[^>]*formnovalidate', page)
    assert 'formaction="/counterparties/vies"' in TestClient(app).get("/counterparties/new").text

def test_μαζική_συμπλήρωση_γεμίζει_μόνο_όσους_δεν_έχουν_όνομα(monkeypatch, db, db_cfg, taxpayer):
    a = ensure_counterparty(db, taxpayer.id, "090000113")
    b = ensure_counterparty(db, taxpayer.id, "800000131")
    c = ensure_counterparty(db, taxpayer.id, "990000143")
    d = ensure_counterparty(db, taxpayer.id, "990000106", "ΠΕΛΑΤΗΣ Α"); db.commit()
    _wire(monkeypatch, db_cfg)
    calls = _fake_vies(monkeypatch, {"090000113": GR_COMPANY, "800000131": ViesResult(True),
                                     "990000143": ViesError("Το VIES δεν απάντησε: MS_UNAVAILABLE")})
    assert "(3 χωρίς όνομα)" in TestClient(app).get("/counterparties").text
    resp = TestClient(app).post("/counterparties/vies-fill")
    assert resp.status_code == 200 and sorted(v for _, v in calls) == ["090000113", "800000131", "990000143"]
    company = get_counterparty(db, a)
    assert (company.name, company.postal_code, company.city) == (GR_COMPANY.name, "10003", "ΓΑΜΜΑΠΟΛΗ")
    assert get_counterparty(db, b).name == "" and get_counterparty(db, c).name == ""
    assert get_counterparty(db, d).name == "ΠΕΛΑΤΗΣ Α"
    assert "Συμπληρώθηκαν 1 από 3" in resp.text and "800000131" in resp.text
    assert "990000143" in resp.text and "MS_UNAVAILABLE" in resp.text
