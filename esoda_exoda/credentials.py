# ABOUTME: Cross-platform ανάγνωση/αποθήκευση κλειδιών myDATA (ανά περιβάλλον) και του
# ABOUTME: κωδικού της βάσης μέσω keyring (Windows Credential Manager / macOS Keychain / Secret Service).
import keyring

# Το production κρατά το αρχικό όνομα ώστε οι υπάρχουσες εγκαταστάσεις να μη χρειάζονται νέο setup.
SERVICES = {"production": "esoda-exoda-mydata", "dev": "esoda-exoda-mydata-dev"}

def _service(environment: str) -> str:
    try:
        return SERVICES[environment]
    except KeyError:
        raise ValueError(f"Άγνωστο περιβάλλον myDATA: {environment!r}") from None

def set_credentials(environment: str, user_id: str, key: str) -> None:
    svc = _service(environment)
    keyring.set_password(svc, "user-id", user_id)
    keyring.set_password(svc, "subscription-key", key)

def get_headers(environment: str) -> dict:
    svc = _service(environment)
    uid = keyring.get_password(svc, "user-id")
    key = keyring.get_password(svc, "subscription-key")
    if not uid or not key:
        raise RuntimeError(f"Λείπουν τα κλειδιά myDATA ({environment}). Τρέξε `esoda-exoda keys`.")
    return {"aade-user-id": uid, "Ocp-Apim-Subscription-Key": key}

DB_SERVICE = "esoda-exoda-db"

def set_db_password(password: str) -> None:
    keyring.set_password(DB_SERVICE, "password", password)

def get_db_password() -> str:
    pw = keyring.get_password(DB_SERVICE, "password")
    if not pw:
        raise RuntimeError("Λείπει ο κωδικός της βάσης. Τρέξε `esoda-exoda keys` "
            "(ή `esoda-exoda setup` αν δεν έχεις στήσει ακόμη).")
    return pw
