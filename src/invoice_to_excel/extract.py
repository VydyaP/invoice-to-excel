"""Reading invoices with AI.

Providers:
  * ClaudeProvider  - the real thing: sends the PDF or photo to the Claude API and forces
                      the answer into the invoice JSON schema.
  * ClaudeCodeProvider - reads each invoice through the Claude Code CLI (`claude -p`), using
                      a Claude subscription login instead of an API key. Used for evaluation.
  * RecordedProvider - replays answers saved by scripts/evaluate.py --record, so the public
                      demo costs nothing and never needs an API key.
Tests use a fake provider with the same interface.
"""

from __future__ import annotations

import base64
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageOps

from .schema import INVOICE_JSON_SCHEMA

DEFAULT_MODEL = os.environ.get("INVOICE_MODEL", "claude-haiku-5-5")
MAX_IMAGE_EDGE = 1568  # larger images cost more tokens without reading better
SUPPORTED = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
             ".webp": "image/webp"}
MAX_BYTES = 20 * 1024 * 1024

INSTRUCTIONS = """You are reading an Indian GST tax invoice (a purchase bill) for bookkeeping.
Fill in the schema with what is PRINTED on the invoice.

Rules:
- Copy names, GSTINs, invoice numbers and HSN codes exactly as printed. GSTINs are 15 characters.
- Dates: Indian invoices print day first (03-10-2026 is 3 October 2026). Return YYYY-MM-DD.
- Amounts: plain numbers without commas or currency signs. Use the printed values even if they
  look wrong; never correct or recalculate the invoice.
- If CGST, SGST, IGST or round off is not shown, use 0. If anything else is not visible or not
  readable, use null. Never guess.
- place_of_supply_state_code is the 2-digit state code (for example 29 for Karnataka).
- One line_items entry per item row. gst_rate is the percentage, for example 5 or 18.
"""


class ExtractionError(Exception):
    """The invoice could not be read. The message is shown to the person using the tool."""


@dataclass
class Extraction:
    data: dict
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    notes: list[str] = field(default_factory=list)


class Provider(Protocol):
    name: str

    def extract(self, file_name: str, data: bytes) -> Extraction: ...


def media_type(file_name: str) -> str:
    ext = Path(file_name).suffix.lower()
    if ext not in SUPPORTED:
        raise ExtractionError(f"{file_name}: unsupported file type. Use PDF, JPG, PNG or WEBP.")
    return SUPPORTED[ext]


def prepare_image(data: bytes) -> tuple[bytes, str]:
    """Fix phone rotation (EXIF), shrink very large photos, return JPEG bytes."""
    try:
        img = Image.open(io.BytesIO(data))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except Exception as exc:
        raise ExtractionError("The image could not be opened. It may be damaged.") from exc
    if max(img.size) > MAX_IMAGE_EDGE:
        img.thumbnail((MAX_IMAGE_EDGE, MAX_IMAGE_EDGE))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return buf.getvalue(), "image/jpeg"


def build_content(file_name: str, data: bytes) -> list[dict]:
    """Message content for one invoice: the document or image, then the instructions."""
    if len(data) > MAX_BYTES:
        raise ExtractionError(f"{file_name}: file is larger than 20 MB.")
    mt = media_type(file_name)
    if mt == "application/pdf":
        if not data.startswith(b"%PDF"):
            raise ExtractionError(f"{file_name}: this is not a valid PDF.")
        source_block = {"type": "document",
                        "source": {"type": "base64", "media_type": mt, "data": base64.b64encode(data).decode()}}
    else:
        img, img_type = prepare_image(data)
        source_block = {"type": "image",
                        "source": {"type": "base64", "media_type": img_type, "data": base64.b64encode(img).decode()}}
    return [source_block, {"type": "text", "text": INSTRUCTIONS}]


