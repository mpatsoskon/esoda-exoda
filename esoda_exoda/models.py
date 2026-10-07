# ABOUTME: Dataclasses: Record (εγγραφή βιβλίου myDATA) και SheetRow (γραμμή Excel).
# ABOUTME: Αναπαριστά δεδομένα από myDATA και στη μορφή που θα ήταν σε ένα φύλλο εργασίας.
from dataclasses import dataclass
from datetime import date

# Η στήλη J των εξόδων είναι πρωτόκολλο μεταξύ mapping, vat και του SUMIF του Excel:
# «ΝΑΙ» εκπίπτει, «ΌΧΙ» ρητή άρνηση, «ΑΓΝΩΣΤΟ» καμία απόφαση. Μία γραφή, ένα σημείο.
UNKNOWN_DEDUCTION = "ΑΓΝΩΣΤΟ"

@dataclass
class Record:
    counter_vat: str
    issue_date: date
    inv_type: str
    net: float
    vat: float
    withheld: float
    gross: float
    mark: str

@dataclass
class SheetRow:
    type: str
    series: str
    aa: str
    date: date
    afm: str
    net: float
    vat: float
    total: float
    col_j: object          # float (ΦΟΡΟΣ) για έσοδα· "ΝΑΙ"/"ΌΧΙ"/UNKNOWN_DEDUCTION για έξοδα
    charact: str
    category: str
    kind: str
    flagged: bool = False   # True αν ο χαρακτηρισμός δεν βρέθηκε στο config
