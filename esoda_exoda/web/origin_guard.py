# ABOUTME: Φύλακας προέλευσης: κάθε request μόνο σε Host 127.0.0.1/localhost, και κάθε μη
# ABOUTME: ασφαλές request μόνο από σελίδα της ίδιας της εφαρμογής (Sec-Fetch-Site ή Origin).
from collections.abc import Mapping
from starlette.responses import PlainTextResponse

_HOSTS = {"127.0.0.1", "localhost"}
_SAFE = {"GET", "HEAD", "OPTIONS"}
_CROSS = ("Άρνηση: το αίτημα δεν ήρθε από σελίδα της εφαρμογής. Αν το έστειλες εσύ από "
             "την εφαρμογή, κάποια επέκταση του browser αφαιρεί τα headers Origin/Sec-Fetch-Site.")

def refusal(method: str, headers: Mapping[str, str]) -> str | None:
    """None όταν το αίτημα περνά, αλλιώς ο λόγος της άρνησης.

    Host: ο server ακούει μόνο στο 127.0.0.1, αλλά με DNS rebinding μια ξένη σελίδα φτάνει
    εδώ με το δικό της hostname και διαβάζει ό,τι δείχνει η εφαρμογή. Η θύρα δεν ελέγχεται
    (το demo τρέχει σε άλλη)· την ελέγχει το Origin, που πρέπει να ταιριάζει ακριβώς.

    Προέλευση: μια ξένη σελίδα μπορεί να υποβάλει φόρμα urlencoded χωρίς preflight. Ο
    browser δηλώνει πάντα από πού προέρχεται το POST· όποιο αίτημα δεν το δηλώνει δεν το
    έστειλε η φόρμα της εφαρμογής."""
    host = headers.get("host", "")
    if host.partition(":")[0] not in _HOSTS:
        return "Άρνηση: η εφαρμογή απαντά μόνο σε 127.0.0.1 και localhost."
    if method in _SAFE:
        return None
    site = headers.get("sec-fetch-site")
    if site is not None:
        return None if site == "same-origin" else _CROSS
    origin = headers.get("origin")
    if origin is not None and origin == f"http://{host}":
        return None
    return _CROSS

async def origin_guard(request, call_next):
    reason = refusal(request.method, request.headers)
    if reason:
        return PlainTextResponse(reason, status_code=403)
    return await call_next(request)
