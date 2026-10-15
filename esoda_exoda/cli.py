# ABOUTME: Γραμμή εντολών: χωρίς όρισμα σηκώνει την εφαρμογή· `setup` καταχωρεί τον
# ABOUTME: φορολογούμενο, το περιβάλλον myDATA και τα κλειδιά (keyring) μία φορά· `keys`
# ABOUTME: ξαναδίνει μόνο τα κλειδιά σε υπάρχουσα εγκατάσταση.
import argparse
import dataclasses
import getpass
from . import credentials
from .config import load_config
from .db import DbUnavailable, connect, dsn_from_parts, migrate
from .taxpayers import (ENVIRONMENTS, TaxpayerError, create_taxpayer, current_taxpayer,
                        is_valid_afa)

def _serve(port: int = 8000) -> None:
    import uvicorn
    uvicorn.run("esoda_exoda.web.app:app", host="127.0.0.1", port=port)
