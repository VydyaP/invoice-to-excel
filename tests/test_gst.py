import datetime as dt

import pytest

from invoice_to_excel.gst import gstin_check_char, gstin_problem, rate_problem, state_of

AFTER = dt.date(2026, 1, 10)
BEFORE = dt.date(2025, 8, 1)


def test_check_char_matches_a_known_real_format_gstin():
    assert gstin_check_char("27AAPFU0939F1Z") == "V"


@pytest.mark.parametrize("gstin", ["27AAPFU0939F1ZV", "29AAICS4821K1ZY", "33AAGFC2276D1ZV", "27aapfu0939f1zv"])
def test_valid_gstins_pass(gstin):
    assert gstin_problem(gstin) is None


@pytest.mark.parametrize("gstin,needle", [
    ("27AAPFU0939F1ZX", "should be V, not X"),
    ("27AAPFU0939F1Z", "15 characters"),
    ("27AAPF10939F1ZV", "format"),
    ("27AAPFU0939F1AV", "format"),
    ("40AAPFU0939F1ZV", "not a valid state code"),
    ("", "missing"),
])
def test_bad_gstins_are_explained(gstin, needle):
    assert needle in gstin_problem(gstin)


def test_single_digit_misread_is_caught():
    good = "29AAEFM6055R1ZI"
    assert gstin_problem(good) is None
    assert "check character" in gstin_problem(good[:-1] + "7")
    assert "check character" in gstin_problem(good[:5] + "B" + good[6:])


def test_state_of():
    assert state_of("29AAICS4821K1ZY") == "29"
    assert state_of("XX") is None
    assert state_of(None) is None


@pytest.mark.parametrize("rate", [0, 5, 18, 40, 3, 0.25])
def test_current_rates_ok_after_change(rate):
    assert rate_problem(rate, AFTER) is None


@pytest.mark.parametrize("rate", [12, 28])
def test_removed_slabs_flagged_after_change(rate):
    assert rate_problem(rate, AFTER)[0] == "RATE_NOT_VALID_ON_DATE"


@pytest.mark.parametrize("rate", [12, 28, 5, 18])
def test_old_slabs_ok_before_change(rate):
    assert rate_problem(rate, BEFORE) is None


def test_change_day_itself_uses_new_rates():
    assert rate_problem(12, dt.date(2025, 9, 22))[0] == "RATE_NOT_VALID_ON_DATE"
    assert rate_problem(12, dt.date(2025, 9, 21)) is None


def test_40_not_valid_before_change():
    assert rate_problem(40, BEFORE)[0] == "RATE_UNUSUAL"


def test_unusual_and_missing_rates():
    assert rate_problem(7, AFTER)[0] == "RATE_UNUSUAL"
    assert rate_problem(None, AFTER)[0] == "RATE_MISSING"
    assert rate_problem(7, None)[0] == "RATE_UNUSUAL"
    assert rate_problem(12, None) is None
