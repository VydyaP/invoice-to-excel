import json

import evaluate
from conftest import ANSWERS


def test_same_compares_numbers_and_text_loosely():
    assert evaluate.same("grand_total", 100.004, 100)
    assert not evaluate.same("grand_total", 101, 100)
    assert evaluate.same("supplier_name", "Sahyadri  agro foods", "Sahyadri Agro Foods")
    assert evaluate.same("buyer_gstin", None, None)
    assert not evaluate.same("buyer_gstin", None, "29AAPFN5678Q1ZX")
    assert not evaluate.same("grand_total", "abc", 5)


def make_recordings(folder, tamper=None):
    folder.mkdir()
    for p in ANSWERS.glob("*.json"):
        data = json.loads(p.read_text(encoding="utf-8"))["invoice"]
        if tamper and p.stem == tamper[0]:
            tamper[1](data)
        (folder / p.name).write_text(json.dumps({"data": data, "model": "claude-haiku-5-5",
                                                 "input_tokens": 2000, "output_tokens": 500}))


def run(tmp_path, monkeypatch, tamper=None):
    make_recordings(tmp_path / "rec", tamper)
    monkeypatch.setattr(evaluate, "RECORDED", tmp_path / "rec")
    monkeypatch.setattr(evaluate, "REPORT", tmp_path / "accuracy.md")
    assert evaluate.main(["--provider", "recorded"]) == 0
    return (tmp_path / "accuracy.md").read_text(encoding="utf-8")


def test_perfect_answers_score_100(tmp_path, monkeypatch):
    report = run(tmp_path, monkeypatch)
    assert "(100.0%)" in report
    assert "**5 of 5**" in report
    assert "False alarms" in report and "| **0** |" in report
    assert "None." in report


def test_misreads_are_counted_and_listed(tmp_path, monkeypatch):
    def misread(d):
        d["grand_total"] = 99.0
        d["line_items"][0]["quantity"] = 7

    report = run(tmp_path, monkeypatch, tamper=("inv02_kaveri", misread))
    assert "(100.0%)" not in report
    assert "inv02_kaveri.pdf**: grand_total, line 1 quantity" in report
    assert "TOTAL_MISMATCH" in report  # the checks caught the misread total
