"""Checks on what the AI read. Plain arithmetic and GST rules, no AI, so they can be
trusted to catch both the AI's misreads and real mistakes on the invoice."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from .gst import gstin_problem, rate_problem, state_of
from .schema import Invoice

ERROR, WARNING = "error", "warning"
TOLERANCE = 1.0  # rupees: printed amounts are rounded


@dataclass(frozen=True)
class Flag:
    code: str
    severity: str
    field: str
    message: str


def _close(a: float, b: float, tol: float = TOLERANCE) -> bool:
    return abs(a - b) <= tol


def _r(x: float) -> str:
    return f"₹{x:,.2f}"


def check_invoice(inv: Invoice, today: dt.date | None = None) -> list[Flag]:
    flags: list[Flag] = []
    add = lambda *a: flags.append(Flag(*a))  # noqa: E731
    today = today or dt.date.today()

    for fld in ("supplier_gstin", "invoice_number", "invoice_date", "grand_total"):
        if getattr(inv, fld) in (None, ""):
            add("MISSING_FIELD", ERROR, fld, "Not found on the invoice; fill it in before exporting")

    for fld in ("supplier_gstin", "buyer_gstin"):
        value = getattr(inv, fld)
        if value:
            problem = gstin_problem(value)
            if problem:
                code = "GSTIN_CHECKSUM" if "check character" in problem else "GSTIN_INVALID"
                add(code, ERROR, fld, problem)

    if inv.invoice_date:
        d = inv.date
        if d is None:
            add("DATE_INVALID", ERROR, "invoice_date", f"'{inv.invoice_date}' is not a valid date")
        elif d > today:
            add("DATE_FUTURE", WARNING, "invoice_date", "Invoice date is in the future; check day and month")

    # Line arithmetic and rates
    for i, ln in enumerate(inv.line_items, 1):
        if ln.quantity is not None and ln.rate is not None and ln.taxable_value is not None:
            expected = ln.quantity * ln.rate
            if not _close(expected, ln.taxable_value):
                add("LINE_MATH", WARNING, f"line {i}",
                    f"{ln.quantity:g} x {_r(ln.rate)} = {_r(expected)}, but the line shows {_r(ln.taxable_value)}")
        rp = rate_problem(ln.gst_rate, inv.date)
        if rp:
            add(rp[0], WARNING if rp[0] != "RATE_MISSING" else ERROR, f"line {i}", rp[1])

    values = [ln.taxable_value for ln in inv.line_items]
    if inv.taxable_total is not None and values and all(v is not None for v in values):
        if not _close(sum(values), inv.taxable_total):
            add("TAXABLE_SUM", ERROR, "taxable_total",
                f"Lines add up to {_r(sum(values))}, but taxable value shows {_r(inv.taxable_total)}")

    cgst, sgst, igst = (inv.cgst_amount or 0.0), (inv.sgst_amount or 0.0), (inv.igst_amount or 0.0)

    # Same state: CGST + SGST. Different states: IGST.
    sup_state = state_of(inv.supplier_gstin)
    pos = inv.place_of_supply_state_code or state_of(inv.buyer_gstin)
    if sup_state and pos:
        if sup_state == pos and igst > 0:
            add("TAX_TYPE", ERROR, "igst_amount",
                "Supplier and place of supply are in the same state, so CGST + SGST should be charged, not IGST")
        if sup_state != pos and (cgst > 0 or sgst > 0):
            add("TAX_TYPE", ERROR, "cgst_amount",
                "Supplier and place of supply are in different states, so IGST should be charged, not CGST + SGST")
    if not _close(cgst, sgst, 0.05):
        add("CGST_SGST", ERROR, "sgst_amount", f"CGST {_r(cgst)} and SGST {_r(sgst)} should be equal")

    # Tax charged vs. tax the rates imply
    if inv.line_items and all(ln.taxable_value is not None and ln.gst_rate is not None for ln in inv.line_items):
        implied = sum(ln.taxable_value * ln.gst_rate / 100 for ln in inv.line_items)
        charged = cgst + sgst + igst
        if not _close(implied, charged, TOLERANCE + 0.5 * len(inv.line_items)):
            add("TAX_AMOUNT", ERROR, "cgst_amount" if cgst else "igst_amount",
                f"Rates imply tax of {_r(implied)}, but {_r(charged)} is charged")

    if inv.grand_total is not None and inv.taxable_total is not None:
        expected = inv.taxable_total + cgst + sgst + igst + (inv.round_off or 0.0)
        if not _close(expected, inv.grand_total):
            add("TOTAL_MISMATCH", ERROR, "grand_total",
                f"Taxable value + tax + round off = {_r(expected)}, but grand total shows {_r(inv.grand_total)}")
    return flags


def duplicate_key(inv: Invoice) -> tuple[str, str] | None:
    if not inv.supplier_gstin or not inv.invoice_number:
        return None
    return inv.supplier_gstin, re.sub(r"[\s/\-_.]", "", inv.invoice_number.upper())


def check_batch(invoices: list[Invoice], names: list[str], today: dt.date | None = None) -> list[list[Flag]]:
    """Checks for each invoice, plus duplicates within the batch (flagged on the later copy)."""
    seen: dict[tuple[str, str], str] = {}
    out = []
    for inv, name in zip(invoices, names, strict=True):
        flags = check_invoice(inv, today)
        key = duplicate_key(inv)
        if key:
            if key in seen:
                flags.append(Flag("DUPLICATE", ERROR, "invoice_number",
                                  f"Same supplier GSTIN and invoice number as {seen[key]}"))
            else:
                seen[key] = name
        out.append(flags)
    return out
