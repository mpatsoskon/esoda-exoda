# ABOUTME: Tests παραγωγής σειρών βιβλίου από τη βάση: προτεραιότητα χαρακτηρισμού,
# ABOUTME: ΑΓΝΩΣΤΟ χωρίς απόφαση, self-declared χωρίς διπλό, golden Ιούλιος 2026.
from datetime import date
from esoda_exoda.books_query import book_rows, deductible_flag, flagged_afms, month_overview
from esoda_exoda.classifications import SelfDeclared
from esoda_exoda.counterparties import ensure_counterparty, save_default
from esoda_exoda.fetches import store_fetch
from esoda_exoda.invoices import add_snapshot, upsert_book_record, upsert_self_declared
from esoda_exoda.models import Record, UNKNOWN_DEDUCTION
from esoda_exoda.refresh import refresh
from esoda_exoda import vat

def _f(db, tp):
    return store_fetch(db, tp.id, "RequestMyExpenses", date(2026, 1, 1), date(2026, 12, 31), "")

def _exp(db, tp, f, vat_no, mark, cid=None, d=date(2026, 7, 3)):
    upsert_book_record(db, tp.id, Record(vat_no, d, "1.1", 100, 24, 0, 124, mark), "expense", f, cid)

def test_deductible_flag():
    assert deductible_flag("category2_5") == "ΌΧΙ" and deductible_flag("category2_4") == "ΝΑΙ"

def test_άγνωστος_ΑΦΜ_δεν_δηλώνεται_εκπιπτόμενος(db, db_cfg, taxpayer):
    _exp(db, taxpayer, _f(db, taxpayer), "1", "M1")
    _, exp = book_rows(db, db_cfg, taxpayer, 2026)
    assert exp[0].col_j == UNKNOWN_DEDUCTION and exp[0].flagged and exp[0].charact == ""
    assert flagged_afms([], exp) == ["1"]

def test_default_αντισυμβαλλόμενου_γεμίζει_τις_στήλες(db, db_cfg, taxpayer):
    f = _f(db, taxpayer)
    cid = ensure_counterparty(db, taxpayer.id, "1")
    save_default(db, cid, "expense", "category2_5", "E3_585_016", False)
    _exp(db, taxpayer, f, "1", "M1", cid)
    _, [row] = book_rows(db, db_cfg, taxpayer, 2026)
    assert (row.col_j, row.charact, row.category, row.kind) == (
        "ΌΧΙ", "ΝΑΙ", "2.5 Γενικά Έξοδα χωρίς δικαίωμα έκπτωσης ΦΠΑ", "Λοιπά έξοδα (E3_585_016)")
    assert not row.flagged

def test_επίσημος_χαρακτηρισμός_υπερισχύει_του_default(db, db_cfg, taxpayer):
    f = _f(db, taxpayer)
    cid = ensure_counterparty(db, taxpayer.id, "1")
    save_default(db, cid, "expense", "category2_4", "E3_585_009", True)
    _exp(db, taxpayer, f, "1", "M1", cid)
    add_snapshot(db, taxpayer.id, "M1", "e3_info", f, date(2026, 7, 3),
                 lines=[("expense", "category2_5", "E3_585_016", 100.0)])
    _, [row] = book_rows(db, db_cfg, taxpayer, 2026)
    assert row.col_j == "ΌΧΙ" and row.kind == "Λοιπά έξοδα (E3_585_016)"

def test_transmitted_υπερισχύει_του_E3Info(db, db_cfg, taxpayer):
    f = _f(db, taxpayer)
    _exp(db, taxpayer, f, "1", "M1")
    add_snapshot(db, taxpayer.id, "M1", "e3_info", f, date(2026, 7, 3), lines=[("expense", "category2_5", "E3_585_016", 100.0)])
    add_snapshot(db, taxpayer.id, "M1", "transmitted_docs", f, None, lines=[("expense", "category2_3", "E3_585_009", None)])
    _, [row] = book_rows(db, db_cfg, taxpayer, 2026)
    assert row.category == "2.3 Λήψη Υπηρεσιών" and row.col_j == "ΝΑΙ"

def test_κωδικός_χωρίς_label_μένει_κωδικός(db, db_cfg, taxpayer):
    f = _f(db, taxpayer)
    _exp(db, taxpayer, f, "1", "M1")
    add_snapshot(db, taxpayer.id, "M1", "e3_info", f, date(2026, 7, 3), lines=[("expense", "category2_9", "E3_999", 1.0)])
    _, [row] = book_rows(db, db_cfg, taxpayer, 2026)
    assert (row.category, row.kind) == ("category2_9", "E3_999")

def test_έσοδο_με_transmitted_και_χωρίς(db, db_cfg, taxpayer):
    f = store_fetch(db, taxpayer.id, "RequestMyIncome", date(2026, 1, 1), date(2026, 12, 31), "")
    cid = ensure_counterparty(db, taxpayer.id, "990000106", "ΠΕΛΑΤΗΣ Α")
    save_default(db, cid, "income", "category1_3", "E3_561_001", None)
    upsert_book_record(db, taxpayer.id, Record("990000106", date(2026, 7, 1), "2.1", 500, 120, 100, 620, "I1"), "income", f, cid)
    upsert_book_record(db, taxpayer.id, Record("5", date(2026, 7, 2), "2.1", 1, 0, 0, 1, "I2"), "income", f, None)
    add_snapshot(db, taxpayer.id, "I1", "transmitted_docs", f, None, lines=[("income", "category1_3", "E3_561_001", None)])
    inc, _ = book_rows(db, db_cfg, taxpayer, 2026)
    assert inc[0].col_j == 100.0 and inc[0].charact == "ΝΑΙ" and inc[0].type == "2.1 Τιμολόγιο Παροχής"
    assert inc[1].flagged and flagged_afms(inc, []) == ["5"]

