# Έσοδα-Έξοδα myDATA

> *English:* A local web app for Greek freelancers: it downloads income/expense books from
> AADE's myDATA, helps classify expenses, transmits invoice types 13.3/14.x/17.2, and builds
> the E3 and VAT summaries. Greek-language UI and docs. AGPL-3.0.

Τοπική εφαρμογή για ελεύθερους επαγγελματίες: κατεβάζει τα βιβλία εσόδων-εξόδων από το myDATA,
βοηθά στον χαρακτηρισμό των εξόδων, διαβιβάζει παραστατικά (13.3, 14.x, 17.2) και φτιάχνει τις
συνόψεις Ε3 και ΦΠΑ. Τρέχει στον υπολογιστή σου· τα δεδομένα μένουν σε μια τοπική Postgres.

> **⚠️ Προσοχή**
> - Κάθε διαβίβαση στο **production** myDATA είναι **αμετάκλητη**.
> - Το εργαλείο **δεν αντικαθιστά τον λογιστή σου**. Έλεγξε κάθε χαρακτηρισμό.
> - Παρέχεται **χωρίς καμία εγγύηση** (βλ. LICENSE).

## Για ποιον είναι
Ελεύθεροι επαγγελματίες **παροχής υπηρεσιών** με **απλογραφικά** βιβλία. Οι κωδικοί Ε3 και τα
έτοιμα πρότυπα (κοινόχρηστα 13.3, αποσβέσεις 17.2) είναι ρυθμισμένα γι' αυτή την περίπτωση.
Άλλη δραστηριότητα; Δες «Θέλουμε τη βοήθειά σου».

## Τι χρειάζεσαι
- Python 3.11 ή νεότερη
- Docker (για την Postgres)
- Κλειδιά myDATA REST API (user id + subscription key) — για δοκιμές, από το δοκιμαστικό
  περιβάλλον της ΑΑΔΕ (δωρεάν εγγραφή, [φόρμα εγγραφής](https://www.aade.gr/en/mydata-electronic-books/mydata/test-environment))· για πραγματική χρήση, από το myAADE.

## Εγκατάσταση
1. `git clone https://github.com/mpatsoskon/esoda-exoda && cd esoda-exoda`
2. Όρισε δικό σου κωδικό βάσης και σήκωσε την Postgres:
   `POSTGRES_PASSWORD=<κωδικός> docker compose up -d`
   (PowerShell: `$env:POSTGRES_PASSWORD='<κωδικός>'; docker compose up -d`)
   (χωρίς αυτό, ο κωδικός είναι ο δοκιμαστικός `esoda-dev`· η βάση ακούει μόνο στο 127.0.0.1).
   Ο κωδικός ισχύει μόνο όταν δημιουργείται το volume την πρώτη φορά· μετά δεν αλλάζει από εδώ.
3. `python -m venv .venv`, ενεργοποίησέ το, και `pip install -e .`
4. `esoda-exoda setup` — ρωτά κωδικό βάσης, ΑΦΜ, επωνυμία, ΤΚ, πόλη, περιβάλλον
   (`dev` ή `production`) και τα κλειδιά myDATA. Τα κλειδιά αποθηκεύονται στο keyring του
   λειτουργικού (Windows Credential Manager / macOS Keychain / Secret Service), όχι σε αρχείο.
   Αν άλλαξαν τα κλειδιά myDATA ή ο κωδικός της βάσης (ή σε νέο υπολογιστή): `esoda-exoda keys`.
5. `esoda-exoda` και άνοιξε το http://127.0.0.1:8000

## Δοκιμαστικό ή πραγματικό myDATA
Το περιβάλλον επιλέγεται μία φορά στο `setup` και δένεται με τη βάση. Ξεκίνα με `dev`.
Για να έχεις και τα δύο, φτιάξε δεύτερη βάση και δεύτερο config με άλλο `dbname`, και δείξε το
με τη μεταβλητή `ESODA_EXODA_CONFIG=<path>`. Η μπάρα στην κορυφή κάθε σελίδας δείχνει σε ποιο
περιβάλλον βρίσκεσαι.

## Θέλουμε τη βοήθειά σου
Το εργαλείο φτιάχτηκε για μία συγκεκριμένη περίπτωση. Αν είσαι ελεύθερος επαγγελματίας με άλλη
δραστηριότητα (πώληση αγαθών, άλλοι κωδικοί Ε3, άλλοι τύποι παραστατικών), άνοιξε ένα issue
«Νέα περίπτωση επαγγελματία». Για κώδικα, δες το [CONTRIBUTING.md](CONTRIBUTING.md) και το
[ARCHITECTURE.md](ARCHITECTURE.md). Ερωτήσεις χρήσης στα Discussions.

**Ποτέ μη βάζεις πραγματικούς ΑΦΜ, MARK ή ποσά σε issues, PR ή συζητήσεις.**

## Άδεια
[AGPL-3.0-or-later](LICENSE). Οι γραμματοσειρές IBM Plex διανέμονται με την
[SIL OFL 1.1](esoda_exoda/web/static/fonts/OFL.txt).
