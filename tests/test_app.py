import pytest
from streamlit.testing.v1 import AppTest

from conftest import ROOT

APP = str(ROOT / "app.py")


@pytest.fixture
def app(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return AppTest.from_file(APP, default_timeout=60)


def load_samples(at):
    at.run()
    next(b for b in at.button if b.label == "Load the 12 sample invoices").click().run()
    assert not at.exception
    return at


def test_first_screen_explains_demo_and_missing_key(app):
    app.run()
    assert not app.exception
    text = " ".join(x.value for x in app.info) + " ".join(x.value for x in app.warning)
    assert "hand-typed correct values" in text  # no recordings in the repo yet: says so plainly
    assert "needs an Anthropic API key" in text
    read = next(b for b in app.button if b.label == "Read invoices")
    assert read.disabled


def test_demo_batch_lists_flagged_invoices_first(app):
    at = load_samples(app)
    assert [m.value for m in at.metric][:3] == ["12", "7", "5"]
    assert at.selectbox[0].value == 8  # inv09 (bad total) is the first one needing review
    assert "grand total shows ₹7,664.00" in at.error[0].value


def test_editing_a_flagged_field_rechecks(app):
    at = load_samples(app)
    next(t for t in at.text_input if t.label.startswith("Grand total")).input("7564.00")
    next(b for b in at.button if "Save changes" in b.label).click().run()
    assert not at.exception
    assert [m.value for m in at.metric][1] == "8"
    assert any("Every check passed" in s.value for s in at.success)


def test_review_other_invoice_shows_its_reason(app):
    at = load_samples(app)
    at.selectbox[0].set_value(9).run()  # inv10, mistyped GSTIN
    assert "check character should be I, not 7" in at.error[0].value


def test_download_buttons_present(app):
    at = load_samples(app)
    labels = [el.proto.label for el in at.get("download_button")]
    assert labels == ["Excel workbook", "Invoices CSV", "Line items CSV"]


def test_recorded_answers_used_when_present(app, tmp_path, monkeypatch):
    import invoice_to_excel.extract as ex

    class AllRecorded(ex.RecordedProvider):
        def available(self, file_name):
            return True

    monkeypatch.setattr(ex, "RecordedProvider", AllRecorded)
    app.run()
    assert any("actually returned" in c.value for c in app.caption)


def test_key_from_environment_enables_own_invoices(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not any("needs an Anthropic API key" in w.value for w in at.warning)
