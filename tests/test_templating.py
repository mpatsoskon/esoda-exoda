# ABOUTME: Tests των φίλτρων μορφοποίησης των οθονών (ποσά, ημερομηνίες, πληθυντικός).
# ABOUTME: Το ποσό που δείχνει η οθόνη πρέπει να ξαναδιαβάζεται από τον parse_amount.
import pytest
from esoda_exoda.transmit import parse_amount
from esoda_exoda.web.templating import templates

eur = templates.env.filters["eur"]

@pytest.mark.parametrize("value,shown", [
    (12.0, "12,00"),
    (0.5, "0,50"),
    (75.40, "75,40"),
    (1250.40, "1.250,40"),
    (1234567.89, "1.234.567,89"),
])
def test_eur_shows_greek_form(value, shown):
    assert eur(value) == shown

@pytest.mark.parametrize("value", [12.0, 0.5, 75.40, 1250.40, 1234567.89])
def test_what_the_screen_shows_is_read_back_the_same(value):
    """Η ηχώ της τιμής έχει νόημα μόνο αν η μορφή που εμφανίζεται είναι μορφή που
    ο parse_amount δέχεται, και δίνει την ίδια τιμή."""
    assert parse_amount(eur(value)) == value

def test_parastatika_singular_and_plural():
    p = templates.env.filters["parastatika"]
    assert p(1) == "1 παραστατικό"
    assert p(4) == "4 παραστατικά"
