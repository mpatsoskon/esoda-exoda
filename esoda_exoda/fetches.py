# ABOUTME: Αρχείο ωμών απαντήσεων του myDATA (mydata_fetch): τι ζητήσαμε, πότε, τι πήραμε.
# ABOUTME: Επιτρέπει επανα-parsing χωρίς νέα κλήση και δίνει την «τελευταία ανανέωση».
import calendar
from datetime import date, datetime

def store_fetch(conn, taxpayer_id: int, method: str, date_from: date | None,
                date_to: date | None, body: str) -> int:
    return conn.execute(
        "insert into mydata_fetch (taxpayer_id, method, date_from, date_to, body) "
        "values (%s, %s, %s, %s, %s) returning id",
        (taxpayer_id, method, date_from, date_to, body)).fetchone()[0]

def has_fetched(conn, taxpayer_id: int, method: str) -> bool:
    return conn.execute(
        "select 1 from mydata_fetch where taxpayer_id = %s and method = %s limit 1",
        (taxpayer_id, method)).fetchone() is not None

def refresh_dates(conn, taxpayer_id: int, year: int) -> dict[int, datetime]:
    """Ένας μήνας μετράει ανανεωμένος μόνο αν ένα RequestMyExpenses τον κάλυψε ολόκληρο:
    μερική κάλυψη θα έδειχνε φρέσκο έναν μήνα με μισά παραστατικά."""
    rows = conn.execute(
        "select date_from, date_to, fetched_at from mydata_fetch "
        "where taxpayer_id = %s and method = 'RequestMyExpenses' and date_from is not null",
        (taxpayer_id,)).fetchall()
    out: dict[int, datetime] = {}
    for m in range(1, 13):
        first = date(year, m, 1)
        last = date(year, m, calendar.monthrange(year, m)[1])
        hits = [at for df, dt, at in rows if df <= first and dt >= last]
        if hits:
            out[m] = max(hits)
    return out
