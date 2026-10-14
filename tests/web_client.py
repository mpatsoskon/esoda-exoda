# ABOUTME: TestClient που μιλά όπως ο browser του χρήστη: Host 127.0.0.1:8000 και Origin της
# ABOUTME: ίδιας σελίδας, ώστε τα tests να περνούν από τον φύλακα προέλευσης όπως η εφαρμογή.
from fastapi.testclient import TestClient
from esoda_exoda.web.app import app

LOCAL = "http://127.0.0.1:8000"

def local_client(*, headers: dict | None = None, **kw) -> TestClient:
    return TestClient(app, base_url=LOCAL, headers={"Origin": LOCAL, **(headers or {})}, **kw)