def test_self_declared_μπαίνει_μία_φορά_και_όχι_ακυρωμένο(db, db_cfg, taxpayer):
    f = _f(db, taxpayer)
    sd = SelfDeclared(mark="S1", uid="", inv_type="17.2", series="0", aa="1", date=date(2026, 12, 31),
                      net=1250.40, vat=0, e3_type="E3_587", category="category2_8")
    upsert_self_declared(db, taxpayer.id, sd, f, None)
    upsert_self_declared(db, taxpayer.id, SelfDeclared(**{**sd.__dict__, "mark": "S2", "cancelled_by": "S3"}), f, None)
    # S1 είναι και στο βιβλίο εξόδων: μία γραμμή, όχι δύο
    upsert_book_record(db, taxpayer.id, Record("", date(2026, 12, 31), "17.2", 1250.40, 0, 0, 1250.40, "S1"), "expense", f, None)
    # Ο χαρακτηρισμός ζει σε snapshot, όχι στο upsert_self_declared: χωρίς αυτό το S1 θα ήταν ΑΓΝΩΣΤΟ.
    add_snapshot(db, taxpayer.id, "S1", "transmitted_docs", f, None, lines=[("expense", "category2_8", "E3_587", None)])
    _, exp = book_rows(db, db_cfg, taxpayer, 2026)
    assert [r.aa for r in exp] == ["1"] and exp[0].afm == taxpayer.afm
    assert exp[0].type == "17.2 Αποσβέσεις" and exp[0].kind == "Αποσβέσεις (E3_587)"

def test_μήνας_φιλτράρει(db, db_cfg, taxpayer):
    f = _f(db, taxpayer)
    _exp(db, taxpayer, f, "1", "A", d=date(2026, 7, 3)); _exp(db, taxpayer, f, "1", "B", d=date(2026, 8, 3))
    _, exp = book_rows(db, db_cfg, taxpayer, 2026, 8)
    assert [r.date.month for r in exp] == [8]

def test_month_overview(db, db_cfg, taxpayer):
    f = store_fetch(db, taxpayer.id, "RequestMyExpenses", date(2026, 7, 1), date(2026, 7, 31), "")
    _exp(db, taxpayer, f, "1", "A", d=date(2026, 7, 3)); _exp(db, taxpayer, f, "2", "B", d=date(2026, 7, 4))
    cid = ensure_counterparty(db, taxpayer.id, "2"); save_default(db, cid, "expense", "category2_4", "E3_585_016", True)
    db.execute("update invoice set counterparty_id = %s where mark = 'B'", (cid,))
    store_fetch(db, taxpayer.id, "RequestMyExpenses", date(2026, 7, 1), date(2026, 7, 31), "")
    [m] = month_overview(db, db_cfg, taxpayer, 2026)
    assert (m["month"], m["income"], m["expenses"], m["unknown"]) == (7, 0, 2, 1)
    assert m["last_refresh"] is not None

def test_golden_Ιούλιος_2026(db, db_cfg, taxpayer, fixtures_dir):
    """Πάνω στα fixtures Ιουλίου 2026: 2 χαρακτηρισμένα έξοδα, εκπιπτόμενο βιβλίων 18,00,
    επίσημο 386 = 27,60. Η ΔΙΑΦΟΡΑ είναι μη μηδενική επειδή τα fixtures δεν έχουν βιβλίο
    Ιουλίου 2026 (το 900000000001049 με 9,60 ζει μόνο στο VatInfo)."""
    files = {"RequestMyIncome": "mydata_income_2025.xml", "RequestMyExpenses": "mydata_expenses_2025.xml",
             "RequestTransmittedDocs": "mydata_transmitted_sample.xml", "RequestDocs": "mydata_received_sample.xml",
             "RequestE3Info": "mydata_e3_info_2026_07.xml", "RequestVatInfo": "mydata_vat_info_2026_07.xml"}
    refresh(db, taxpayer, 2026, 7, fetch_xml=lambda m, a, b: (fixtures_dir / files[m]).read_text(encoding="utf-8"))
    # Τα βιβλία των fixtures είναι του 2025· για τον Ιούλιο 2026 σημαδεύουμε ως in_book
    # τα ληφθέντα του μήνα, όπως θα έκανε ένα πραγματικό RequestMyExpenses του 2026.
    db.execute("update invoice set in_book = true where received and issue_date between '2026-07-01' and '2026-07-31' "
               "and counterpart_vat = %s", (taxpayer.afm,))
    inc, exp = book_rows(db, db_cfg, taxpayer, 2026, 7)
    from esoda_exoda.invoices import official_vat_by_month
    months = vat.compute(inc, exp, official_vat_by_month(db, taxpayer.id, 2026))
    july = next(m for m in months if m.month == 7)
    assert sum(1 for r in exp if r.charact == "ΝΑΙ") == 2
    assert round(july.in_vat_deductible, 2) == 18.0
    assert round(july.official_deductible, 2) == 27.6
