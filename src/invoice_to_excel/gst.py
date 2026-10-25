"""Indian GST rules used by the checks. No AI here: plain, testable code.

Sources for the rate change: GST Council, 56th meeting. From 22 September 2025 the
main slabs became 5% and 18%, the 12% and 28% slabs were removed, and 40% applies
to a short list of goods (tobacco, sugary/aerated drinks and similar).
"""

from __future__ import annotations

import datetime as dt
import re

GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")

STATE_CODES = {
    "01": "Jammu and Kashmir", "02": "Himachal Pradesh", "03": "Punjab", "04": "Chandigarh",
    "05": "Uttarakhand", "06": "Haryana", "07": "Delhi", "08": "Rajasthan", "09": "Uttar Pradesh",
    "10": "Bihar", "11": "Sikkim", "12": "Arunachal Pradesh", "13": "Nagaland", "14": "Manipur",
    "15": "Mizoram", "16": "Tripura", "17": "Meghalaya", "18": "Assam", "19": "West Bengal",
    "20": "Jharkhand", "21": "Odisha", "22": "Chhattisgarh", "23": "Madhya Pradesh", "24": "Gujarat",
    "26": "Dadra and Nagar Haveli and Daman and Diu", "27": "Maharashtra", "28": "Andhra Pradesh (old)",
    "29": "Karnataka", "30": "Goa", "31": "Lakshadweep", "32": "Kerala", "33": "Tamil Nadu",
    "34": "Puducherry", "35": "Andaman and Nicobar Islands", "36": "Telangana", "37": "Andhra Pradesh",
    "38": "Ladakh", "97": "Other Territory", "99": "Centre Jurisdiction",
}

RATE_CHANGE_DATE = dt.date(2025, 9, 22)
# Main slabs plus the common special rates (precious metals, diamonds, merchant exports).
RATES_BEFORE = {0, 0.1, 0.25, 1.5, 3, 5, 12, 18, 28}
RATES_FROM = {0, 0.1, 0.25, 1.5, 3, 5, 18, 40}
REMOVED_SLABS = {12, 28}


def gstin_check_char(first14: str) -> str:
    """Check character for the first 14 characters of a GSTIN (mod-36, alternating weights 1 and 2)."""
    total = 0
    for i, ch in enumerate(first14.upper()):
        product = GSTIN_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_problem(gstin: str | None) -> str | None:
    """None if the GSTIN looks right, otherwise a plain explanation."""
    if not gstin:
        return "GSTIN is missing"
    g = gstin.strip().upper()
    if len(g) != 15:
        return f"GSTIN should be 15 characters, this has {len(g)}"
    if not GSTIN_RE.match(g):
        return "GSTIN format is wrong (expected 2 digits, PAN, entity number, Z, check character)"
    if g[:2] not in STATE_CODES:
        return f"GSTIN starts with {g[:2]}, which is not a valid state code"
    expected = gstin_check_char(g[:14])
    if g[14] != expected:
        return f"GSTIN check character should be {expected}, not {g[14]}: likely a typo or misread"
    return None


def state_of(gstin: str | None) -> str | None:
    if gstin and len(gstin) >= 2 and gstin[:2] in STATE_CODES:
        return gstin[:2]
    return None


def rate_problem(rate: float | None, invoice_date: dt.date | None) -> tuple[str, str] | None:
    """(code, message) if the GST rate is doubtful for the invoice date, else None."""
    if rate is None:
        return ("RATE_MISSING", "GST rate is missing")
    r = float(rate)
    r_key = int(r) if r.is_integer() else r
    if invoice_date is None:
        if r_key not in RATES_BEFORE | RATES_FROM:
            return ("RATE_UNUSUAL", f"{r:g}% is not a standard GST rate")
        return None
    if invoice_date >= RATE_CHANGE_DATE:
        if r_key in REMOVED_SLABS:
            return ("RATE_NOT_VALID_ON_DATE",
                    f"{r:g}% slab was removed from 22 Sep 2025; check the rate on this invoice")
        if r_key not in RATES_FROM:
            return ("RATE_UNUSUAL", f"{r:g}% is not a standard GST rate")
    elif r_key not in RATES_BEFORE:
        return ("RATE_UNUSUAL", f"{r:g}% is not a standard GST rate for that date")
    return None
