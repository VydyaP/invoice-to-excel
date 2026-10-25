"""Generate FICTIONAL GST purchase invoices plus their answer keys.

    python scripts/make_samples.py

Writes samples/invoices/*.pdf|*.jpg and samples/answers/*.json. Fixed random seed,
so the files never change between runs.

All businesses are made up. GSTINs are generated with a valid check digit so the
format checks can be exercised; any match with a real registration is coincidental.

The answer key records what is PRINTED on each invoice, mistakes included, and which
problems the checks should find. That is what the evaluation scores against.
"""

from __future__ import annotations

import io
import json
import random
import sys
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import matplotlib
import pypdfium2 as pdfium
from fpdf import FPDF
from PIL import Image, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from invoice_to_excel.gst import gstin_check_char  # noqa: E402

OUT_INV = ROOT / "samples" / "invoices"
OUT_ANS = ROOT / "samples" / "answers"
FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
TWO = Decimal("0.01")


def money(x) -> Decimal:
    return Decimal(str(x)).quantize(TWO, rounding=ROUND_HALF_UP)


def gstin(state: str, pan: str, entity: str = "1") -> str:
    base = f"{state}{pan}{entity}Z"
    return base + gstin_check_char(base)


STATES = {"29": "Karnataka", "33": "Tamil Nadu", "27": "Maharashtra"}

BUYER = {
    "name": "Namma Angadi Provisions (demo)",
    "address": "4th Block, Jayanagar, Bengaluru 560011",
    "gstin": gstin("29", "AAPFN5678Q"),
    "state": "29",
}

SUPPLIERS = {
    "sahyadri": {"name": "Sahyadri Agro Foods Pvt Ltd", "address": "KIADB Industrial Area, Vasanthanarasapura, Tumakuru 572128",
                 "gstin": gstin("29", "AAICS4821K"), "state": "29", "phone": "+91 81000 00011"},
    "kaveri": {"name": "Kaveri Home Care Products", "address": "Hebbal Industrial Area, Mysuru 570016",
               "gstin": gstin("29", "AAMFK7390B"), "state": "29", "phone": "+91 81000 00022"},
    "coromandel": {"name": "Coromandel Spices & Masala Co.", "address": "Ambattur Industrial Estate, Chennai 600058",
                   "gstin": gstin("33", "AAGFC2276D"), "state": "33", "phone": "+91 81000 00033"},
    "deccan": {"name": "Deccan Packaging Industries", "address": "Peenya 2nd Stage, Bengaluru 560058",
               "gstin": gstin("29", "AAPFD9143H"), "state": "29", "phone": "+91 81000 00044"},
    "malnad": {"name": "Malnad Coffee Curing Works", "address": "IG Road, Chikkamagaluru 577101",
               "gstin": gstin("29", "AAEFM6055R"), "state": "29", "phone": "+91 81000 00055"},
    "konkan": {"name": "Konkan Snacks & Namkeen LLP", "address": "MIDC Bhosari, Pune 411026",
               "gstin": gstin("27", "AAOFK3318E"), "state": "27", "phone": "+91 81000 00066"},
}


@dataclass
class Line:
    description: str
    hsn: str
    quantity: Decimal
    unit: str
    rate: Decimal
    gst_rate: Decimal

    @property
    def taxable_value(self) -> Decimal:
        return money(self.quantity * self.rate)


