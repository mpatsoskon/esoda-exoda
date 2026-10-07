# ABOUTME: Parsing του myDATA RequestedBookInfo XML (με σελιδοποίηση) σε
# ABOUTME: κανονικοποιημένες εγγραφές Record — αγνοεί το XML namespace.
from datetime import date
import xml.etree.ElementTree as ET
from .models import Record

PAGE_BREAK = "<!-- PAGE BREAK -->"

def _local(tag: str) -> str:
    return tag.split("}")[-1]

def _text(elem, name, default="0"):
    for child in elem:
        if _local(child.tag) == name:
            return (child.text or "").strip()
    return default

def parse_book(xml_text: str) -> list[Record]:
    records: list[Record] = []
    for page in xml_text.split(PAGE_BREAK):
        page = page.strip()
        if not page:
            continue
        root = ET.fromstring(page)
        for bi in root.iter():
            if _local(bi.tag) != "bookInfo":
                continue
            issue_date = _text(bi, "issueDate", "")
            mark = _text(bi, "minMark", "") or "(άγνωστο)"
            if not issue_date:
                raise ValueError(f"Απόν issueDate σε bookInfo με MARK {mark}")
            try:
                parsed_date = date.fromisoformat(issue_date)
            except ValueError:
                raise ValueError(
                    f"Μη έγκυρο issueDate '{issue_date}' σε bookInfo με MARK {mark}") from None
            records.append(Record(
                counter_vat=_text(bi, "counterVatNumber", ""),
                issue_date=parsed_date,
                inv_type=_text(bi, "invType", ""),
                net=float(_text(bi, "netValue")),
                vat=float(_text(bi, "vatAmount")),
                withheld=float(_text(bi, "withheldAmount")),
                gross=float(_text(bi, "grossValue")),
                mark=_text(bi, "minMark", ""),
            ))
    return records
