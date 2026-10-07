# ABOUTME: Ενορχήστρωση ανανέωσης: 6 GET από το myDATA → mydata_fetch, invoice, counterparty,
# ABOUTME: classification_snapshot. Ο καλών δίνει τη συναλλαγή· εδώ δεν γίνεται commit.
import calendar
import functools
from datetime import date, datetime
from .books import parse_book
from .received import parse_received
from .classifications import parse_self_declared, parse_transmitted, parse_doc_headers
from .classification_state import parse_e3_info, parse_vat_info
from .counterparties import ensure_counterparty, find_by_vat
from .fetches import store_fetch
from .invoices import (add_snapshot, set_headers, upsert_book_record, upsert_received,
                       upsert_self_declared)
from .taxpayers import Taxpayer
from . import mydata_client

PAGE_BREAK = "\n<!-- PAGE BREAK -->\n"

def month_range(year: int, month: int) -> tuple[str, str]:
    """Το myDATA θέλει dd/MM/yyyy. Η τελευταία μέρα από το calendar: ένα σταθερό «31»
    θα έδινε 31/02 και άκυρη παράμετρο."""
    last = calendar.monthrange(year, month)[1]
    return f"01/{month:02d}/{year}", f"{last:02d}/{month:02d}/{year}"

def year_range(year: int) -> tuple[str, str]:
    return f"01/01/{year}", f"31/12/{year}"

def _iso(dmy: str) -> date:
    return datetime.strptime(dmy, "%d/%m/%Y").date()

class _Counter:
    def __init__(self, conn, taxpayer_id):
        self.conn, self.taxpayer_id, self.new = conn, taxpayer_id, 0
    def ensure(self, vat: str, name: str = "") -> int | None:
        if not vat:
            return None
        existed = find_by_vat(self.conn, self.taxpayer_id, vat) is not None
        cid = ensure_counterparty(self.conn, self.taxpayer_id, vat, name)
        if not existed:
            self.new += 1
        return cid

def refresh(conn, taxpayer: Taxpayer, year: int, month: int | None = None,
            fetch_xml=None) -> dict:
    # Late binding: ένα default `mydata_client.fetch_xml` θα δεσμευόταν στο import και το
    # monkeypatch των route tests (web_app.mydata_client.fetch_xml) δεν θα έπιανε — θα έτρεχε
    # το πραγματικό fetch και θα έσκαγε στο netguard. Το λύνουμε εδώ, στην κλήση.
    if fetch_xml is None:
        fetch_xml = functools.partial(mydata_client.fetch_xml, env=taxpayer.environment)
    df, dt = month_range(year, month) if month else year_range(year)
    tid = taxpayer.id
    stats = {"new_invoices": 0, "seen_invoices": 0, "snapshots": 0, "date_from": df, "date_to": dt}
    cps = _Counter(conn, tid)

    def got(method):
        body = fetch_xml(method, df, dt)
        rng = (_iso(df), _iso(dt)) if method in mydata_client.RANGE_METHODS else (None, None)
        return body, store_fetch(conn, tid, method, rng[0], rng[1], body)

    def count(inserted: bool):
        stats["new_invoices" if inserted else "seen_invoices"] += 1

    income_xml, f_inc = got("RequestMyIncome")
    for rec in parse_book(income_xml):
        count(upsert_book_record(conn, tid, rec, "income", f_inc, cps.ensure(rec.counter_vat)))

    expenses_xml, f_exp = got("RequestMyExpenses")
    for rec in parse_book(expenses_xml):
        count(upsert_book_record(conn, tid, rec, "expense", f_exp, cps.ensure(rec.counter_vat)))

    transmitted_xml, f_tr = got("RequestTransmittedDocs")
    for sd in parse_self_declared(transmitted_xml):
        # Αυτο-δηλωθέν με ξένο εκδότη (14.x): ο αντισυμβαλλόμενος είναι ο εκδότης, όχι εμείς.
        cid = cps.ensure(sd.issuer_vat) if sd.issuer_vat and sd.issuer_vat != taxpayer.afm else None
        count(upsert_self_declared(conn, tid, sd, f_tr, cid))
    for mark, cl in parse_transmitted(transmitted_xml).items():
        add_snapshot(conn, tid, mark, "transmitted_docs", f_tr, None,
                     lines=[(cl.kind, cl.category, cl.e3_type, None)])
        stats["snapshots"] += 1

    received_xml, f_rd = got("RequestDocs")
    for doc in parse_received(received_xml):
        count(upsert_received(conn, tid, doc, f_rd, cps.ensure(doc.issuer_vat, doc.issuer_name)))
    set_headers(conn, tid, parse_doc_headers(PAGE_BREAK.join((transmitted_xml, received_xml))))

    # Ο επίσημος χαρακτηρισμός ληφθέντος ΔΕΝ υπάρχει στο RequestDocs — η λίστα
    # expensesClassificationsDoc του §6.2 δεν επιστρέφεται ποτέ. Ζει στο RequestE3Info,
    # που δίνει και τα δικά μας εκδοθέντα (category1_*): το books_query κρατά τα category2_*.
    e3_xml, f_e3 = got("RequestE3Info")
    for mark, lines in parse_e3_info(e3_xml).items():
        add_snapshot(conn, tid, mark, "e3_info", f_e3, lines[0].date,
                     lines=[("income" if l.category.startswith("category1_") else "expense",
                             l.category, l.e3_type, l.value) for l in lines])
        stats["snapshots"] += 1

    vat_xml, f_vat = got("RequestVatInfo")
    for mark, info in parse_vat_info(vat_xml).items():
        add_snapshot(conn, tid, mark, "vat_info", f_vat, info.date, codes=info.codes)
        stats["snapshots"] += 1

    stats["new_counterparties"] = cps.new
    return stats
