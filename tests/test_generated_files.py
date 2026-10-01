"""The generated agent integration files.

These files are what a tool actually loads, so a syntax error in one of them is
a broken integration — not a cosmetic problem. The generator validates its own
output, and these tests hold it to that.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from api.agent_registry import AGENTS  # noqa: E402
from scripts.generate_agent_docs import (  # noqa: E402
    GeneratedFileError,
    deliverables,
    validate,
    validate_all,
)

try:
    import tomllib
except ImportError:  # pragma: no cover - Python 3.10
    tomllib = None

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


@pytest.fixture(scope="module")
def generated() -> dict[str, str]:
    return deliverables()


# ── Validation ──────────────────────────────────────────────────────────────


def test_generated_output_passes_validation(generated):
    validate_all(generated)  # raises on any problem


def test_every_agent_gets_a_reference_document(generated):
    for agent in AGENTS:
        path = f"docs/agents/{agent.id}.md"
        assert path in generated, f"{agent.id} has no reference document"
        assert generated[path].strip(), f"{path} is empty"


def test_every_declared_config_file_is_produced(generated):
    for agent in AGENTS:
        for path in agent.config_files:
            assert path in generated, f"{agent.name} declares {path} but none is generated"


def test_no_generated_file_is_empty_or_lacking_a_header(generated):
    for path, content in generated.items():
        assert content.strip(), f"{path} is empty"
        first = content.splitlines()[0]
        assert first.startswith(("<!--", "#", "{", "[", "---", "!")), \
            f"{path} has no generated-file marker: {first[:60]!r}"


def test_machine_specific_paths_are_rejected():
    """A committed config must work on someone else's machine."""
    with pytest.raises(GeneratedFileError, match="local checkout path"):
        validate("demo.toml", f'cwd = "{ROOT.as_posix()}"\n')


def test_invalid_toml_is_rejected():
    with pytest.raises(GeneratedFileError, match="not valid TOML"):
        validate("demo.toml", "<!-- markdown comment -->\nkey = 1\n")


def test_invalid_yaml_is_rejected():
    with pytest.raises(GeneratedFileError, match="not valid YAML"):
        validate("demo.yml", "<!-- markdown comment -->\nread:\n  - a.md\n")


def test_invalid_json_is_rejected():
    with pytest.raises(GeneratedFileError, match="not valid JSON"):
        validate("demo.json", "{ not json }")


def test_validate_all_reports_every_problem_at_once():
    with pytest.raises(GeneratedFileError) as info:
        validate_all({"a.json": "{", "b.json": "{"})
    message = str(info.value)
    assert "a.json" in message and "b.json" in message


# ── Real parsing of the committed formats ───────────────────────────────────


@pytest.mark.skipif(tomllib is None, reason="needs tomllib (Python 3.11+)")
def test_codex_toml_actually_parses(generated):
    content = generated[".codex/config.toml"]
    parsed = tomllib.loads(content)
    server = parsed["mcp_servers"]["auto_get_py"]
    assert server["command"] == "python"
    assert server["args"] == ["mcp_server.py"]
    assert "cwd" not in server, "a hard-coded cwd would be wrong on other machines"
    assert server["env"]["AUTO_GET_BASE_URL"].startswith("http")


@pytest.mark.skipif(yaml is None, reason="needs PyYAML")
def test_aider_yaml_actually_parses(generated):
    parsed = yaml.safe_load(generated[".aider.conf.yml"])
    assert isinstance(parsed, dict), "the HTML header used to make this a string"
    assert parsed["read"] == ["CONVENTIONS.md", "AGENTS.md"]


def test_json_configs_actually_parse(generated):
    json_files = [path for path in generated if path.endswith(".json")]
    assert json_files, "expected some JSON config files"
    for path in json_files:
        json.loads(generated[path])  # raises on failure


def test_mcp_configs_register_the_stdio_server(generated):
    for path in [".mcp.json", ".cursor/mcp.json", ".roo/mcp.json",
                 ".windsurf/mcp.json", ".dsh/mcp.json", ".gemini/settings.json"]:
        payload = json.loads(generated[path])
        # Gemini and the others all use an mcpServers map; VS Code uses `servers`.
        servers = payload.get("mcpServers") or payload.get("servers") or {}
        assert "auto-get-py" in servers, f"{path} does not register the server"
        assert "mcp_server.py" in json.dumps(servers), f"{path} has a wrong command"


def test_opencode_config_shape(generated):
    payload = json.loads(generated["opencode.json"])
    entry = payload["mcp"]["auto-get-py"]
    assert entry["type"] == "local"
    assert entry["command"] == ["python", "mcp_server.py"]


# ── Committed files match the generator ─────────────────────────────────────


def test_committed_files_are_up_to_date(generated):
    """`--check` must pass: the repository copy equals freshly generated output."""
    stale = []
    for path, content in generated.items():
        target = ROOT / path
        if not target.exists():
            stale.append(f"{path} (missing)")
            continue
        if target.read_text(encoding="utf-8") != content:
            stale.append(path)
    assert not stale, (
        "generated files are out of date; run "
        f"`python scripts/generate_agent_docs.py`:\n  " + "\n  ".join(sorted(stale)))


def test_generation_is_deterministic(generated):
    """Two runs must produce byte-identical output, or CI would flap."""
    assert deliverables() == generated
