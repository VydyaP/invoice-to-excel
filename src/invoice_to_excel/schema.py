"""The invoice fields, the JSON schema the AI must fill, and clean-up of its answer."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import asdict, dataclass, field
from typing import Any

HEADER_FIELDS = [
    "supplier_name", "supplier_gstin", "invoice_number", "invoice_date", "buyer_name", "buyer_gstin",
    "place_of_supply_state_code", "taxable_total", "cgst_amount", "sgst_amount", "igst_amount",
    "round_off", "grand_total",
]
LINE_FIELDS = ["description", "hsn_code", "quantity", "unit", "rate", "taxable_value", "gst_rate"]
MONEY_FIELDS = {"taxable_total", "cgst_amount", "sgst_amount", "igst_amount", "round_off", "grand_total"}
LINE_NUMBERS = {"quantity", "rate", "taxable_value", "gst_rate"}

FIELD_LABELS = {
    "supplier_name": "Supplier", "supplier_gstin": "Supplier GSTIN", "invoice_number": "Invoice no.",
    "invoice_date": "Invoice date", "buyer_name": "Buyer", "buyer_gstin": "Buyer GSTIN",
    "place_of_supply_state_code": "Place of supply (state code)", "taxable_total": "Taxable value",
    "cgst_amount": "CGST", "sgst_amount": "SGST", "igst_amount": "IGST", "round_off": "Round off",
    "grand_total": "Grand total", "description": "Description", "hsn_code": "HSN/SAC", "quantity": "Qty",
    "unit": "Unit", "rate": "Rate", "taxable_value": "Taxable value", "gst_rate": "GST %",
}


def _nullable(kind: str, description: str) -> dict:
    return {"type": [kind, "null"], "description": description}


# Sent to the model as output_config.format. Every object sets additionalProperties: false
# and lists every property as required (null is allowed), as structured outputs expect.
INVOICE_JSON_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": False,
    "required": HEADER_FIELDS + ["line_items"],
    "properties": {
        "supplier_name": _nullable("string", "Seller's business name exactly as printed"),
        "supplier_gstin": _nullable("string", "Seller's 15-character GSTIN exactly as printed, no spaces"),
        "invoice_number": _nullable("string", "Invoice number exactly as printed"),
        "invoice_date": _nullable("string", "Invoice date as YYYY-MM-DD. Indian invoices print day first."),
        "buyer_name": _nullable("string", "Buyer (billed to) name as printed"),
        "buyer_gstin": _nullable("string", "Buyer's GSTIN exactly as printed"),
        "place_of_supply_state_code": _nullable("string", "2-digit GST state code of the place of supply"),
        "taxable_total": _nullable("number", "Total taxable value before tax"),
        "cgst_amount": _nullable("number", "Total CGST charged; 0 if the invoice shows none"),
        "sgst_amount": _nullable("number", "Total SGST/UTGST charged; 0 if none"),
        "igst_amount": _nullable("number", "Total IGST charged; 0 if none"),
        "round_off": _nullable("number", "Round-off amount (can be negative); 0 if none"),
        "grand_total": _nullable("number", "Final amount payable as printed"),
        "line_items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": LINE_FIELDS,
                "properties": {
                    "description": _nullable("string", "Item description as printed"),
                    "hsn_code": _nullable("string", "HSN or SAC code as printed"),
                    "quantity": _nullable("number", "Quantity"),
                    "unit": _nullable("string", "Unit such as PKT, KG, NOS"),
                    "rate": _nullable("number", "Price per unit before tax"),
                    "taxable_value": _nullable("number", "Line amount before tax"),
                    "gst_rate": _nullable("number", "GST rate in percent, e.g. 5 or 18"),
                },
            },
        },
    },
}


@dataclass
class LineItem:
    description: str | None = None
    hsn_code: str | None = None
    quantity: float | None = None
    unit: str | None = None
    rate: float | None = None
    taxable_value: float | None = None
    gst_rate: float | None = None


@dataclass
class Invoice:
    supplier_name: str | None = None
    supplier_gstin: str | None = None
    invoice_number: str | None = None
    invoice_date: str | None = None  # ISO YYYY-MM-DD
    buyer_name: str | None = None
    buyer_gstin: str | None = None
    place_of_supply_state_code: str | None = None
    taxable_total: float | None = None
    cgst_amount: float | None = None
    sgst_amount: float | None = None
    igst_amount: float | None = None
    round_off: float | None = None
    grand_total: float | None = None
    line_items: list[LineItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def date(self) -> dt.date | None:
        try:
            return dt.date.fromisoformat(self.invoice_date) if self.invoice_date else None
        except ValueError:
            return None


# ---------------------------------------------------------------- clean-up of model output

def _num(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = re.sub(r"[₹,\s]|Rs\.?|INR", "", str(value), flags=re.I)
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    s = " ".join(str(value).split())
    return s or None


def _gstin(value: Any) -> str | None:
    s = _text(value)
    return re.sub(r"[\s-]", "", s).upper() if s else None


def _date(value: Any) -> str | None:
    s = _text(value)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d-%m-%y", "%d/%m/%y", "%d %b %Y", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return s  # keep what was read; the date check will flag it


def _state(value: Any) -> str | None:
    s = _text(value)
    if not s:
        return None
    m = re.search(r"\d{1,2}", s)
    return m.group(0).zfill(2) if m else s


def invoice_from_dict(data: dict) -> Invoice:
    """Turn the model's JSON (or an edited table) into a clean Invoice. Never raises on odd values."""
    data = data or {}
    lines = []
    for raw in data.get("line_items") or []:
        if not isinstance(raw, dict):
            continue
        lines.append(LineItem(
            description=_text(raw.get("description")),
            hsn_code=_text(raw.get("hsn_code")),
            quantity=_num(raw.get("quantity")),
            unit=_text(raw.get("unit")),
            rate=_num(raw.get("rate")),
            taxable_value=_num(raw.get("taxable_value")),
            gst_rate=_num(raw.get("gst_rate")),
        ))
    return Invoice(
        supplier_name=_text(data.get("supplier_name")),
        supplier_gstin=_gstin(data.get("supplier_gstin")),
        invoice_number=_text(data.get("invoice_number")),
        invoice_date=_date(data.get("invoice_date")),
        buyer_name=_text(data.get("buyer_name")),
        buyer_gstin=_gstin(data.get("buyer_gstin")),
        place_of_supply_state_code=_state(data.get("place_of_supply_state_code")),
        taxable_total=_num(data.get("taxable_total")),
        cgst_amount=_num(data.get("cgst_amount")),
        sgst_amount=_num(data.get("sgst_amount")),
        igst_amount=_num(data.get("igst_amount")),
        round_off=_num(data.get("round_off")),
        grand_total=_num(data.get("grand_total")),
        line_items=lines,
    )
