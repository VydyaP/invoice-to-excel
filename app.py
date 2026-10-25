"""Invoice to Excel: upload purchase bills, let AI read them, review only what's flagged, export.

Run:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from invoice_to_excel.export import (  # noqa: E402
    INVOICE_COLUMNS,
    LINE_COLUMNS,
    invoice_rows,
    line_rows,
    to_csv,
    to_excel,
)
from invoice_to_excel.extract import (  # noqa: E402
    DEFAULT_MODEL,
    SUPPORTED,
    ClaudeProvider,
    Extraction,
    ExtractionError,
    RecordedProvider,
)
from invoice_to_excel.pipeline import Result, estimated_cost_usd, process, recheck  # noqa: E402
from invoice_to_excel.preview import preview_images  # noqa: E402
from invoice_to_excel.schema import FIELD_LABELS, HEADER_FIELDS, LINE_FIELDS, MONEY_FIELDS, invoice_from_dict  # noqa: E402

SAMPLES = ROOT / "samples" / "invoices"
ANSWERS = ROOT / "samples" / "answers"
RECORDED = ROOT / "demo" / "recorded"
MAX_FILES = 25
def inr(x) -> str | None:
    """₹12,34,567.89 (Indian digit grouping)."""
    if x is None:
        return None
    sign, x = ("-" if x < 0 else ""), abs(x)
    whole, frac = f"{x:.2f}".split(".")
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    return f"{sign}₹{','.join(([head] if head else []) + groups + [tail])}.{frac}"


STATUS_ICON = {"Looks right": "✅", "Check warnings": "🟡", "Needs review": "🔴", "Could not read": "⛔"}

st.set_page_config(page_title="Invoice to Excel", page_icon="🧾", layout="wide", initial_sidebar_state="collapsed")


class AnswerKeyProvider:
    """Used only when no recorded AI answers exist yet: replays the hand-typed answer keys so the
    checks and review screen can be tried. Clearly labelled as not AI output."""

    name = "answer-key"

    def extract(self, file_name: str, data: bytes) -> Extraction:
        path = ANSWERS / f"{Path(file_name).stem}.json"
        if not path.exists():
            raise ExtractionError(f"No answer key for {file_name}.")
        return Extraction(json.loads(path.read_text(encoding="utf-8"))["invoice"], "answer key (not AI)")


def api_key() -> str | None:
    try:
        key = st.secrets.get("ANTHROPIC_API_KEY")  # .streamlit/secrets.toml, never committed
    except Exception:  # noqa: BLE001 - no secrets file
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY")


def demo_provider():
    recorded = RecordedProvider(RECORDED)
    names = [p.name for p in sorted(SAMPLES.iterdir()) if p.suffix.lower() in SUPPORTED]
    if names and all(recorded.available(n) for n in names):
        return recorded, True
    return AnswerKeyProvider(), False


def run(files: list[tuple[str, bytes]], provider) -> None:
    with st.spinner(f"Reading {len(files)} invoice(s)…"):
        results = process(files, provider)
    for k in [k for k in st.session_state if str(k)[:1].isdigit() or str(k).startswith("edit_")]:
        del st.session_state[k]  # drop edit boxes from a previous batch
    st.session_state.results = results
    st.session_state.files = dict(files)
    st.session_state.selected = 0


# ------------------------------------------------------------------ header and input

st.title("🧾 Invoice to Excel")
st.write("Upload purchase bills (PDF or phone photos). AI reads each one, plain-arithmetic GST checks "
         "flag anything that doesn't add up, you fix only what's flagged, and download a clean Excel file.")

key = api_key()
tab_demo, tab_own = st.tabs(["Try the sample invoices", "Read your own invoices"])

with tab_demo:
    provider, is_recorded = demo_provider()
    if is_recorded:
        st.caption("12 fictional invoices. The answers shown are what the AI actually returned when "
                   "these files were read (saved earlier), so the demo is free and needs no key.")
    else:
        st.info("Real AI answers for the samples haven't been recorded yet, so this demo uses the "
                "hand-typed correct values. It shows the checks and the review screen, not AI accuracy. "
                "Run `python scripts/evaluate.py --record` to add the AI's answers.")
    if st.button("Load the 12 sample invoices", type="primary"):
        sample_files = [(p.name, p.read_bytes()) for p in sorted(SAMPLES.iterdir()) if p.suffix.lower() in SUPPORTED]
        run(sample_files, provider)

with tab_own:
    if not key:
        st.warning("Reading your own invoices needs an Anthropic API key. Add it to "
                   "`.streamlit/secrets.toml` or the `ANTHROPIC_API_KEY` environment variable and restart "
                   "(see docs/setup.md). The key is never typed into this page.")
    st.caption(f"Model: {DEFAULT_MODEL}. Invoices are sent to Anthropic's API for reading; "
               "nothing is stored by this app.")
    uploads = st.file_uploader("Invoices", type=[e.lstrip(".") for e in SUPPORTED], accept_multiple_files=True,
                               disabled=not key, help=f"Up to {MAX_FILES} files per batch, 20 MB each.")
    if uploads and len(uploads) > MAX_FILES:
        st.error(f"{len(uploads)} files selected. Please upload {MAX_FILES} or fewer at a time.")
    elif st.button("Read invoices", type="primary", disabled=not (key and uploads)):
        try:
            run([(u.name, u.getvalue()) for u in uploads], ClaudeProvider(api_key=key))
        except ExtractionError as exc:
            st.error(str(exc))

results: list[Result] = st.session_state.get("results", [])
if not results:
    st.stop()

# ------------------------------------------------------------------ batch summary

st.divider()
counts = {s: sum(r.status == s for r in results) for s in STATUS_ICON}
c1, c2, c3, c4 = st.columns(4)
c1.metric("Invoices", len(results))
c2.metric("Looks right", counts["Looks right"])
c3.metric("To review", counts["Needs review"] + counts["Could not read"] + counts["Check warnings"])
cost = estimated_cost_usd(results)
c4.metric("AI cost (approx.)", f"${cost:.4f}" if cost is not None else "—",
          help="Estimated from tokens used and the prices in pipeline.py. Check Anthropic's pricing page.")

overview = pd.DataFrame([{
    "": STATUS_ICON[r.status], "File": r.file_name, "Status": r.status,
    "Supplier": r.invoice.supplier_name if r.invoice else None,
    "Invoice no.": r.invoice.invoice_number if r.invoice else None,
    "Grand total": inr(r.invoice.grand_total) if r.invoice else None,
    "Issues": "; ".join(f.message for f in r.flags) or (r.error or ""),
} for r in results])
st.dataframe(overview, hide_index=True, width="stretch", height=min(len(results) + 1, 16) * 35 + 3,
             column_config={"": st.column_config.TextColumn(width="small"),
                            "Issues": st.column_config.TextColumn(width="large")})

# ------------------------------------------------------------------ review one invoice

st.subheader("Review")
order = sorted(range(len(results)), key=lambda i: ["Could not read", "Needs review", "Check warnings",
                                                    "Looks right"].index(results[i].status))
labels = {i: f"{STATUS_ICON[results[i].status]} {results[i].file_name}" for i in order}
idx = st.selectbox("Invoice", order, format_func=labels.get, key="review_pick",
                   help="Invoices needing review are listed first.")
res = results[idx]
left, right = st.columns([4, 6], gap="large")

with left:
    pages = preview_images(res.file_name, st.session_state.files.get(res.file_name, b""))
    if pages:
        for p in pages:
            st.image(p, width="stretch")
    else:
        st.caption("No preview available for this file.")

with right:
    if res.error:
        st.error(res.error)
    for f in res.flags:
        label = FIELD_LABELS.get(f.field, f.field)
        (st.error if f.severity == "error" else st.warning)(f"**{label}:** {f.message}")
    if res.invoice and not res.flags:
        st.success("Every check passed.")
    if res.extraction and res.extraction.notes:
        st.caption(" · ".join(res.extraction.notes))

    if res.invoice:
        flagged = {f.field for f in res.flags}
        inv = res.invoice
        with st.form(f"edit_{idx}"):
            values = {}
            cols = st.columns(2)
            for n, fld in enumerate(HEADER_FIELDS):
                label = FIELD_LABELS[fld] + (" ⚠️" if fld in flagged else "")
                current = getattr(inv, fld)
                values[fld] = cols[n % 2].text_input(
                    label, "" if current is None else (f"{current:.2f}" if fld in MONEY_FIELDS else str(current)),
                    key=f"{idx}_{fld}", help="Date as YYYY-MM-DD" if fld == "invoice_date" else None)
            st.caption("Line items" + (" ⚠️" if any(x.startswith("line") for x in flagged) else ""))
            lines_df = pd.DataFrame([vars(ln) for ln in inv.line_items], columns=LINE_FIELDS)
            edited = st.data_editor(lines_df, num_rows="dynamic", hide_index=True, width="stretch",
                                    key=f"{idx}_lines",
                                    column_config={f: st.column_config.Column(FIELD_LABELS[f]) for f in LINE_FIELDS})
            if st.form_submit_button("Save changes and re-check", type="primary"):
                data = {k: (v.strip() or None) for k, v in values.items()}
                data["line_items"] = [{k: (None if pd.isna(v) else v) for k, v in row.items()}
                                      for row in edited.to_dict("records")
                                      if any(not pd.isna(v) and v != "" for v in row.values())]
                res.invoice = invoice_from_dict(data)
                recheck(results)
                st.rerun()

# ------------------------------------------------------------------ export

st.divider()
st.subheader("Download")
pending = sum(r.status in ("Needs review", "Could not read") for r in results)
if pending:
    st.caption(f"{pending} invoice(s) still need review. You can download now; their status is shown in the file.")
model = next((r.extraction.model for r in results if r.extraction), None)
stamp = dt.date.today().isoformat()
d1, d2, d3, _ = st.columns([1, 1, 1, 3])
d1.download_button("Excel workbook", to_excel(results, model), f"invoices-{stamp}.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
d2.download_button("Invoices CSV", to_csv(invoice_rows(results), INVOICE_COLUMNS), f"invoices-{stamp}.csv", "text/csv")
d3.download_button("Line items CSV", to_csv(line_rows(results), LINE_COLUMNS), f"line-items-{stamp}.csv", "text/csv")
