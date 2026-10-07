# ABOUTME: Tests του taxpayers.py — μία γραμμή φορολογούμενου, περιβάλλον myDATA,
# ABOUTME: και έλεγχος ψηφίου ελέγχου ΑΦΜ.
import psycopg
import pytest
from esoda_exoda.taxpayers import (TaxpayerError, create_taxpayer, current_taxpayer,
                                   is_valid_afm)

def test_create_και_current(db):
    t = create_taxpayer(db, "123456783", environment="dev", postal_code="10000", city="ΔΕΛΤΑΠΟΛΗ")
    assert t == current_taxpayer(db)
    assert t.afm == "123456783" and t.city == "ΔΕΛΤΑΠΟΛΗ" and t.environment == "dev"

def test_create_χωρίς_περιβάλλον_δεν_επιτρέπεται(db):
    with pytest.raises(TypeError):
        create_taxpayer(db, "123456783")

def test_η_βάση_αρνείται_άγνωστο_περιβάλλον(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        create_taxpayer(db, "123456783", environment="prod")

def test_η_βάση_αρνείται_γραμμή_χωρίς_περιβάλλον(db):
    with pytest.raises(psycopg.errors.NotNullViolation):
        db.execute("insert into taxpayer (afm) values ('123456783')")

def test_current_χωρίς_γραμμή_λέει_τι_να_κάνεις(db):
    with pytest.raises(TaxpayerError) as e:
        current_taxpayer(db)
    assert "esoda-exoda setup" in str(e.value)

def test_current_με_δύο_γραμμές_αρνείται(db):
    create_taxpayer(db, "1", environment="dev"); create_taxpayer(db, "2", environment="dev")
    with pytest.raises(TaxpayerError):
        current_taxpayer(db)

@pytest.mark.parametrize("afm", ["123456783", "090000010", "800000014"])
def test_έγκυρος_ΑΦΜ(afm):
    assert is_valid_afm(afm)

@pytest.mark.parametrize("afm", ["123456789", "12345678", "1234567830", "12345678a",
                                 "", "000000000", " 123456783", "12345678²"])
def test_άκυρος_ΑΦΜ(afm):
    assert not is_valid_afm(afm)
