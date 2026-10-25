import json
import subprocess
from pathlib import Path

import pytest

import evaluate
from conftest import ANSWERS, SAMPLES, answer
from invoice_to_excel.extract import ClaudeCodeProvider, ExtractionError
from invoice_to_excel.schema import INVOICE_JSON_SCHEMA

PDF = (SAMPLES / "inv01_sahyadri.pdf").read_bytes()
JPG = (SAMPLES / "inv05_malnad_photo.jpg").read_bytes()


def cli_output(data=None, *, result="", is_error=False, subtype="success", model="claude-sonnet-5-5"):
    return json.dumps({
        "type": "result", "subtype": subtype, "is_error": is_error, "result": result,
        "structured_output": data, "session_id": "s1", "total_cost_usd": 0.01,
        "usage": {"input_tokens": 100, "cache_read_input_tokens": 2000, "cache_creation_input_tokens": 900,
                  "output_tokens": 450},
        "modelUsage": {"claude-haiku-5-5": {"outputTokens": 20}, model: {"outputTokens": 430}},
    })


class FakeCLI:
    """Stands in for subprocess.run; records what Claude Code would have been asked."""

    def __init__(self, stdout="", stderr="", exc=None):
        self.stdout, self.stderr, self.exc, self.calls = stdout, stderr, exc, []

    def __call__(self, cmd, **kw):
        folder = Path(kw["cwd"])
        self.calls.append({"cmd": cmd, "kw": kw, "files": {p.name: p.read_bytes() for p in folder.iterdir()}})
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, 0, self.stdout, self.stderr)


def test_command_restricts_tools_and_forces_schema(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-be-passed")
    data = answer("inv01_sahyadri")["invoice"]
    cli = FakeCLI(cli_output(data))
    ex = ClaudeCodeProvider(runner=cli).extract("inv01_sahyadri.pdf", PDF)
    call = cli.calls[0]
    cmd = call["cmd"]
    assert cmd[:2] == ["claude", "-p"] and "./invoice.pdf" in cmd[2] and "never correct" in cmd[2]
    assert cmd[cmd.index("--output-format") + 1] == "json"
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == INVOICE_JSON_SCHEMA
    assert cmd[cmd.index("--allowedTools") + 1] == "Read"
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "--model" not in cmd
    assert call["files"] == {"invoice.pdf": PDF}  # only the invoice is in the folder it can see
    assert call["kw"]["stdin"] == subprocess.DEVNULL  # no 3-second wait for piped input
    assert "ANTHROPIC_API_KEY" not in call["kw"]["env"]  # uses the subscription login, not API credit
    assert not Path(call["kw"]["cwd"]).exists()  # temporary folder removed afterwards
    assert ex.data == data and ex.model == "claude-sonnet-5-5"
    assert ex.input_tokens == 3000 and ex.output_tokens == 450
    assert "Claude Code" in ex.notes[0]


def test_model_option_and_photo_preprocessing():
    cli = FakeCLI(cli_output({"grand_total": 1}))
    ClaudeCodeProvider(model="claude-haiku-5-5", runner=cli).extract("photo.JPG", JPG)
    cmd, files = cli.calls[0]["cmd"], cli.calls[0]["files"]
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-5-5"
    assert list(files) == ["invoice.jpg"] and files["invoice.jpg"][:2] == b"\xff\xd8"


def test_falls_back_to_result_text():
    cli = FakeCLI(cli_output(None, result='```json\n{"grand_total": 5}\n```'))
    assert ClaudeCodeProvider(runner=cli).extract("a.pdf", PDF).data == {"grand_total": 5}


@pytest.mark.parametrize("fake,needle", [
    (FakeCLI(cli_output(None, result="Not logged in · Please run /login", is_error=True)), "Not logged in"),
    (FakeCLI(cli_output(None, subtype="error_max_turns")), "error_max_turns"),
    (FakeCLI("", stderr="error: unknown option '--json-schema'"), "unknown option"),
    (FakeCLI(exc=subprocess.TimeoutExpired("claude", 300)), "longer than 300 s"),
    (FakeCLI(exc=FileNotFoundError("claude")), "Could not start"),
], ids=["not-logged-in", "max-turns", "old-cli", "timeout", "missing-binary"])
def test_failures_become_plain_messages(fake, needle):
    with pytest.raises(ExtractionError, match=needle):
        ClaudeCodeProvider(runner=fake).extract("a.pdf", PDF)


def test_bad_files_rejected_before_calling_claude():
    cli = FakeCLI(cli_output({}))
    with pytest.raises(ExtractionError, match="not a valid PDF"):
        ClaudeCodeProvider(runner=cli).extract("a.pdf", b"hello")
    with pytest.raises(ExtractionError, match="unsupported"):
        ClaudeCodeProvider(runner=cli).extract("a.docx", b"x")
    assert cli.calls == []


def test_missing_cli_explained(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ExtractionError, match="docs/setup.md"):
        ClaudeCodeProvider()


def test_evaluate_with_claude_code_records_and_labels(tmp_path, monkeypatch):
    class KeysThroughCLI(ClaudeCodeProvider):
        def __init__(self, model=None):
            super().__init__(model=model, runner=self.fake)

        def fake(self, cmd, **kw):
            name = self.current
            return subprocess.CompletedProcess(cmd, 0, cli_output(answer(name)["invoice"]), "")

        def extract(self, file_name, data):
            self.current = Path(file_name).stem
            return super().extract(file_name, data)

    monkeypatch.setattr(evaluate, "ClaudeCodeProvider", KeysThroughCLI)
    monkeypatch.setattr(evaluate, "RECORDED", tmp_path / "rec")
    monkeypatch.setattr(evaluate, "REPORT", tmp_path / "accuracy.md")
    assert evaluate.main(["--provider", "claude-code", "--record"]) == 0
    report = (tmp_path / "accuracy.md").read_text(encoding="utf-8")
    assert "**claude-sonnet-5-5**" in report and "Claude Code CLI on a Claude subscription" in report
    assert "About this measurement" in report and "Estimated AI cost" not in report
    assert "(100.0%)" in report and "**5 of 5**" in report
    saved = sorted(p.name for p in (tmp_path / "rec").glob("*.json"))
    assert saved == sorted(p.name for p in ANSWERS.glob("*.json"))
    rec = json.loads((tmp_path / "rec" / "inv01_sahyadri.json").read_text())
    assert rec["model"] == "claude-sonnet-5-5" and rec["data"] == answer("inv01_sahyadri")["invoice"]


def test_evaluate_reports_missing_cli(monkeypatch, capsys):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert evaluate.main(["--provider", "claude-code"]) == 2
    assert "not found" in capsys.readouterr().err
