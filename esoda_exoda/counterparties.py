# ABOUTME: Αντισυμβαλλόμενοι (πελάτες και προμηθευτές) ανά ΑΦΜ/χώρα, με τον
# ABOUTME: προεπιλεγμένο χαρακτηρισμό τους. Απορροφά expense_map, income_map, suppliers.toml.
import re
from dataclasses import dataclass, field

EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
      "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SE",
      "SI", "SK", "ES"}
_COUNTRY = re.compile(r"^[A-Z]{2}$")

class CounterpartyError(ValueError):
    pass

@dataclass(frozen=True)
class ClassificationDefault:
    direction: str
    category_code: str
    e3_code: str
    deductible: bool | None
    inv_type: str = ""

@dataclass
class Counterparty:
    id: int | None
    taxpayer_id: int
    vat: str
    country: str = "GR"
    name: str = ""
    postal_code: str = ""
    city: str = ""
    notes: str = ""
    separate_totals: bool = False
    defaults: dict[str, ClassificationDefault] = field(default_factory=dict)

@dataclass(frozen=True)
class ForeignSupplier:
    """Ό,τι χρειάζεται το transmit.build_xml_14 — ίδια πεδία με τον παλιό Supplier."""
    name: str
    vat: str
    country: str
    postal_code: str
    city: str
    inv_type: str
    e3: str
    category: str

    @property
    def vat_classification(self) -> str:
        return "VAT_365" if self.inv_type == "14.3" else "VAT_366"

def validate(cp: Counterparty) -> None:
    for name_, value in (("vat", cp.vat), ("name", cp.name), ("postal_code", cp.postal_code),
                         ("city", cp.city), ("notes", cp.notes)):
        # Χαρακτήρας ελέγχου θα κατέληγε αυτούσιος στο XML μιας αμετάκλητης διαβίβασης.
        if any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
            raise CounterpartyError(f"Πεδίο {name_}: δεν επιτρέπονται χαρακτήρες ελέγχου "
                                    "(π.χ. αλλαγή γραμμής)")
    if not cp.vat.strip():
        raise CounterpartyError("Κενό πεδίο: vat")
    if not cp.name.strip():
        raise CounterpartyError("Κενό πεδίο: name")
    if not _COUNTRY.match(cp.country):
        raise CounterpartyError(f"Χώρα «{cp.country}»: χρειάζεται κωδικός ISO δύο κεφαλαίων "
                                "γραμμάτων, π.χ. NL ή US")
    d = cp.defaults.get("expense")
    inv_type = d.inv_type if d else ""
    if inv_type:
        if inv_type not in ("14.3", "14.4"):
            raise CounterpartyError(f"inv_type «{inv_type}»: μόνο 14.3 ή 14.4")
        if cp.country == "GR":
            raise CounterpartyError("Χώρα GR δεν επιτρέπεται σε προμηθευτή εξωτερικού")
        if not cp.postal_code.strip() or not cp.city.strip():
            raise CounterpartyError("Προμηθευτής εξωτερικού θέλει ΤΚ και πόλη — μπαίνουν στο XML")
        if inv_type == "14.3" and cp.country not in EU:
            raise CounterpartyError(f"Το 14.3 θέλει χώρα ΕΕ — η {cp.country} δεν είναι")
        if inv_type == "14.4" and cp.country in EU:
            raise CounterpartyError(f"Το 14.4 θέλει χώρα εκτός ΕΕ — η {cp.country} είναι ΕΕ")

_COLS = "id, taxpayer_id, vat, country, name, postal_code, city, notes, separate_totals"

def _defaults(conn, cp_id: int) -> dict[str, ClassificationDefault]:
    rows = conn.execute(
        "select direction, category_code, e3_code, deductible, inv_type "
        "from classification_default where counterparty_id = %s", (cp_id,)).fetchall()
    return {r[0]: ClassificationDefault(*r) for r in rows}

def _load(conn, row) -> Counterparty:
    cp = Counterparty(*row)
    cp.defaults = _defaults(conn, cp.id)
    return cp

def get_counterparty(conn, cp_id: int) -> Counterparty | None:
    row = conn.execute(f"select {_COLS} from counterparty where id = %s", (cp_id,)).fetchone()
    return _load(conn, row) if row else None

def find_by_vat(conn, taxpayer_id: int, vat: str) -> Counterparty | None:
    row = conn.execute(
        f"select {_COLS} from counterparty where taxpayer_id = %s and vat = %s "
        "order by id limit 1", (taxpayer_id, vat)).fetchone()
    return _load(conn, row) if row else None

