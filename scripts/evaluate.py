"""Measure how accurately the AI reads the sample invoices.

    # With an Anthropic API key (what the app uses):
    export ANTHROPIC_API_KEY=...            # your own key; never commit it
    python scripts/evaluate.py --record

    # With a Claude subscription (e.g. Pro) through the Claude Code CLI, no API key:
    python scripts/evaluate.py --provider claude-code --record

    # Re-score saved answers, no AI calls:
    python scripts/evaluate.py --provider recorded

Scores every field against samples/answers/*.json (what is printed on each invoice), checks
that the rules catch the 5 planted problems without false alarms, and writes
docs/accuracy.md. With --record, the AI's raw answers are saved to demo/recorded/ so the
public demo can replay real results for free.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from invoice_to_excel.extract import (  # noqa: E402
    DEFAULT_MODEL,
    ClaudeCodeProvider,
    ClaudeProvider,
    ExtractionError,
    RecordedProvider,
)
from invoice_to_excel.pipeline import estimated_cost_usd, process  # noqa: E402
from invoice_to_excel.schema import HEADER_FIELDS, LINE_FIELDS, invoice_from_dict  # noqa: E402

SAMPLES = ROOT / "samples" / "invoices"
ANSWERS = ROOT / "samples" / "answers"
RECORDED = ROOT / "demo" / "recorded"
REPORT = ROOT / "docs" / "accuracy.md"
# Sample invoices are dated October 2026; checking against a fixed "today" keeps results stable.
EVAL_TODAY = dt.date(2026, 10, 31)


def _show(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def same(field: str, got, want) -> bool:
    if want is None:
        return got is None
    if got is None:
        return False
    if isinstance(want, (int, float)) and not isinstance(want, bool):
        try:
            return abs(float(got) - float(want)) < 0.011
        except (TypeError, ValueError):
            return False
    norm = lambda s: " ".join(str(s).split()).casefold()  # noqa: E731
    return norm(got) == norm(want)


def score(got_inv, want: dict) -> dict:
    """Per-field results for one invoice: {'header': {field: bool}, 'lines': [{field: bool}], ...}."""
    want_inv = invoice_from_dict(want)
    header = {f: same(f, getattr(got_inv, f), getattr(want_inv, f)) for f in HEADER_FIELDS}
    lines = []
    for i, wl in enumerate(want_inv.line_items):
        gl = got_inv.line_items[i] if i < len(got_inv.line_items) else None
        lines.append({f: (gl is not None and same(f, getattr(gl, f), getattr(wl, f))) for f in LINE_FIELDS})
    return {"header": header, "lines": lines, "extra_lines": max(0, len(got_inv.line_items) - len(want_inv.line_items))}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", choices=["claude", "claude-code", "recorded"], default="claude",
                    help="claude = Anthropic API key; claude-code = Claude Code CLI on a Claude subscription")
    ap.add_argument("--model", help=f"model id (API default: {DEFAULT_MODEL}; Claude Code: its default model)")
    ap.add_argument("--record", action="store_true", help="save the AI's answers to demo/recorded/")
    ap.add_argument("--only", help="comma-separated sample names to run (default: all)")
    args = ap.parse_args(argv)

    try:
        if args.provider == "recorded":
            provider = RecordedProvider(RECORDED)
        elif args.provider == "claude-code":
            provider = ClaudeCodeProvider(model=args.model)
        else:
            provider = ClaudeProvider(model=args.model or DEFAULT_MODEL)
    except ExtractionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    answers = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in sorted(ANSWERS.glob("*.json"))}
    if args.only:
        keep = set(args.only.split(","))
        answers = {k: v for k, v in answers.items() if k in keep}
    files = [(a["file"], (SAMPLES / a["file"]).read_bytes()) for a in answers.values()]

    def progress(done: int, total: int, name: str) -> None:
        if args.provider != "recorded":
            print(f"[{done + 1}/{total}] reading {name} ...", flush=True)

    started = time.time()
    results = process(files, provider, today=EVAL_TODAY, progress=progress)
    seconds = time.time() - started

    rows, totals = [], {"fields": 0, "right": 0}
    caught = missed = false_alarms = 0
    misses: list[str] = []
    for (stem, ans), res in zip(answers.items(), results, strict=True):
        expected = set(ans["expected_flags"])
        if res.invoice is None:
            n = len(HEADER_FIELDS) + len(LINE_FIELDS) * len(ans["invoice"]["line_items"])
            rows.append((ans["file"], 0, n, "not read", "-"))
            totals["fields"] += n
            misses.append(f"- **{ans['file']}**: not read ({res.error})")
            missed += len(expected)
            continue
        s = score(res.invoice, ans["invoice"])
        flat = list(s["header"].items()) + [(f"line {i + 1} {f}", ok) for i, ln in enumerate(s["lines"]) for f, ok in ln.items()]
        right = sum(ok for _, ok in flat)
        totals["fields"] += len(flat)
        totals["right"] += right
        got_codes = {f.code for f in res.flags if f.severity == "error" or f.code in expected}
        caught += len(expected & got_codes)
        missed += len(expected - got_codes)
        extra = {f.code for f in res.flags if f.severity == "error"} - expected
        false_alarms += len(extra)
        wrong = [name for name, ok in flat if not ok]
        if wrong:
            misses.append(f"- **{ans['file']}**: " + ", ".join(wrong))
        if s["extra_lines"]:
            misses.append(f"- **{ans['file']}**: {s['extra_lines']} extra line item(s) invented")
        rows.append((ans["file"], right, len(flat), ", ".join(sorted(got_codes)) or "none",
                     ", ".join(sorted(extra)) or "none"))
        if args.record and args.provider != "recorded" and res.extraction:
            RECORDED.mkdir(parents=True, exist_ok=True)
            ex = res.extraction
            (RECORDED / f"{stem}.json").write_text(json.dumps({
                "file": ans["file"], "model": ex.model, "recorded_on": dt.date.today().isoformat(),
                "input_tokens": ex.input_tokens, "output_tokens": ex.output_tokens, "data": ex.data,
            }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pct = 100 * totals["right"] / totals["fields"] if totals["fields"] else 0.0
    expected_total = sum(len(a["expected_flags"]) for a in answers.values())
    cost = estimated_cost_usd(results)
    model = next((r.extraction.model for r in results if r.extraction), args.model or DEFAULT_MODEL)
    via = {"claude": "the Anthropic API (the same call the app makes)",
           "claude-code": "the Claude Code CLI on a Claude subscription (not the app's API call; see below)",
           "recorded": "previously recorded answers"}[args.provider]
    lines = [
        "# Measured accuracy",
        "",
        f"Run on {dt.date.today().strftime('%d %b %Y')} with **{model}** over {len(answers)} fictional sample invoices "
        f"(PDFs and phone photos, see `samples/`). Answer keys are in `samples/answers/`.",
        "",
        f"Read through {via}.",
        "",
        "| Measure | Result |",
        "|---|---|",
        f"| Fields read correctly | **{totals['right']} of {totals['fields']} ({pct:.1f}%)** |",
        f"| Planted problems caught by the checks | **{caught} of {expected_total}** |",
        f"| False alarms (error-level flags with no planted problem) | **{false_alarms}** |",
        f"| Time for all invoices | {seconds:.0f} s |",
    ]
    if cost is not None and args.provider == "claude":
        lines.append(f"| Estimated AI cost for the run | about ${cost:.4f} (≈ ₹{cost * 88:.2f} at ₹88/$) |")
    summary = [line for line in lines if line.startswith("| ") and not line.startswith("| Measure")]
    lines += ["", "## Per invoice", "", "| Invoice | Fields right | Problems flagged | Unexpected errors |", "|---|---|---|---|"]
    lines += [f"| {f} | {r}/{n} | {c} | {x} |" for f, r, n, c, x in rows]
    lines += ["", "## Fields the AI got wrong", ""] + (misses or ["None."])
    if args.provider == "claude-code":
        lines += ["", "## About this measurement", "",
                  "These answers came from Claude Code (`claude -p` with `--json-schema`), which reads each file "
                  "with its own Read tool and was signed in with a Claude subscription, so there is no per-invoice "
                  "API cost to report. The web app's \"Read your own invoices\" tab calls the Anthropic API "
                  f"directly with `{DEFAULT_MODEL}`. Results through that path may differ until it is measured "
                  "with `python scripts/evaluate.py --record` and an API key."]
    lines += ["", "Re-run with `python scripts/evaluate.py --record`. The cost estimate uses the per-token "
              "prices in `src/invoice_to_excel/pipeline.py`; check Anthropic's pricing page for current rates."]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n".join(summary))
    print(f"\nFull report: {_show(REPORT)}")
    if args.record and args.provider != "recorded":
        print(f"Saved AI answers for the demo in {_show(RECORDED)}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
