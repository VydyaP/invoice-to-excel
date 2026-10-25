from invoice_to_excel.schema import HEADER_FIELDS, INVOICE_JSON_SCHEMA, LINE_FIELDS, invoice_from_dict


def walk(node):
    yield node
    for child in (node.get("properties") or {}).values():
        yield from walk(child)
    if isinstance(node.get("items"), dict):
        yield from walk(node["items"])


def test_schema_follows_structured_output_rules():
    objects = [n for n in walk(INVOICE_JSON_SCHEMA) if n.get("type") == "object"]
    assert len(objects) == 2
    for obj in objects:
        assert obj["additionalProperties"] is False
        assert set(obj["required"]) == set(obj["properties"])
    assert set(INVOICE_JSON_SCHEMA["required"]) == set(HEADER_FIELDS) | {"line_items"}
    assert set(INVOICE_JSON_SCHEMA["properties"]["line_items"]["items"]["required"]) == set(LINE_FIELDS)
    unsupported = {"minimum", "maximum", "minLength", "maxLength", "pattern", "format"}
    assert not any(unsupported & set(n) for n in walk(INVOICE_JSON_SCHEMA))


def test_numbers_are_cleaned():
    inv = invoice_from_dict({"grand_total": "₹ 1,23,456.50", "cgst_amount": "Rs. 90", "igst_amount": "INR 0",
                             "line_items": [{"gst_rate": "18%", "quantity": "2", "rate": True}]})
    assert inv.grand_total == 123456.5 and inv.cgst_amount == 90 and inv.igst_amount == 0
    assert inv.line_items[0].gst_rate == 18 and inv.line_items[0].quantity == 2
    assert inv.line_items[0].rate is None  # booleans are not amounts


def test_unreadable_numbers_become_none():
    assert invoice_from_dict({"grand_total": "illegible"}).grand_total is None


def test_dates_become_iso_day_first():
    for raw in ("03-10-2026", "03/10/2026", "03.10.2026", "2026-10-03", "03-10-26", "3 Oct 2026"):
        assert invoice_from_dict({"invoice_date": raw}).invoice_date == "2026-10-03", raw


def test_unknown_date_kept_for_the_check_to_flag():
    assert invoice_from_dict({"invoice_date": "31-02-2026"}).invoice_date == "31-02-2026"


def test_gstin_and_state_cleaned():
    inv = invoice_from_dict({"supplier_gstin": " 29aaics 4821-k1zy ", "place_of_supply_state_code": "Karnataka (29)"})
    assert inv.supplier_gstin == "29AAICS4821K1ZY"
    assert inv.place_of_supply_state_code == "29"
    assert invoice_from_dict({"place_of_supply_state_code": "7"}).place_of_supply_state_code == "07"


def test_text_whitespace_collapsed_and_blank_is_none():
    inv = invoice_from_dict({"supplier_name": "  Sahyadri   Agro\nFoods ", "invoice_number": "   "})
    assert inv.supplier_name == "Sahyadri Agro Foods" and inv.invoice_number is None


def test_odd_input_never_raises():
    assert invoice_from_dict(None).line_items == []
    assert invoice_from_dict({"line_items": ["junk", None, {"description": "ok"}]}).line_items[0].description == "ok"
    assert invoice_from_dict({"line_items": None}).line_items == []


def test_round_trip(all_answers):
    for a in all_answers.values():
        inv = invoice_from_dict(a["invoice"])
        assert invoice_from_dict(inv.to_dict()) == inv
