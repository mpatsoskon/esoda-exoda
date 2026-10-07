# ABOUTME: Ο πίνακας invoice ανά MARK και τα snapshots χαρακτηρισμού. Κάθε πηγή του myDATA
# ABOUTME: συμπληρώνει μόνο ό,τι ξέρει· τίποτα δεν διαγράφεται, τα snapshots μόνο προστίθενται.
from dataclasses import dataclass
from datetime import date
from .models import Record
from .received import ReceivedDoc, VatLine
from .classifications import SelfDeclared
from .classification_state import E3Line

def _exists(conn, taxpayer_id: int, mark: str):
    return conn.execute("select id from invoice where taxpayer_id = %s and mark = %s",
                        (taxpayer_id, mark)).fetchone()

def _insert(conn, taxpayer_id, mark, direction, issue_date, fetch_id, **cols) -> int:
    names = ["taxpayer_id", "mark", "direction", "issue_date", "first_seen_fetch_id",
             "last_seen_fetch_id"] + list(cols)
    values = [taxpayer_id, mark, direction, issue_date, fetch_id, fetch_id] + list(cols.values())
    sql = (f"insert into invoice ({', '.join(names)}) values "
           f"({', '.join(['%s'] * len(values))}) returning id")
    return conn.execute(sql, values).fetchone()[0]

def _update(conn, invoice_id: int, fetch_id: int, **cols) -> None:
    sets = ", ".join(f"{k} = %s" for k in cols) + ", last_seen_fetch_id = %s"
    conn.execute(f"update invoice set {sets} where id = %s",
                 list(cols.values()) + [fetch_id, invoice_id])

def upsert_book_record(conn, taxpayer_id: int, rec: Record, direction: str,
                       fetch_id: int, counterparty_id: int | None) -> bool:
    cols = dict(inv_type=rec.inv_type, counterpart_vat=rec.counter_vat, net=rec.net,
                vat=rec.vat, withheld=rec.withheld, gross=rec.gross, in_book=True)
    if counterparty_id is not None:
        cols["counterparty_id"] = counterparty_id
    row = _exists(conn, taxpayer_id, rec.mark)
    if row:
        _update(conn, row[0], fetch_id, **cols)
        return False
    _insert(conn, taxpayer_id, rec.mark, direction, rec.issue_date, fetch_id, **cols)
    return True

def upsert_received(conn, taxpayer_id: int, doc: ReceivedDoc, fetch_id: int,
                    counterparty_id: int | None) -> bool:
    # Το RequestDocs γράφει counterpart_vat = ο λήπτης (εμείς)· σε γραμμή που το βιβλίο εξόδων
    # είχε με τον προμηθευτή, η στήλη αλλάζει σημασία σε «λήπτης». Το χρειάζεται το classify
    # (mine = counterpart_vat == tp.afm)· το afm του εξόδου βγαίνει από issuer_vat, όχι από εδώ.
    cols = dict(inv_type=doc.inv_type, series=doc.series, aa=doc.aa, issuer_vat=doc.issuer_vat,
                issuer_name=doc.issuer_name, counterpart_vat=doc.counterpart_vat,
                fuel_invoice=doc.fuel_invoice, other_taxes=doc.other_taxes,
                stamp_duty=doc.stamp_duty, fees=doc.fees, received=True)
    if counterparty_id is not None:
        cols["counterparty_id"] = counterparty_id
    row = _exists(conn, taxpayer_id, doc.mark)
    if row:
        invoice_id = row[0]
        _update(conn, invoice_id, fetch_id, **cols)
        inserted = False
    else:
        # Το RequestDocs χωρίς βιβλίο: κρατάμε και τα ποσά, αλλιώς η γραμμή θα ήταν μηδενική
        # μέχρι να έρθει το RequestMyExpenses.
        invoice_id = _insert(conn, taxpayer_id, doc.mark, "expense", doc.date, fetch_id,
                             net=doc.net, vat=doc.vat, gross=doc.net + doc.vat, **cols)
        inserted = True
    conn.execute("delete from invoice_line where invoice_id = %s", (invoice_id,))
    for i, line in enumerate(doc.lines, start=1):
        conn.execute(
            "insert into invoice_line (invoice_id, line_number, net, vat_category, vat_amount, "
            "vat_exemption_category) values (%s, %s, %s, %s, %s, %s)",
            (invoice_id, line.line_number or i, line.net, line.vat_category, line.vat_amount,
             line.vat_exemption_category))
    return inserted