@dataclass
class Invoice:
    file_id: str
    supplier: str
    number: str
    date: str  # YYYY-MM-DD
    lines: list[Line]
    layout: str  # classic / modern / compact
    photo: bool = False
    charge_igst: bool | None = None  # None = correct for the states; True/False to force a mistake
    total_error: Decimal = Decimal("0")
    gstin_override: str | None = None
    expected_flags: list[str] = field(default_factory=list)
    note: str = ""

    def compute(self) -> dict:
        sup = SUPPLIERS[self.supplier]
        inter_state = sup["state"] != BUYER["state"]
        use_igst = inter_state if self.charge_igst is None else self.charge_igst
        taxable = sum((ln.taxable_value for ln in self.lines), Decimal("0"))
        cgst = sgst = igst = Decimal("0")
        for ln in self.lines:
            tax = money(ln.taxable_value * ln.gst_rate / 100)
            if use_igst:
                igst += tax
            else:
                half = money(ln.taxable_value * ln.gst_rate / 200)
                cgst += half
                sgst += half
        exact = taxable + cgst + sgst + igst
        grand = exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        round_off = grand - exact
        grand += self.total_error  # a printed total that does not add up
        return {"taxable": taxable, "cgst": cgst, "sgst": sgst, "igst": igst, "round_off": round_off,
                "grand": grand, "use_igst": use_igst}

    def answer(self) -> dict:
        sup = SUPPLIERS[self.supplier]
        t = self.compute()
        f = lambda d: float(d)  # noqa: E731
        return {
            "file": self.file_name,
            "note": self.note,
            "expected_flags": self.expected_flags,
            "invoice": {
                "supplier_name": sup["name"],
                "supplier_gstin": self.gstin_override or sup["gstin"],
                "invoice_number": self.number,
                "invoice_date": self.date,
                "buyer_name": BUYER["name"],
                "buyer_gstin": BUYER["gstin"],
                "place_of_supply_state_code": BUYER["state"],
                "line_items": [
                    {"description": ln.description, "hsn_code": ln.hsn, "quantity": f(ln.quantity),
                     "unit": ln.unit, "rate": f(ln.rate), "taxable_value": f(ln.taxable_value),
                     "gst_rate": f(ln.gst_rate)}
                    for ln in self.lines
                ],
                "taxable_total": f(t["taxable"]),
                "cgst_amount": f(t["cgst"]),
                "sgst_amount": f(t["sgst"]),
                "igst_amount": f(t["igst"]),
                "round_off": f(t["round_off"]),
                "grand_total": f(t["grand"]),
            },
        }

    @property
    def file_name(self) -> str:
        return f"{self.file_id}.{'jpg' if self.photo else 'pdf'}"


# ---------------------------------------------------------------- amounts in words (Indian system)

ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve",
        "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _two(n: int) -> str:
    return ONES[n] if n < 20 else (TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else ""))


def _three(n: int) -> str:
    h, r = divmod(n, 100)
    return " ".join(p for p in [(ONES[h] + " Hundred") if h else "", _two(r) if r else ""] if p)


def in_words(amount: Decimal) -> str:
    n = int(amount)
    if n == 0:
        return "Rupees Zero Only"
    parts = []
    for size, name in ((10_000_000, "Crore"), (100_000, "Lakh"), (1000, "Thousand")):
        q, n = divmod(n, size)
        if q:
            parts.append(f"{_three(q) if q >= 100 else _two(q)} {name}")
    if n:
        parts.append(_three(n))
    return "Rupees " + " ".join(parts) + " Only"


def inr(d: Decimal) -> str:
    s = f"{abs(d):.2f}"
    whole, frac = s.split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups) + "," + tail
    return ("-" if d < 0 else "") + whole + "." + frac


def qty(d: Decimal) -> str:
    return f"{d:f}".rstrip("0").rstrip(".") if "." in f"{d:f}" else f"{d:f}"


def ddmmyyyy(iso: str) -> str:
    y, m, d = iso.split("-")
    return f"{d}-{m}-{y}"


# ---------------------------------------------------------------- PDF layouts

