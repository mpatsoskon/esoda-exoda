# ABOUTME: Tests του αρχείου ωμών απαντήσεων myDATA και της «τελευταίας ανανέωσης» ανά μήνα.
from datetime import date
from esoda_exoda.fetches import has_fetched, refresh_dates, store_fetch

def test_store_και_has_fetched(db, taxpayer):
    assert not has_fetched(db, taxpayer.id, "RequestTransmittedDocs")
    fid = store_fetch(db, taxpayer.id, "RequestTransmittedDocs", None, None, "<a/>")
    assert fid > 0 and has_fetched(db, taxpayer.id, "RequestTransmittedDocs")
    body = db.execute("select body from mydata_fetch where id = %s", (fid,)).fetchone()[0]
    assert body == "<a/>"

def test_refresh_dates_ανά_μήνα_που_καλύφθηκε(db, taxpayer):
    store_fetch(db, taxpayer.id, "RequestMyExpenses", date(2026, 7, 1), date(2026, 7, 31), "")
    store_fetch(db, taxpayer.id, "RequestMyExpenses", date(2026, 1, 1), date(2026, 3, 31), "")
    store_fetch(db, taxpayer.id, "RequestMyIncome", date(2026, 9, 1), date(2026, 9, 30), "")
    d = refresh_dates(db, taxpayer.id, 2026)
    assert set(d) == {1, 2, 3, 7}

def test_refresh_dates_αγνοεί_μερική_κάλυψη(db, taxpayer):
    store_fetch(db, taxpayer.id, "RequestMyExpenses", date(2026, 7, 10), date(2026, 7, 31), "")
    assert refresh_dates(db, taxpayer.id, 2026) == {}