def parse_json_text(text: str) -> dict:
    """Accept plain JSON or JSON wrapped in prose / code fences."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise ExtractionError("The AI did not return invoice data. Try again or check the file.") from None
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError as exc:
            raise ExtractionError("The AI's answer was not valid data. Try again.") from exc


class ClaudeProvider:
    """Claude API. Needs ANTHROPIC_API_KEY in the environment (or passed in)."""

    name = "claude"

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None, client=None, max_tokens: int = 4000):
        self.model = model
        self.max_tokens = max_tokens
        if client is not None:
            self.client = client
        else:
            import anthropic

            key = api_key or os.environ.get("ANTHROPIC_API_KEY")
            if not key:
                raise ExtractionError("No API key found. Set ANTHROPIC_API_KEY (see docs/setup.md).")
            self.client = anthropic.Anthropic(api_key=key, max_retries=3, timeout=120)

    def extract(self, file_name: str, data: bytes) -> Extraction:
        content = build_content(file_name, data)
        notes: list[str] = []
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": content}],
                output_config={"format": {"type": "json_schema", "schema": INVOICE_JSON_SCHEMA}},
            )
        except Exception as exc:  # noqa: BLE001 - mapped to plain messages below
            if _is_bad_request(exc):
                # If this model rejects the schema option, fall back to instructions-only JSON.
                notes.append("Schema enforcement unavailable for this model; used JSON instructions instead.")
                response = self._create_without_schema(content)
            else:
                raise ExtractionError(_friendly(exc)) from exc
        if getattr(response, "stop_reason", None) == "max_tokens":
            raise ExtractionError("The invoice was too long to read in one go. Split it into fewer pages.")
        if getattr(response, "stop_reason", None) == "refusal":
            raise ExtractionError("The AI declined to read this file.")
        text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", "") == "text")
        usage = getattr(response, "usage", None)
        return Extraction(
            data=parse_json_text(text),
            model=self.model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            notes=notes,
        )

    def _create_without_schema(self, content: list[dict]):
        schema_hint = json.dumps(INVOICE_JSON_SCHEMA)
        text = content[-1]["text"] + f"\nReply with only a JSON object matching this JSON Schema:\n{schema_hint}"
        try:
            return self.client.messages.create(
                model=self.model, max_tokens=self.max_tokens,
                messages=[{"role": "user", "content": content[:-1] + [{"type": "text", "text": text}]}],
            )
        except Exception as exc:  # noqa: BLE001
            raise ExtractionError(_friendly(exc)) from exc


def _is_bad_request(exc: Exception) -> bool:
    """A 400 about the structured-output option itself (not about the file)."""
    text = str(exc).lower()
    return getattr(exc, "status_code", None) == 400 and any(w in text for w in ("schema", "output_config", "format"))


def _friendly(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status == 401:
        return "The API key was rejected. Check ANTHROPIC_API_KEY."
    if status == 429:
        return "Too many requests right now (rate limit). Wait a minute and try again."
    if status and status >= 500:
        return "The AI service had a temporary problem. Try again shortly."
    if type(exc).__name__ in ("APIConnectionError", "APITimeoutError"):
        return "Could not reach the AI service. Check the internet connection."
    return f"The AI request failed: {exc}"


class ClaudeCodeProvider:
    """Claude Code CLI in print mode, signed in with a Claude subscription (for example Pro).

    Each invoice is copied into an empty temporary folder; Claude Code may only use its Read
    tool there, and must answer in the invoice JSON schema (--json-schema). ANTHROPIC_API_KEY is
    removed from its environment so the subscription login is used, not API credit.
    """

    name = "claude-code"

    def __init__(self, model: str | None = None, cli: str = "claude", timeout: int = 300, runner=None):
        self.model, self.cli, self.timeout = model, cli, timeout
        self.runner = runner or subprocess.run
        if runner is None and shutil.which(cli) is None:
            raise ExtractionError("Claude Code ('claude' command) was not found. Install it and sign in "
                                  "with your Claude account first (see docs/setup.md).")

    def command(self, file_name: str) -> list[str]:
        prompt = (f"Read the invoice file ./{file_name} with the Read tool. Do not open any other file.\n\n"
                  + INSTRUCTIONS + "\nAnswer only with the structured output.")
        cmd = [self.cli, "-p", prompt, "--output-format", "json", "--json-schema", json.dumps(INVOICE_JSON_SCHEMA),
               "--allowedTools", "Read", "--permission-mode", "dontAsk"]
        if self.model:
            cmd += ["--model", self.model]
        return cmd

    def extract(self, file_name: str, data: bytes) -> Extraction:
        if len(data) > MAX_BYTES:
            raise ExtractionError(f"{file_name}: file is larger than 20 MB.")
        mt = media_type(file_name)
        if mt == "application/pdf":
            if not data.startswith(b"%PDF"):
                raise ExtractionError(f"{file_name}: this is not a valid PDF.")
            local_name = "invoice.pdf"
        else:
            data, _ = prepare_image(data)  # same rotation and resizing as the API path
            local_name = "invoice.jpg"
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        with tempfile.TemporaryDirectory(prefix="invoice-") as tmp:
            (Path(tmp) / local_name).write_bytes(data)
            try:
                proc = self.runner(self.command(local_name), cwd=tmp, env=env, stdin=subprocess.DEVNULL,
                                   capture_output=True, text=True, timeout=self.timeout)
            except subprocess.TimeoutExpired as exc:
                raise ExtractionError(f"Claude Code took longer than {self.timeout} s on this file.") from exc
            except OSError as exc:
                raise ExtractionError(f"Could not start Claude Code: {exc}") from exc
        return self._parse(proc)

    def _parse(self, proc) -> Extraction:
        try:
            out = json.loads(proc.stdout)
        except (json.JSONDecodeError, TypeError):
            detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:] or ["no output"]
            raise ExtractionError(f"Claude Code did not return a result ({detail[0][:200]}).") from None
        if out.get("is_error") or out.get("subtype", "success") != "success":
            reason = str(out.get("result") or out.get("subtype") or "unknown error")[:200]
            raise ExtractionError(f"Claude Code could not read this file: {reason}")
        data = out.get("structured_output")
        if not isinstance(data, dict):
            data = parse_json_text(str(out.get("result") or ""))
        model_usage = out.get("modelUsage") or {}
        model = self.model or "claude-code"
        if model_usage:  # the model that did the reading produced the most output
            model = max(model_usage, key=lambda m: (model_usage[m] or {}).get("outputTokens", 0))
        usage = out.get("usage") or {}
        return Extraction(
            data=data, model=model,
            input_tokens=sum(int(usage.get(k) or 0) for k in
                             ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")),
            output_tokens=int(usage.get("output_tokens") or 0),
            notes=[f"Read through Claude Code ({model}) on a Claude subscription"],
        )


class RecordedProvider:
    """Replays saved answers (demo/recorded/<file>.json). Free, offline, deterministic."""

    name = "recorded"

    def __init__(self, folder: Path):
        self.folder = Path(folder)

    def available(self, file_name: str) -> bool:
        return (self.folder / f"{Path(file_name).stem}.json").exists()

    def extract(self, file_name: str, data: bytes) -> Extraction:
        path = self.folder / f"{Path(file_name).stem}.json"
        if not path.exists():
            raise ExtractionError(f"No recorded AI answer for {file_name}.")
        saved = json.loads(path.read_text(encoding="utf-8"))
        return Extraction(data=saved["data"], model=saved.get("model", "recorded"),
                          input_tokens=saved.get("input_tokens", 0), output_tokens=saved.get("output_tokens", 0),
                          notes=[f"Recorded answer from {saved.get('model', 'the AI')} "
                                 f"on {saved.get('recorded_on', '?')}"])
