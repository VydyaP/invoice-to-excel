import copy
import datetime as dt

import pytest

from conftest import answer
from invoice_to_excel.checks import check_batch, check_invoice
from invoice_to_excel.schema import invoice_from_dict

TODAY = dt.date(2026, 10, 31)


def codes(data, today=TODAY):
    return sorted({f.code for f in check_invoice(invoice_from_dict(data), today)})


def base():
    return copy.deepcopy(answer("inv01_sahyadri")["invoice"])


def test_answer_keys_raise_exactly_the_planted_problems(all_answers):
    invoices = [invoice_from_dict(a["invoice"]) for a in all_answers.values()]
    flags = check_batch(invoices, [a["file"] for a in all_answers.values()], TODAY)
    for a, f in zip(all_answers.values(), flags, strict=True):
        assert sorted({x.code for x in f}) == sorted(a["expected_flags"]), a["file"]


def test_clean_invoice_has_no_flags():
    assert codes(base()) == []


@pytest.mark.parametrize("field", ["supplier_gstin", "invoice_number", "invoice_date", "grand_total"])
def test_missing_key_fields(field):
    d = base()
    d[field] = None
    assert "MISSING_FIELD" in codes(d)


def test_line_math_warning():
    d = base()
    d["line_items"][0]["quantity"] += 1
    assert "LINE_MATH" in codes(d)


def test_taxable_sum_error():
    d = base()
    d["line_items"][0]["taxable_value"] += 50
    d["line_items"][0]["rate"] = d["line_items"][0]["taxable_value"] / d["line_items"][0]["quantity"]
    assert "TAXABLE_SUM" in codes(d)


def test_rounding_within_one_rupee_is_fine():
    d = base()
    d["grand_total"] += 0.9
    assert codes(d) == []
    d["grand_total"] += 0.2
    assert codes(d) == ["TOTAL_MISMATCH"]


def test_cgst_sgst_must_match():
    d = base()
    d["sgst_amount"] += 10
    d["grand_total"] += 10
    assert "CGST_SGST" in codes(d)


def test_tax_amount_vs_rates():
    d = base()
    d["cgst_amount"] += 40
    d["sgst_amount"] += 40
    d["grand_total"] += 80
    assert "TAX_AMOUNT" in codes(d)


def test_interstate_must_use_igst():
    d = base()
    d["place_of_supply_state_code"] = "33"
    assert "TAX_TYPE" in codes(d)
    d = copy.deepcopy(answer("inv03_coromandel")["invoice"])  # Tamil Nadu supplier, IGST: correct
    assert codes(d) == []


def test_future_and_invalid_dates():
    d = base()
    d["invoice_date"] = "2027-01-05"
    assert "DATE_FUTURE" in codes(d)
    d["invoice_date"] = "31-02-2026"
    assert "DATE_INVALID" in codes(d)


def test_gstin_checksum_on_buyer_too():
    d = base()
    d["buyer_gstin"] = d["buyer_gstin"][:-1] + ("A" if d["buyer_gstin"][-1] != "A" else "B")
    assert "GSTIN_CHECKSUM" in codes(d)


def test_missing_rate_is_an_error():
    d = base()
    d["line_items"][0]["gst_rate"] = None
    flags = check_invoice(invoice_from_dict(d), TODAY)
    assert any(f.code == "RATE_MISSING" and f.severity == "error" for f in flags)


def test_duplicates_ignore_number_formatting_and_flag_later_copy():
    a, b, c = base(), base(), base()
    b["invoice_number"] = b["invoice_number"].replace("/", "-").lower()
    c["supplier_gstin"] = "27AAPFU0939F1ZV"  # different supplier, same number: not a duplicate
    flags = check_batch([invoice_from_dict(x) for x in (a, b, c)], ["a.pdf", "b.pdf", "c.pdf"], TODAY)
    assert [f.code for f in flags[0]] == []
    dup = [f for f in flags[1] if f.code == "DUPLICATE"]
    assert dup and "a.pdf" in dup[0].message
    assert not any(f.code == "DUPLICATE" for f in flags[2])