def upsert_self_declared(conn, taxpayer_id: int, sd: SelfDeclared, fetch_id: int,
                         counterparty_id: int | None) -> bool:
    cols = dict(inv_type=sd.inv_type, series=sd.series, aa=sd.aa, issuer_vat=sd.issuer_vat,
                uid=sd.uid, cancelled_by_mark=sd.cancelled_by, self_declared=True)
    if counterparty_id is not None:
        cols["counterparty_id"] = counterparty_id
    row = _exists(conn, taxpayer_id, sd.mark)
    if row:
        _update(conn, row[0], fetch_id, **cols)
        return False
    _insert(conn, taxpayer_id, sd.mark, "expense", sd.date, fetch_id,
            net=sd.net, vat=sd.vat, gross=sd.net + sd.vat, **cols)
    return True

def set_headers(conn, taxpayer_id: int, headers: dict[str, tuple[str, str]]) -> None:
    """Σειρά/ΑΑ από το invoiceHeader των TransmittedDocs/RequestDocs, μόνο σε γραμμές που
    υπάρχουν: το βιβλίο είναι η αρχή για το τι ανήκει στα βιβλία."""
    for mark, (series, aa) in headers.items():
        conn.execute(
            "update invoice set series = %s, aa = %s where taxpayer_id = %s and mark = %s",
            (series, aa, taxpayer_id, mark))

def add_snapshot(conn, taxpayer_id: int, mark: str, source: str, fetch_id: int,
                 issue_date: date | None, lines=(), codes: dict[str, float] | None = None) -> int:
    sid = conn.execute(
        "insert into classification_snapshot (taxpayer_id, mark, source, fetch_id, issue_date) "
        "values (%s, %s, %s, %s, %s) returning id",
        (taxpayer_id, mark, source, fetch_id, issue_date)).fetchone()[0]
    for kind, category, e3_type, value in lines:
        conn.execute(
            "insert into classification_line (snapshot_id, kind, category, e3_type, value) "
            "values (%s, %s, %s, %s, %s)", (sid, kind, category, e3_type, value))
    for code, value in (codes or {}).items():
        conn.execute("insert into vat_code_line (snapshot_id, code, value) values (%s, %s, %s)",
                     (sid, code, value))
    return sid

@dataclass(frozen=True)
class CurrentClassification:
    source: str
    kind: str
    category: str
    e3_type: str

@dataclass
class InvoiceRow:
    mark: str
    direction: str
    inv_type: str
    issue_date: date
    series: str
    aa: str
    issuer_vat: str
    counterpart_vat: str
    counterparty_id: int | None
    net: float
    vat: float
    withheld: float
    in_book: bool
    self_declared: bool
    cancelled_by_mark: str
    transmitted: CurrentClassification | None
    e3_lines: list[E3Line]

@dataclass(frozen=True)
class SelfDeclaredRef:
    inv_type: str
    aa: str
    date: date

@dataclass(frozen=True)
class SelfDeclaredDoc:
    """Αυτο-δηλωμένο παραστατικό όπως το χρειάζονται οι έλεγχοι πριν τη διαβίβαση."""
    inv_type: str
    series: str
    aa: str
    issue_date: date
    net: float
    issuer_vat: str
    cancelled: bool