class Doc(FPDF):
    def __init__(self):
        super().__init__(format="A4")
        self.add_font("Sans", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("Sans", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.add_font("Mono", "", str(FONT_DIR / "DejaVuSansMono.ttf"))
        self.add_font("Mono", "B", str(FONT_DIR / "DejaVuSansMono-Bold.ttf"))
        self.set_auto_page_break(False)
        self.add_page()


def totals_rows(inv: Invoice, t: dict) -> list[tuple[str, str]]:
    rows = [("Taxable value", inr(t["taxable"]))]
    if t["use_igst"]:
        rows.append(("IGST", inr(t["igst"])))
    else:
        rows += [("CGST", inr(t["cgst"])), ("SGST", inr(t["sgst"]))]
    rows += [("Round off", inr(t["round_off"])), ("Grand total (₹)", inr(t["grand"]))]
    return rows


def layout_classic(inv: Invoice) -> bytes:
    sup, t = SUPPLIERS[inv.supplier], inv.compute()
    gst_no = inv.gstin_override or sup["gstin"]
    pdf = Doc()
    pdf.set_draw_color(60, 60, 60)
    pdf.rect(10, 10, 190, 277)
    pdf.set_xy(10, 14)
    pdf.set_font("Sans", "B", 15)
    pdf.cell(190, 7, sup["name"], align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Sans", "", 9)
    pdf.cell(190, 5, sup["address"], align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(190, 5, f"GSTIN: {gst_no}   State: {STATES[sup['state']]} ({sup['state']})   Ph: {sup['phone']}",
             align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.line(10, 33, 200, 33)
    pdf.set_xy(10, 35)
    pdf.set_font("Sans", "B", 12)
    pdf.cell(190, 7, "TAX INVOICE", align="C")
    pdf.line(10, 43, 200, 43)
    pdf.set_font("Sans", "", 9)
    y = 46
    pdf.set_xy(14, y)
    pdf.multi_cell(95, 5, f"Bill to:\n{BUYER['name']}\n{BUYER['address']}\nGSTIN: {BUYER['gstin']}")
    pdf.set_xy(120, y)
    pdf.multi_cell(76, 5, f"Invoice No: {inv.number}\nInvoice Date: {ddmmyyyy(inv.date)}\n"
                          f"Place of Supply: {STATES[BUYER['state']]} ({BUYER['state']})\nReverse charge: No")
    pdf.line(10, 70, 200, 70)
    cols = [("S.No", 10, "C"), ("Description of goods", 62, "L"), ("HSN", 16, "C"), ("Qty", 14, "R"),
            ("Unit", 12, "C"), ("Rate", 22, "R"), ("GST %", 14, "R"), ("Taxable value", 32, "R")]
    pdf.set_xy(12, 72)
    pdf.set_font("Sans", "B", 8.5)
    for name, w, _al in cols:
        pdf.cell(w, 7, name, border=1, align="C")
    pdf.ln()
    pdf.set_font("Sans", "", 8.5)
    for i, ln in enumerate(inv.lines, 1):
        pdf.set_x(12)
        vals = [str(i), ln.description, ln.hsn, qty(ln.quantity), ln.unit, inr(ln.rate), f"{qty(ln.gst_rate)}%",
                inr(ln.taxable_value)]
        for (_name, w, al), v in zip(cols, vals, strict=True):
            pdf.cell(w, 7, v, border=1, align=al)
        pdf.ln()
    y = pdf.get_y() + 4
    for label, val in totals_rows(inv, t):
        pdf.set_xy(120, y)
        pdf.set_font("Sans", "B" if label.startswith("Grand") else "", 9.5)
        pdf.cell(44, 6.5, label, border=1)
        pdf.cell(36, 6.5, val, border=1, align="R")
        y += 6.5
    pdf.set_xy(14, y + 4)
    pdf.set_font("Sans", "", 9)
    pdf.multi_cell(180, 5, f"Amount in words: {in_words(t['grand'])}")
    pdf.set_xy(130, 262)
    pdf.cell(66, 5, f"For {sup['name']}", align="R")
    pdf.set_xy(130, 276)
    pdf.cell(66, 5, "Authorised Signatory", align="R")
    return bytes(pdf.output())


def layout_modern(inv: Invoice) -> bytes:
    sup, t = SUPPLIERS[inv.supplier], inv.compute()
    gst_no = inv.gstin_override or sup["gstin"]
    pdf = Doc()
    pdf.set_fill_color(28, 88, 72)
    pdf.rect(0, 0, 210, 34, style="F")
    pdf.set_text_color(255, 255, 255)
    pdf.set_xy(14, 9)
    pdf.set_font("Sans", "B", 17)
    pdf.cell(120, 8, sup["name"])
    pdf.set_xy(14, 19)
    pdf.set_font("Sans", "", 8.5)
    pdf.cell(130, 5, sup["address"])
    pdf.set_xy(14, 24)
    pdf.cell(130, 5, f"GSTIN {gst_no}")
    pdf.set_xy(150, 10)
    pdf.set_font("Sans", "B", 14)
    pdf.cell(46, 8, "Tax Invoice", align="R")
    pdf.set_text_color(30, 30, 30)
    pdf.set_font("Sans", "", 9)
    pdf.set_xy(14, 42)
    pdf.set_font("Sans", "B", 9)
    pdf.cell(90, 5, "BILLED TO")
    pdf.set_xy(120, 42)
    pdf.cell(76, 5, "INVOICE DETAILS")
    pdf.set_font("Sans", "", 9)
    pdf.set_xy(14, 48)
    pdf.multi_cell(95, 5, f"{BUYER['name']}\n{BUYER['address']}\nGSTIN {BUYER['gstin']}")
    pdf.set_xy(120, 48)
    pdf.multi_cell(76, 5, f"Number      {inv.number}\nDate           {ddmmyyyy(inv.date).replace('-', '/')}\n"
                          f"Supply to   {STATES[BUYER['state']]} ({BUYER['state']})")
    y = 70
    cols = [("Item", 70, "L"), ("HSN/SAC", 20, "L"), ("Qty", 18, "R"), ("Rate", 24, "R"), ("GST", 14, "R"),
            ("Amount", 36, "R")]
    pdf.set_xy(14, y)
    pdf.set_fill_color(230, 240, 236)
    pdf.set_font("Sans", "B", 8.5)
    for name, w, al in cols:
        pdf.cell(w, 8, name, align=al, fill=True)
    pdf.ln()
    pdf.set_font("Sans", "", 9)
    for i, ln in enumerate(inv.lines):
        pdf.set_x(14)
        fill = i % 2 == 1
        pdf.set_fill_color(246, 249, 248)
        vals = [ln.description, ln.hsn, f"{qty(ln.quantity)} {ln.unit}", inr(ln.rate), f"{qty(ln.gst_rate)}%",
                inr(ln.taxable_value)]
        for (_name, w, al), v in zip(cols, vals, strict=True):
            pdf.cell(w, 8, v, align=al, fill=fill)
        pdf.ln()
    y = pdf.get_y() + 6
    for label, val in totals_rows(inv, t):
        grand = label.startswith("Grand")
        pdf.set_xy(118, y)
        pdf.set_font("Sans", "B" if grand else "", 11 if grand else 9.5)
        pdf.cell(42, 7, label.replace("Grand total (₹)", "Total payable"))
        pdf.cell(36, 7, ("₹ " if grand else "") + val, align="R")
        y += 7.5 if grand else 6.5
    pdf.set_xy(14, y + 6)
    pdf.set_font("Sans", "", 8.5)
    pdf.cell(180, 5, in_words(t["grand"]))
    pdf.set_xy(14, 270)
    pdf.set_text_color(110, 110, 110)
    pdf.cell(180, 5, "Goods once sold will not be taken back. Subject to local jurisdiction. This is a computer generated invoice.")
    return bytes(pdf.output())


def layout_compact(inv: Invoice) -> bytes:
    sup, t = SUPPLIERS[inv.supplier], inv.compute()
    gst_no = inv.gstin_override or sup["gstin"]
    pdf = FPDF(format=(110, 240))
    pdf.add_font("Mono", "", str(FONT_DIR / "DejaVuSansMono.ttf"))
    pdf.add_font("Mono", "B", str(FONT_DIR / "DejaVuSansMono-Bold.ttf"))
    pdf.set_auto_page_break(False)
    pdf.add_page()
    w = 94
    pdf.set_xy(8, 8)
    pdf.set_font("Mono", "B", 10)
    pdf.multi_cell(w, 5, sup["name"].upper(), align="C")
    pdf.set_font("Mono", "", 7.5)
    pdf.set_x(8)
    pdf.multi_cell(w, 4, f"{sup['address']}\nGSTIN:{gst_no}\nTAX INVOICE", align="C")
    dash = "-" * 54
    pdf.set_x(8)
    pdf.multi_cell(w, 4, f"{dash}\nINV:{inv.number}   DT:{ddmmyyyy(inv.date).replace('-', '.')}\n"
                         f"TO :{BUYER['name']}\nGST:{BUYER['gstin']}  POS:{BUYER['state']}\n{dash}")
    pdf.set_x(8)
    pdf.cell(w, 4, f"{'ITEM':<22}{'HSN':>6}{'QTY':>6}{'RATE':>9}{'AMT':>11}")
    pdf.ln()
    for ln in inv.lines:
        pdf.set_x(8)
        pdf.cell(w, 4, f"{ln.description[:22]:<22}{ln.hsn:>6}{qty(ln.quantity):>6}{inr(ln.rate):>9}"
                       f"{inr(ln.taxable_value):>11}")
        pdf.ln()
        pdf.set_x(8)
        pdf.cell(w, 4, f"  GST {qty(ln.gst_rate)}%  {ln.unit}")
        pdf.ln()
    pdf.set_x(8)
    pdf.cell(w, 4, dash)
    pdf.ln()
    for label, val in totals_rows(inv, t):
        pdf.set_x(8)
        pdf.set_font("Mono", "B" if label.startswith("Grand") else "", 8 if label.startswith("Grand") else 7.5)
        pdf.cell(w, 4.5, f"{label.upper().replace(' (₹)', ''):<30}{val:>24}")
        pdf.ln()
    pdf.set_font("Mono", "", 7)
    pdf.set_x(8)
    pdf.multi_cell(w, 4, f"{dash}\n{in_words(t['grand']).upper()}\nE&OE. THANK YOU.", align="C")
    return bytes(pdf.output())


LAYOUTS = {"classic": layout_classic, "modern": layout_modern, "compact": layout_compact}


# ---------------------------------------------------------------- "phone photo" effect

def photo_from_pdf(pdf_bytes: bytes, rng: random.Random, quality: int = 72) -> bytes:
    page = pdfium.PdfDocument(pdf_bytes)[0]
    img = page.render(scale=150 / 72).to_pil().convert("RGB")
    w, h = img.size
    # paper on a wooden-ish desk, slightly turned and tilted, with uneven light
    canvas = Image.new("RGB", (int(w * 1.12), int(h * 1.08)), (120, 92, 64))
    angle = rng.uniform(-3.5, 3.5)
    paper = img.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(120, 92, 64))
    canvas.paste(paper, ((canvas.width - paper.width) // 2, (canvas.height - paper.height) // 2))
    cw, ch = canvas.size
    d = int(cw * 0.025)
    quad = (rng.randint(0, d), rng.randint(0, d), rng.randint(0, d), ch - rng.randint(0, d),
            cw - rng.randint(0, d), ch - rng.randint(0, d), cw - rng.randint(0, d), rng.randint(0, d))
    canvas = canvas.transform(canvas.size, Image.QUAD, quad, resample=Image.BICUBIC)
    # smooth light falloff towards one corner (a phone held at an angle)
    across = Image.linear_gradient("L").rotate(90).resize(canvas.size)  # 90 degrees keeps the square filled
    down = Image.linear_gradient("L").resize(canvas.size)
    if rng.random() < 0.5:
        across = across.transpose(Image.FLIP_LEFT_RIGHT)
    shade = ImageChops.add(across, down, scale=2.0).point(lambda v: int(80 * (v / 255) ** 2.2))
    canvas = Image.composite(Image.new("RGB", canvas.size, (0, 0, 0)), canvas, shade)
    canvas = canvas.filter(ImageFilter.GaussianBlur(0.6))
    noise = Image.effect_noise(canvas.size, 14).convert("RGB")
    canvas = Image.blend(canvas, noise, 0.05)
    canvas = canvas.resize((int(cw * 0.75), int(ch * 0.75)))
    buf = io.BytesIO()
    canvas.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# ---------------------------------------------------------------- the 12 samples

D = Decimal


def L(desc, hsn, q, unit, rate, gst):
    return Line(desc, hsn, D(str(q)), unit, D(str(rate)), D(str(gst)))


INVOICES = [
    Invoice("inv01_sahyadri", "sahyadri", "SAF/26-27/0412", "2026-10-03", [
        L("Toor Dal 1kg", "0713", 40, "PKT", 142.00, 5), L("Sona Masoori Rice 25kg", "1006", 6, "BAG", 1180.00, 5),
        L("Wheat Atta 5kg", "1101", 20, "PKT", 228.00, 5)], "classic", note="Clean digital invoice, same state"),
    Invoice("inv02_kaveri", "kaveri", "KHC-2026-1187", "2026-10-06", [
        L("Detergent Powder 1kg", "3402", 24, "PKT", 92.00, 18), L("Dishwash Bar 3pc", "3401", 36, "PKT", 38.00, 18),
        L("Herbal Toothpaste 150g", "3306", 30, "NOS", 64.00, 5)], "modern", note="Mixed 5% and 18% lines"),
    Invoice("inv03_coromandel", "coromandel", "CSM/1903/26", "2026-10-08", [
        L("Sambar Powder 500g", "0910", 30, "PKT", 96.00, 5), L("Chilli Powder 1kg", "0904", 12, "PKT", 260.00, 5),
        L("Turmeric Powder 500g", "0910", 20, "PKT", 88.00, 5)], "compact",
        note="Other state (Tamil Nadu), so IGST; narrow receipt layout"),
    Invoice("inv04_deccan", "deccan", "DPI/OCT/2209", "2026-10-09", [
        L("Corrugated Box 12x10x8", "4819", 500, "NOS", 14.50, 18), L("Carry Bag 40 micron (kg)", "3923", 25, "KG", 168.00, 18),
        L("Packing Tape 2 inch", "3919", 48, "NOS", 42.00, 18), L("Label Roll 50x25mm", "4821", 10, "ROL", 210.00, 18),
        L("Stretch Film 18 inch", "3920", 6, "ROL", 640.00, 18), L("Paper Bag Medium", "4819", 1000, "NOS", 3.20, 18),
        L("Glue Bottle 500ml", "3506", 12, "NOS", 85.00, 18), L("Price Gun Labels", "4821", 20, "ROL", 36.00, 18)],
        "classic", note="Long invoice, 8 lines"),
    Invoice("inv05_malnad_photo", "malnad", "MCW/26/0788", "2026-10-11", [
        L("Filter Coffee Powder 500g", "0901", 40, "PKT", 205.00, 5), L("Coffee-Chicory Blend 1kg", "2101", 10, "PKT", 360.00, 5)],
        "modern", photo=True, note="Phone photo: tilted, shadowed, compressed"),
    Invoice("inv06_kaveri_photo", "kaveri", "KHC-2026-1240", "2026-10-14", [
        L("Floor Cleaner 1L", "3402", 24, "BTL", 118.00, 18), L("Toilet Soap 100g x4", "3401", 30, "PKT", 96.00, 5),
        L("Shampoo 340ml", "3305", 18, "BTL", 155.00, 5)], "classic", photo=True, note="Phone photo of a classic layout"),
    Invoice("inv07_konkan_2025", "konkan", "KSN/25-26/0331", "2025-08-18", [
        L("Namkeen Mixture 1kg", "2106", 20, "PKT", 210.00, 12), L("Aloo Bhujia 400g", "2106", 40, "PKT", 82.00, 12)],
        "modern", note="Dated before 22 Sep 2025: 12% was a valid slab then"),
    Invoice("inv08_konkan_2026", "konkan", "KSN/26-27/0102", "2026-10-15", [
        L("Namkeen Mixture 1kg", "2106", 20, "PKT", 215.00, 12), L("Aloo Bhujia 400g", "2106", 40, "PKT", 84.00, 12)],
        "modern", expected_flags=["RATE_NOT_VALID_ON_DATE"],
        note="Still charging the old 12% slab after it was removed"),
    Invoice("inv09_sahyadri_badtotal", "sahyadri", "SAF/26-27/0455", "2026-10-17", [
        L("Sugar 1kg", "1701", 50, "PKT", 44.00, 5), L("Sunflower Oil 1L", "1512", 36, "PKT", 139.00, 5)],
        "classic", total_error=D("100"), expected_flags=["TOTAL_MISMATCH"],
        note="Printed grand total is ₹100 more than the lines add up to"),
    Invoice("inv10_malnad_badgstin", "malnad", "MCW/26/0801", "2026-10-18", [
        L("Filter Coffee Powder 500g", "0901", 30, "PKT", 205.00, 5)], "compact",
        gstin_override=None, expected_flags=["GSTIN_CHECKSUM"], note="Supplier GSTIN has a wrong check digit"),
    Invoice("inv11_deccan_igst", "deccan", "DPI/OCT/2251", "2026-10-20", [
        L("Corrugated Box 12x10x8", "4819", 300, "NOS", 14.50, 18), L("Packing Tape 2 inch", "3919", 24, "NOS", 42.00, 18)],
        "modern", charge_igst=True, expected_flags=["TAX_TYPE"],
        note="Same-state supply but IGST charged instead of CGST + SGST"),
    Invoice("inv12_sahyadri_duplicate", "sahyadri", "SAF/26-27/0412", "2026-10-03", [
        L("Toor Dal 1kg", "0713", 40, "PKT", 142.00, 5), L("Sona Masoori Rice 25kg", "1006", 6, "BAG", 1180.00, 5),
        L("Wheat Atta 5kg", "1101", 20, "PKT", 228.00, 5)], "classic", photo=True, expected_flags=["DUPLICATE"],
        note="The same invoice as inv01, photographed and uploaded again"),
]


def main() -> None:
    OUT_INV.mkdir(parents=True, exist_ok=True)
    OUT_ANS.mkdir(parents=True, exist_ok=True)
    for old in list(OUT_INV.glob("*")) + list(OUT_ANS.glob("*")):
        old.unlink()
    rng = random.Random(2026)
    # inv10: flip the check digit to a wrong one
    good = SUPPLIERS["malnad"]["gstin"]
    bad_char = "7" if good[-1] != "7" else "8"
    INVOICES[9].gstin_override = good[:-1] + bad_char
    for inv in INVOICES:
        pdf = LAYOUTS[inv.layout](inv)
        data = photo_from_pdf(pdf, rng) if inv.photo else pdf
        (OUT_INV / inv.file_name).write_bytes(data)
        (OUT_ANS / f"{inv.file_id}.json").write_text(json.dumps(inv.answer(), indent=2, ensure_ascii=False) + "\n",
                                                     encoding="utf-8")
        print(f"{inv.file_name:34} {len(data) // 1024:>4} KB  flags={inv.expected_flags or '-'}")


if __name__ == "__main__":
    main()
