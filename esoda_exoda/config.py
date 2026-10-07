# ABOUTME: Φόρτωση ρυθμίσεων από config.toml και resolve relative paths
# ABOUTME: σχετικά με το data_dir (πηγή αλήθειας για όλα τα paths).
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

@dataclass
class Config:
    data_dir: Path = Path(".")
    type_labels: dict = field(default_factory=dict)
    presets: dict = field(default_factory=dict)
    e3_labels: dict = field(default_factory=dict)
    category_labels: dict = field(default_factory=dict)
    e3_income: list = field(default_factory=list)
    database: dict = field(default_factory=dict)
    database_url: str = ""
    source_path: Path = Path(".")

    def resolve(self, rel: str) -> Path:
        return (self.data_dir / rel).resolve()

    def categories_for(self, direction: str) -> dict:
        prefix = {"income": "category1_", "expense": "category2_"}[direction]
        return {c: t for c, t in self.category_labels.items() if c.startswith(prefix)}

    def e3_for(self, direction: str) -> dict:
        """Η κατεύθυνση ενός κωδικού Ε3 δεν βγαίνει από το πρόθεμά του, γι' αυτό την
        ορίζει ρητά το e3_income· ό,τι δεν είναι εκεί είναι εξόδου."""
        income = {"income": True, "expense": False}[direction]
        return {c: t for c, t in self.e3_labels.items() if (c in self.e3_income) == income}

def load_config(path=None) -> Config:
    env_path = os.environ.get("ESODA_EXODA_CONFIG")
    if path:
        path = Path(path)
    elif env_path:
        path = Path(env_path)
    else:
        path = Path(__file__).resolve().parent.parent / "config.toml"
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    base = path.resolve().parent
    data_dir = (base / raw.get("data_dir", ".")).resolve()
    return Config(
        data_dir=data_dir,
        type_labels=raw.get("type_labels", {}),
        presets=raw.get("presets", {}),
        e3_labels=raw.get("e3_labels", {}),
        category_labels=raw.get("category_labels", {}),
        e3_income=raw.get("e3_income", []),
        database=raw.get("database", {}),
        source_path=path.resolve(),
    )

def code_for_label(labels: dict, label: str) -> str | None:
    """Αντίστροφη αναζήτηση: από το label που κρατά το expense_map στον κωδικό που
    θέλει το myDATA. Επιστρέφει None όταν το label δεν αντιστοιχεί σε κωδικό —
    η οθόνη τότε δεν προτείνει τίποτα, αντί να μαντέψει."""
    label = (label or "").strip()
    if not label:
        return None
    for code, text in labels.items():
        if text.strip() == label:
            return code
    return None
