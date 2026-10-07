# ABOUTME: Αποτυγχάνει αν τα tracked αρχεία περιέχουν προσωπικά δεδομένα: xlsx, πραγματικά
# ABOUTME: MARK (15 ψηφία από 4), ή όρους από την τοπική, ignored λίστα .personal-data-terms.txt.
import argparse
import re
import subprocess
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TERMS = ROOT / ".personal-data-terms.txt"
# Τα πραγματικά MARK του myDATA είναι 15ψήφια που αρχίζουν από 4· τα συνθετικά από 9.
_MARK = re.compile(r"(?<!\d)4\d{14}(?!\d)")


def _fold(text: str) -> str:
    """Πεζά χωρίς τόνους, ώστε «Αλφάπολη» να ταιριάζει με «ΑΛΦΑΠΟΛΗ»."""
    nfd = unicodedata.normalize("NFD", text)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").casefold()


def load_terms(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = (l.strip() for l in path.read_text(encoding="utf-8").splitlines())
    return [l for l in lines if l and not l.startswith("#")]


def scan(files, terms: list[str]) -> list[str]:
    folded = [_fold(t) for t in terms]
    out = []
    for path, data in files:
        if path.lower().endswith(".xlsx"):
            out.append(f"{path}: αρχείο xlsx")
            continue
        if b"\x00" in data:
            continue  # δυαδικό (γραμματοσειρές κ.λπ.)
        text = data.decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            if _MARK.search(line):
                out.append(f"{path}:{n}: MARK")
            f = _fold(line)
            if any(t in f for t in folded):
                out.append(f"{path}:{n}: όρος από τη λίστα")
    return out


def _tracked():
    names = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                           capture_output=True).stdout.decode("utf-8").split("\0")
    for name in filter(None, names):
        p = ROOT / name
        if p.is_file():
            yield name, p.read_bytes()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--terms", type=Path, default=DEFAULT_TERMS)
    args = parser.parse_args(argv)
    findings = scan(_tracked(), load_terms(args.terms))
    for f in findings:
        print(f)
    print(f"{len(findings)} ευρήματα." if findings else "Καθαρό.")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