# «Ισχύει τώρα» (Φάση 6, απόφαση α): το τρέχον snapshot ενός MARK είναι εκείνο του νεότερου
# mydata_fetch της ίδιας μεθόδου που κάλυψε την ημερομηνία του. Αν ένα νεότερο τέτοιο fetch
# ΔΕΝ έφερε το MARK (η ΑΑΔΕ το ακύρωσε ή διαγράφηκε ο χαρακτηρισμός), το παλιό snapshot παύει
# να είναι τρέχον — δεν «κολλάει» για πάντα, όπως θα έκανε ένα σκέτο «νεότερο snapshot ανά
# (mark, source)». Το transmitted_docs έχει issue_date/date_from/date_to NULL (φέρνει όλο το
# ιστορικό), οπότε «καλύπτει» πάντα· το fetched_at μπορεί να συμπέσει μέσα στην ίδια ανανέωση,
# γι' αυτό και το id ως δεύτερο κριτήριο.
_CURRENT = (
    "select distinct on (s.mark, s.source) s.id, s.mark, s.source, s.issue_date "
    "from classification_snapshot s join mydata_fetch f on f.id = s.fetch_id "
    "where s.taxpayer_id = %s and not exists ("
    "  select 1 from mydata_fetch f2 where f2.taxpayer_id = s.taxpayer_id "
    "    and f2.method = f.method and f2.fetched_at > f.fetched_at "
    "    and (f2.date_from is null or s.issue_date is null or f2.date_from <= s.issue_date) "
    "    and (f2.date_to   is null or s.issue_date is null or f2.date_to   >= s.issue_date)) "
    "order by s.mark, s.source, f.fetched_at desc, s.id desc")

def _range(year: int, month: int | None) -> tuple[date, date]:
    import calendar
    if month is None:
        return date(year, 1, 1), date(year, 12, 31)
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])

def _current_lines(conn, taxpayer_id: int, marks: list[str]) -> dict[tuple[str, str], list]:
    """(mark, source) → γραμμές του τρέχοντος snapshot, ως tuples (kind, category, e3_type, value)."""
    if not marks:
        return {}
    rows = conn.execute(
        f"with cur as ({_CURRENT}) "
        "select cur.mark, cur.source, l.kind, l.category, l.e3_type, l.value "
        "from cur join classification_line l on l.snapshot_id = cur.id "
        "where cur.mark = any(%s) order by l.id", (taxpayer_id, marks)).fetchall()
    out: dict[tuple[str, str], list] = {}
    for mark, source, kind, category, e3_type, value in rows:
        out.setdefault((mark, source), []).append(
            (kind, category, e3_type, float(value) if value is not None else 0.0))
    return out

def invoices_in_range(conn, taxpayer_id: int, year: int, month: int | None = None) -> list[InvoiceRow]:
    lo, hi = _range(year, month)
    rows = conn.execute(
        "select mark, direction, inv_type, issue_date, series, aa, issuer_vat, counterpart_vat, "
        "counterparty_id, net, vat, withheld, in_book, self_declared, cancelled_by_mark "
        "from invoice where taxpayer_id = %s and issue_date between %s and %s "
        "order by issue_date, series, aa", (taxpayer_id, lo, hi)).fetchall()
    lines = _current_lines(conn, taxpayer_id, [r[0] for r in rows])
    out = []
    for r in rows:
        mark = r[0]
        tr = lines.get((mark, "transmitted_docs"))
        transmitted = CurrentClassification("transmitted_docs", *tr[0][:3]) if tr else None
        e3 = [E3Line(mark, r[3], cat, e3t, val) for kind, cat, e3t, val in lines.get((mark, "e3_info"), [])
              if cat.startswith("category2_")]
        out.append(InvoiceRow(mark, r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8],
                              float(r[9]), float(r[10]), float(r[11]), r[12], r[13], r[14],
                              transmitted, e3))
    return out

