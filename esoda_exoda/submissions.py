# ABOUTME: Audit των αμετάκλητων POST στο myDATA (invoice_submission, classification_submission),
# ABOUTME: με το XML που στάλθηκε και την απάντηση. Αντικαθιστά transmissions.jsonl/classifications.jsonl.
import json
from datetime import date
from .counterparties import find_by_vat

def _iso_date(s: str):
    return date.fromisoformat(s) if s else None

def record_invoice_submission(conn, taxpayer_id: int, entry: dict, mark: str, uid: str,
                              request_xml: str, response_xml: str) -> int:
    cp = find_by_vat(conn, taxpayer_id, entry.get("issuer_vat", "")) if entry.get("issuer_vat") else None
    return conn.execute(
        "insert into invoice_submission (taxpayer_id, inv_type, series, aa, issue_date, net, issuer_vat, "
        "issuer_name, counterparty_id, mark, uid, request_xml, response_xml) "
        "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id",
        (taxpayer_id, entry.get("inv_type", ""), entry.get("series", ""), entry.get("aa", ""),
         _iso_date(entry.get("issue_date", "")), entry.get("net", 0.0), entry.get("issuer_vat", ""),
         entry.get("issuer_name", ""), cp.id if cp else None, mark, uid, request_xml, response_xml)
    ).fetchone()[0]

_INV_COLS = "at, inv_type, series, aa, issue_date, net, issuer_vat, issuer_name, mark, uid, status"

def _inv_dict(r) -> dict:
    return {"at": r[0].astimezone().replace(tzinfo=None).isoformat(timespec="seconds"),
            "inv_type": r[1], "series": r[2], "aa": r[3],
            "issue_date": r[4].isoformat() if r[4] else "", "net": float(r[5]),
            "issuer_vat": r[6], "issuer_name": r[7], "mark": r[8], "uid": r[9], "statusCode": r[10]}

def list_invoice_submissions(conn, taxpayer_id: int) -> list[dict]:
    rows = conn.execute(f"select {_INV_COLS} from invoice_submission where taxpayer_id = %s "
                        "order by at desc, id desc", (taxpayer_id,)).fetchall()
    return [_inv_dict(r) for r in rows]

def last_submission(conn, taxpayer_id: int) -> dict | None:
    out = list_invoice_submissions(conn, taxpayer_id)
    return out[0] if out else None

def record_classification_submissions(conn, taxpayer_id: int, year: int, records: list[dict],
                                      request_xml: dict, response_xml: dict) -> None:
    for r in records:
        mode = r.get("per_invoice")
        conn.execute(
            "insert into classification_submission (taxpayer_id, year, invoice_mark, classification_mark, "
            "status, errors, per_invoice, e3_type, category, amount, request_xml, response_xml) "
            "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (taxpayer_id, year, r.get("invoice_mark", ""), r.get("classification_mark", ""), r["status"],
             json.dumps(r.get("errors", []), ensure_ascii=False), mode, r.get("e3_type", ""),
             r.get("category", ""), r.get("amount"), request_xml.get(mode), response_xml.get(mode)))

def list_classification_submissions(conn, taxpayer_id: int, year: int) -> list[dict]:
    rows = conn.execute(
        "select at, invoice_mark, classification_mark, status, errors, per_invoice, e3_type, category, "
        "amount, request_xml, response_xml from classification_submission "
        "where taxpayer_id = %s and year = %s order by at desc, id desc", (taxpayer_id, year)).fetchall()
    return [{"at": r[0].astimezone().replace(tzinfo=None).isoformat(timespec="seconds"),
             "invoice_mark": r[1], "classification_mark": r[2], "status": r[3], "errors": r[4],
             "per_invoice": r[5], "e3_type": r[6], "category": r[7],
             "amount": float(r[8]) if r[8] is not None else None,
             "request_xml": r[9], "response_xml": r[10]} for r in rows]
