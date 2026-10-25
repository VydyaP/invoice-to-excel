import base64
import io
import json
from types import SimpleNamespace

import pytest
from PIL import Image

from conftest import SAMPLES, answer
from invoice_to_excel import extract
from invoice_to_excel.extract import (
    ClaudeProvider,
    ExtractionError,
    RecordedProvider,
    build_content,
    parse_json_text,
    prepare_image,
)
from invoice_to_excel.schema import INVOICE_JSON_SCHEMA

PDF = (SAMPLES / "inv01_sahyadri.pdf").read_bytes()
JPG = (SAMPLES / "inv05_malnad_photo.jpg").read_bytes()


class APIError(Exception):
    def __init__(self, status, text="error"):
        super().__init__(text)
        self.status_code = status


def response(data, stop="end_turn", text=None):
    return SimpleNamespace(stop_reason=stop, usage=SimpleNamespace(input_tokens=2500, output_tokens=420),
                           content=[SimpleNamespace(type="text", text=text if text is not None else json.dumps(data))])


class FakeClient:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


# ---------------------------------------------------------------- building the request

def test_pdf_sent_as_document_block():
    blocks = build_content("a.pdf", PDF)
    assert blocks[0]["type"] == "document"
    assert blocks[0]["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(blocks[0]["source"]["data"]) == PDF
    assert blocks[1]["type"] == "text" and "never correct" in blocks[1]["text"]


def test_photo_sent_as_jpeg_image_block():
    blocks = build_content("a.JPG", JPG)
    assert blocks[0]["type"] == "image" and blocks[0]["source"]["media_type"] == "image/jpeg"


@pytest.mark.parametrize("name,data,needle", [
    ("a.docx", b"x", "unsupported"),
    ("a.pdf", b"hello", "not a valid PDF"),
    ("a.png", b"not an image", "could not be opened"),
    ("a.pdf", b"%PDF" + b"0" * (20 * 1024 * 1024), "20 MB"),
], ids=["word-file", "fake-pdf", "broken-image", "too-large"])
def test_bad_files_rejected_with_plain_messages(name, data, needle):
    with pytest.raises(ExtractionError, match=needle):
        build_content(name, data)


def test_large_photos_shrunk_and_rotated_upright():
    img = Image.new("RGB", (4000, 3000), "white")
    exif = img.getexif()
    exif[0x0112] = 6  # phone held sideways: rotate 90 degrees
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif)
    out, kind = prepare_image(buf.getvalue())
    shrunk = Image.open(io.BytesIO(out))
    assert kind == "image/jpeg"
    assert max(shrunk.size) == extract.MAX_IMAGE_EDGE
    assert shrunk.height > shrunk.width  # portrait after applying EXIF rotation


def test_parse_json_text_accepts_fenced_answers():
    assert parse_json_text('{"a": 1}') == {"a": 1}
    assert parse_json_text('Here you go:\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ExtractionError):
        parse_json_text("I cannot read this")
    with pytest.raises(ExtractionError):
        parse_json_text("{not json}")


# ---------------------------------------------------------------- Claude provider

def test_claude_request_uses_schema_and_returns_usage():
    data = answer("inv01_sahyadri")["invoice"]
    client = FakeClient(response(data))
    ex = ClaudeProvider(model="claude-haiku-5-5", client=client).extract("a.pdf", PDF)
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5"
    assert call["output_config"] == {"format": {"type": "json_schema", "schema": INVOICE_JSON_SCHEMA}}
    assert call["messages"][0]["content"][0]["type"] == "document"
    assert ex.data == data and ex.input_tokens == 2500 and ex.output_tokens == 420 and ex.notes == []


def test_falls_back_when_model_rejects_schema_option():
    data = answer("inv01_sahyadri")["invoice"]
    client = FakeClient(APIError(400, "output_config.format: schema not supported"), response(data, text="```json\n" + json.dumps(data) + "\n```"))
    ex = ClaudeProvider(client=client).extract("a.pdf", PDF)
    assert ex.data == data and "Schema enforcement unavailable" in ex.notes[0]
    assert "output_config" not in client.calls[1]
    assert "JSON Schema" in client.calls[1]["messages"][0]["content"][-1]["text"]


def test_other_bad_requests_are_not_retried():
    client = FakeClient(APIError(400, "Could not process PDF"))
    with pytest.raises(ExtractionError, match="request failed"):
        ClaudeProvider(client=client).extract("a.pdf", PDF)
    assert len(client.calls) == 1


@pytest.mark.parametrize("exc,needle", [
    (APIError(401), "API key was rejected"),
    (APIError(429), "rate limit"),
    (APIError(529), "temporary problem"),
    (type("APIConnectionError", (Exception,), {})("down"), "internet connection"),
])
def test_api_errors_become_plain_messages(exc, needle):
    with pytest.raises(ExtractionError, match=needle):
        ClaudeProvider(client=FakeClient(exc)).extract("a.pdf", PDF)


@pytest.mark.parametrize("stop,needle", [("max_tokens", "too long"), ("refusal", "declined")])
def test_unusable_stop_reasons(stop, needle):
    with pytest.raises(ExtractionError, match=needle):
        ClaudeProvider(client=FakeClient(response({}, stop=stop))).extract("a.pdf", PDF)


def test_missing_key_gives_setup_hint(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ExtractionError, match="docs/setup.md"):
        ClaudeProvider()


# ---------------------------------------------------------------- recorded answers

def test_recorded_provider_replays_saved_answer(tmp_path):
    data = answer("inv02_kaveri")["invoice"]
    (tmp_path / "inv02_kaveri.json").write_text(json.dumps(
        {"data": data, "model": "claude-haiku-5-5", "input_tokens": 10, "output_tokens": 5, "recorded_on": "2026-10-30"}))
    rp = RecordedProvider(tmp_path)
    assert rp.available("inv02_kaveri.pdf") and not rp.available("other.pdf")
    ex = rp.extract("inv02_kaveri.pdf", b"")
    assert ex.data == data and ex.model == "claude-haiku-5-5" and "2026-10-30" in ex.notes[0]
    with pytest.raises(ExtractionError, match="No recorded"):
        rp.extract("other.pdf", b"")