def official_vat_by_month(conn, taxpayer_id: int, year: int) -> dict[int, dict[str, float]]:
    rows = conn.execute(
        f"with cur as ({_CURRENT}) "
        "select extract(month from cur.issue_date)::int, v.code, sum(v.value) "
        "from cur join vat_code_line v on v.snapshot_id = cur.id "
        "where cur.source = 'vat_info' and cur.issue_date between %s and %s "
        "group by 1, 2", (taxpayer_id, date(year, 1, 1), date(year, 12, 31))).fetchall()
    out: dict[int, dict[str, float]] = {}
    for month, code, value in rows:
        out.setdefault(month, {})[code] = round(float(value), 2)
    return out

def received_docs_of_month(conn, taxpayer_id: int, year: int, month: int) -> list[ReceivedDoc]:
    lo, hi = _range(year, month)
    rows = conn.execute(
        "select id, mark, issuer_vat, issuer_name, counterpart_vat, series, aa, issue_date, inv_type, "
        "fuel_invoice, net, vat, other_taxes, stamp_duty, fees from invoice "
        "where taxpayer_id = %s and received and issue_date between %s and %s "
        "order by issue_date, series, aa", (taxpayer_id, lo, hi)).fetchall()
    out = []
    for r in rows:
        lines = conn.execute(
            "select net, vat_category, vat_amount, vat_exemption_category, line_number "
            "from invoice_line where invoice_id = %s order by line_number", (r[0],)).fetchall()
        out.append(ReceivedDoc(
            mark=r[1], issuer_vat=r[2], issuer_name=r[3], counterpart_vat=r[4], series=r[5],
            aa=r[6], date=r[7], inv_type=r[8], fuel_invoice=r[9], net=float(r[10]),
            vat=float(r[11]), other_taxes=float(r[12]), stamp_duty=float(r[13]), fees=float(r[14]),
            lines=[VatLine(float(l[0]), l[1], float(l[2]), l[3], l[4]) for l in lines]))
    return out

def current_expense_lines(conn, taxpayer_id: int, marks: list[str]) -> dict[str, list[E3Line]]:
    """Ίδια σημασιολογία με classification_state.expense_lines: μόνο MARK με τουλάχιστον
    μία γραμμή category2_*, και μόνο αυτές τις γραμμές."""
    dates = dict(conn.execute(
        f"with cur as ({_CURRENT}) select mark, issue_date from cur where source = 'e3_info'",
        (taxpayer_id,)).fetchall())
    lines = _current_lines(conn, taxpayer_id, list(marks))
    out: dict[str, list[E3Line]] = {}
    for (mark, source), items in lines.items():
        if source != "e3_info":
            continue
        exp = [E3Line(mark, dates.get(mark), cat, e3t, val) for kind, cat, e3t, val in items
               if cat.startswith("category2_")]
        if exp:
            out[mark] = exp
    return out

def self_declared_of_year(conn, taxpayer_id: int, year: int) -> list[SelfDeclaredRef]:
    rows = conn.execute(
        "select inv_type, aa, issue_date from invoice where taxpayer_id = %s and self_declared "
        "and issue_date between %s and %s", (taxpayer_id, date(year, 1, 1), date(year, 12, 31))).fetchall()
    return [SelfDeclaredRef(*r) for r in rows]

def self_declared_since(conn, taxpayer_id: int, since: date) -> list[SelfDeclaredDoc]:
    rows = conn.execute(
        "select inv_type, series, aa, issue_date, net, issuer_vat, cancelled_by_mark <> '' "
        "from invoice where taxpayer_id = %s and self_declared and issue_date >= %s "
        "order by issue_date", (taxpayer_id, since)).fetchall()
    return [SelfDeclaredDoc(t, s, a, d, float(n), v, c) for t, s, a, d, n, v, c in rows]

def counterparty_names(conn, taxpayer_id: int) -> dict[str, str]:
    return dict(conn.execute(
        "select vat, name from counterparty where taxpayer_id = %s and name <> ''",
        (taxpayer_id,)).fetchall())
