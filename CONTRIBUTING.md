# Συνεισφορά

Ευχαριστούμε! Λίγοι κανόνες κρατούν το project ασφαλές για όλους.

## Ο απαράβατος κανόνας
**Ποτέ πραγματικά δεδομένα** — ΑΦΜ, επωνυμίες, MARK, ποσά, διευθύνσεις — σε commits, tests,
fixtures, issues ή PR. Στα tests χρησιμοποίησε συνθετικούς ΑΦΜ με έγκυρο ψηφίο ελέγχου
(π.χ. `123456783`) και MARK που αρχίζουν από `9`. Το CI τρέχει
`python scripts/check_no_personal_data.py`.

Αν θέλεις να ελέγχεις και τα δικά σου στοιχεία πριν από κάθε commit, γράψε τα (ένα ανά γραμμή)
στο `.personal-data-terms.txt` (είναι στο `.gitignore`) και βάλε pre-commit hook:
`echo 'python scripts/check_no_personal_data.py' > .git/hooks/pre-commit` (και `chmod +x` σε Linux/macOS).

## Στήσιμο για ανάπτυξη
1. `pip install -e .[dev]`
2. `python -m pytest`

Κάθε test παίρνει δικό του προσωρινό αρχείο SQLite (`tests/conftest.py`)· δεν χρειάζεται
Docker ούτε server βάσης. Τα ποσά στη βάση είναι ακέραια λεπτά: γράψε και διάβασε τα μόνο
μέσω `db.to_cents` / `db.from_cents`.

Τα tests δεν κάνουν ποτέ κλήσεις δικτύου (το `tests/conftest.py` τις μπλοκάρει).

## myDATA
Δοκίμαζε **μόνο** στο δοκιμαστικό περιβάλλον της ΑΑΔΕ (`esoda-exoda setup` → `dev`).

## Ροή
- Ένα issue πριν από μεγάλες αλλαγές, για να συμφωνήσουμε στην προσέγγιση.
- Ένα PR ανά θέμα, με tests. Το CI πρέπει να είναι πράσινο.
- Κώδικας, σχόλια και μηνύματα commit στα ελληνικά, όπως ο υπάρχων κώδικας.
