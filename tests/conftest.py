import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from invoice_to_excel.extract import Extraction, ExtractionError  # noqa: E402

ANSWERS = ROOT / "samples" / "answers"
SAMPLES = ROOT / "samples" / "invoices"


def answer(stem: str) -> dict:
    return json.loads((ANSWERS / f"{stem}.json").read_text(encoding="utf-8"))


class KeyProvider:
    """Fake AI: returns the answer key for each sample, or fails for names in `fail`."""

    name = "fake"

    def __init__(self, fail=(), model="claude-haiku-5-5"):
        self.fail, self.model, self.calls = set(fail), model, []

    def extract(self, file_name, data):
        self.calls.append(file_name)
        if file_name in self.fail:
            raise ExtractionError("The AI service had a temporary problem. Try again shortly.")
        return Extraction(answer(Path(file_name).stem)["invoice"], self.model, 3000, 600)


@pytest.fixture
def all_answers():
    return {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(ANSWERS.glob("*.json"))}


@pytest.fixture
def sample_files(all_answers):
    return [(a["file"], (SAMPLES / a["file"]).read_bytes()) for a in all_answers.values()]
