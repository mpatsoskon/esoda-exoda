# ABOUTME: Tests credentials με mock στο keyring — δεν αγγίζεται το πραγματικό
# ABOUTME: Credential Manager του συστήματος. Κλειδιά χωριστά ανά περιβάλλον myDATA.
import pytest
from esoda_exoda import credentials

def _store(monkeypatch, store):
    monkeypatch.setattr(credentials.keyring, "get_password",
                        lambda svc, name: store.get((svc, name)))

def test_production_διαβάζει_το_υπάρχον_service(monkeypatch):
    # Η υπάρχουσα εγκατάσταση έχει τα κλειδιά της εδώ· δεν ζητάμε νέο setup.
    _store(monkeypatch, {("esoda-exoda-mydata", "user-id"): "u1",
                         ("esoda-exoda-mydata", "subscription-key"): "k1"})
    assert credentials.get_headers("production") == {
        "aade-user-id": "u1", "Ocp-Apim-Subscription-Key": "k1"}

def test_dev_διαβάζει_μόνο_το_dev_service(monkeypatch):
    _store(monkeypatch, {("esoda-exoda-mydata", "user-id"): "u1",
                         ("esoda-exoda-mydata", "subscription-key"): "k1"})
    with pytest.raises(RuntimeError, match="esoda-exoda keys"):
        credentials.get_headers("dev")

def test_άγνωστο_περιβάλλον_σκάει(monkeypatch):
    _store(monkeypatch, {})
    with pytest.raises(ValueError):
        credentials.get_headers("prod")

def test_set_credentials_γράφει_στο_service_του_περιβάλλοντος(monkeypatch):
    stored = {}
    monkeypatch.setattr(credentials.keyring, "set_password",
                        lambda svc, name, val: stored.__setitem__((svc, name), val))
    credentials.set_credentials("dev", "u1", "k1")
    assert stored == {("esoda-exoda-mydata-dev", "user-id"): "u1",
                      ("esoda-exoda-mydata-dev", "subscription-key"): "k1"}