def ensure_counterparty(conn, taxpayer_id: int, vat: str, name: str = "",
                        country: str = "GR") -> int:
    """Η ανανέωση δημιουργεί αντισυμβαλλόμενους αλλά δεν πατάει πάνω σε χειρόγραφη διόρθωση.
    Εξαίρεση: αν το όνομα είναι ακόμη κενό (ο ΑΦΜ ήρθε πρώτα από το βιβλίο, χωρίς όνομα) και
    τώρα έρχεται όνομα από το RequestDocs, το συμπληρώνουμε — αλλιώς σχεδόν κανένας ΑΦΜ του
    βιβλίου δεν θα αποκτούσε ποτέ όνομα."""
    found = find_by_vat(conn, taxpayer_id, vat)
    if found:
        if name and not found.name:
            conn.execute("update counterparty set name = %s where id = %s", (name, found.id))
        return found.id
    return conn.execute(
        "insert into counterparty (taxpayer_id, vat, country, name) values (%s, %s, %s, %s) "
        "returning id", (taxpayer_id, vat, country, name)).fetchone()[0]

def save_counterparty(conn, cp: Counterparty) -> int:
    validate(cp)
    if cp.id is None:
        cp.id = conn.execute(
            "insert into counterparty (taxpayer_id, vat, country, name, postal_code, city, "
            "notes, separate_totals) values (%s, %s, %s, %s, %s, %s, %s, %s) returning id",
            (cp.taxpayer_id, cp.vat, cp.country, cp.name, cp.postal_code, cp.city,
             cp.notes, cp.separate_totals)).fetchone()[0]
    else:
        conn.execute(
            "update counterparty set vat = %s, country = %s, name = %s, postal_code = %s, "
            "city = %s, notes = %s, separate_totals = %s, updated_at = now() where id = %s",
            (cp.vat, cp.country, cp.name, cp.postal_code, cp.city, cp.notes,
             cp.separate_totals, cp.id))
    for d in cp.defaults.values():
        save_default(conn, cp.id, d.direction, d.category_code, d.e3_code, d.deductible,
                     d.inv_type)
    return cp.id

def save_default(conn, counterparty_id: int, direction: str, category_code: str,
                 e3_code: str, deductible: bool | None, inv_type: str = "") -> None:
    conn.execute(
        "insert into classification_default (counterparty_id, direction, category_code, "
        "e3_code, deductible, inv_type) values (%s, %s, %s, %s, %s, %s) "
        "on conflict (counterparty_id, direction) do update set category_code = excluded."
        "category_code, e3_code = excluded.e3_code, deductible = excluded.deductible, "
        "inv_type = excluded.inv_type",
        (counterparty_id, direction, category_code, e3_code, deductible, inv_type))

def list_counterparties(conn, taxpayer_id: int) -> list[dict]:
    rows = conn.execute(
        f"select {_COLS}, "
        "  (select count(*) from invoice i where i.counterparty_id = c.id), "
        "  (select max(issue_date) from invoice i where i.counterparty_id = c.id), "
        "  exists (select 1 from invoice i where i.counterparty_id = c.id "
        "          and i.direction = 'expense'), "
        "  exists (select 1 from classification_default d where d.counterparty_id = c.id "
        "          and d.direction = 'expense') "
        "from counterparty c where taxpayer_id = %s", (taxpayer_id,)).fetchall()
    out = []
    for r in rows:
        cp = _load(conn, r[:9])
        has_expenses, has_default = r[11], r[12]
        out.append({"cp": cp, "invoices": r[9], "last_date": r[10],
                    "missing_default": has_expenses and not has_default})
    out.sort(key=lambda x: (not x["missing_default"], x["cp"].name, x["cp"].vat))
    return out

def foreign_suppliers(conn, taxpayer_id: int) -> list[tuple[int, ForeignSupplier]]:
    rows = conn.execute(
        "select c.id, c.name, c.vat, c.country, c.postal_code, c.city, d.inv_type, "
        "d.e3_code, d.category_code from counterparty c "
        "join classification_default d on d.counterparty_id = c.id and d.direction = 'expense' "
        "where c.taxpayer_id = %s and c.country <> 'GR' and d.inv_type <> '' "
        "order by c.name", (taxpayer_id,)).fetchall()
    return [(r[0], ForeignSupplier(*r[1:])) for r in rows]

def subtotal_parties(conn, taxpayer_id: int) -> list[tuple[str, str]]:
    return [tuple(r) for r in conn.execute(
        "select vat, name from counterparty where taxpayer_id = %s and separate_totals "
        "order by name", (taxpayer_id,)).fetchall()]
