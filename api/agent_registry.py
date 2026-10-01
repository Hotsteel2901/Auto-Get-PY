"""Registry of the coding agents and AI tools this scraper integrates with.

Every tool in this table gets:

* one or more **URL aliases** — the same canonical API, mounted under the
  prefix that tool naturally reaches for;
* one or more **config files** — the paths that tool reads when it starts, so
  the integration works with no manual setup;
* a generated **skill document** describing how to call the API.

Adding support for a new tool is a single entry in :data:`AGENTS`; the router
aliases and the generated documentation both read from here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The canonical prefix. Every other prefix is an alias of this one.
CANONICAL_PREFIX = "/api/agent"


@dataclass(frozen=True)
class AgentDescriptor:
    """One supported agent/tool."""

    id: str
    name: str
    vendor: str
    # URL prefixes that resolve to the same API as CANONICAL_PREFIX.
    aliases: tuple[str, ...]
    # Files this tool loads automatically; the generator writes them.
    config_files: tuple[str, ...] = ()
    # How a user points the tool at this service.
    install: str = ""
    # Extra notes rendered into the generated skill document.
    notes: str = ""
    # Search terms a skill loader can match on.
    triggers: tuple[str, ...] = field(default_factory=tuple)
    docs_url: str = ""

    @property
    def api_prefix(self) -> str:
        return CANONICAL_PREFIX

    @property
    def primary_prefix(self) -> str:
        return self.aliases[0] if self.aliases else CANONICAL_PREFIX


_MEDIA_TRIGGERS = (
    "scrape", "crawl", "download media", "grab images", "grab video",
    "爬取", "抓取", "爬图", "爬视频", "批量下载", "下载图片", "下载视频", "整站下载",
)


AGENTS: tuple[AgentDescriptor, ...] = (
    AgentDescriptor(
        id="generic",
        name="Any MCP/HTTP agent",
        vendor="Universal",
        aliases=(CANONICAL_PREFIX,),
        config_files=("AGENTS.md",),
        install="Point any HTTP client at http://localhost:8000/api/agent",
        notes=("The canonical surface. Use this when your tool is not listed "
               "explicitly — `AGENTS.md` in the repository root describes it."),
        triggers=_MEDIA_TRIGGERS,
    ),
    AgentDescriptor(
        id="hermes",
        name="Hermes Agent",
        vendor="Hermes",
        aliases=("/api/hermes",),
        config_files=("docs/agents/hermes.md", "docs/HERMES_SKILL.md"),
        install="Load docs/HERMES_SKILL.md as a skill, or call /api/hermes/* directly.",
        notes="Original integration surface; kept for backward compatibility.",
        triggers=_MEDIA_TRIGGERS,
    ),
    AgentDescriptor(
        id="opencode",
        name="opencode",
        vendor="anomalyco",
        aliases=("/api/opencode",),
        config_files=("opencode.json", ".opencode/agent/scraper.md", "AGENTS.md"),
        install=("opencode reads `opencode.json` for the MCP server and "
                 "`AGENTS.md` for instructions. Invoke the bundled subagent "
                 "with `@scraper`."),
        notes=("The `mcp` block in `opencode.json` registers `mcp_server.py`, so "
               "opencode gets `scrape` / `quick_scrape` / `fetch_file` as native "
               "tools."),
        triggers=_MEDIA_TRIGGERS + ("opencode",),
        docs_url="https://opencode.ai/docs/",
    ),
    AgentDescriptor(
        id="dsh",
        name="DeepSeek Harness (dsh / dsh-tui)",
        vendor="DeepSeek Harness",
        aliases=("/api/dsh",),
        config_files=("AGENTS.md", ".dsh/skills/auto-get-py/SKILL.md",
                      ".dsh/mcp.json"),
        install=("Copy `.dsh/skills/auto-get-py` into your dsh skills directory, "
                 "or register `.dsh/mcp.json` with `dsh mcp add`."),
        notes=("dsh-tui discovers skills from `SKILL.md` files, so "
               "`.dsh/skills/auto-get-py/SKILL.md` is directly loadable."),
        triggers=_MEDIA_TRIGGERS + ("dsh", "dsh-tui"),
    ),
    AgentDescriptor(
        id="codex",
        name="OpenAI Codex CLI",
        vendor="OpenAI",
        aliases=("/api/codex",),
        config_files=("AGENTS.md", ".codex/README.md", ".codex/config.toml",
                      ".codex/prompts/scrape.md"),
        install=("Codex reads AGENTS.md automatically. Append the "
                 "`[mcp_servers.auto_get_py]` block from `.codex/config.toml` to "
                 "`~/.codex/config.toml` to expose the tools."),
        notes="Codex also supports custom prompts in `.codex/prompts/`.",
        triggers=_MEDIA_TRIGGERS + ("codex",),
        docs_url="https://github.com/openai/codex",
    ),
    AgentDescriptor(
        id="claude",
        name="Claude Code",
        vendor="Anthropic",
        aliases=("/api/claude",),
        config_files=("CLAUDE.md", ".mcp.json",
                      ".claude/skills/auto-get-py/SKILL.md"),
        install=("Claude Code reads CLAUDE.md and `.mcp.json`, and loads the "
                 "skill from `.claude/skills/auto-get-py/SKILL.md`."),
        notes=("The skill declares `allowed-tools: Bash` so it can curl the API "
               "directly, and `.mcp.json` adds the MCP tools."),
        triggers=_MEDIA_TRIGGERS + ("claude",),
        docs_url="https://docs.claude.com/en/docs/claude-code",
    ),
    AgentDescriptor(
        id="gemini",
        name="Gemini CLI",
        vendor="Google",
        aliases=("/api/gemini",),
        config_files=("GEMINI.md", ".gemini/settings.json"),
        install="Gemini CLI reads GEMINI.md and `.gemini/settings.json`.",
        triggers=_MEDIA_TRIGGERS + ("gemini",),
        docs_url="https://github.com/google-gemini/gemini-cli",
    ),
    AgentDescriptor(
        id="cursor",
        name="Cursor",
        vendor="Anysphere",
        aliases=("/api/cursor",),
        config_files=(".cursor/rules/auto-get-py.mdc", ".cursor/mcp.json"),
        install="Cursor loads `.cursor/rules/*.mdc` and `.cursor/mcp.json`.",
        triggers=_MEDIA_TRIGGERS + ("cursor",),
        docs_url="https://docs.cursor.com/context/rules",
    ),
    AgentDescriptor(
        id="copilot",
        name="GitHub Copilot",
        vendor="GitHub",
        aliases=("/api/copilot",),
        config_files=(".github/copilot-instructions.md", ".vscode/mcp.json"),
        install="Repository instructions and `.vscode/mcp.json` are read "
                "automatically by VS Code / Copilot.",
        triggers=_MEDIA_TRIGGERS + ("copilot",),
        docs_url="https://docs.github.com/copilot",
    ),
    AgentDescriptor(
        id="cline",
        name="Cline",
        vendor="Cline",
        aliases=("/api/cline",),
        config_files=(".clinerules/auto-get-py.md",),
        install="Cline reads `.clinerules/` from the workspace root.",
        triggers=_MEDIA_TRIGGERS + ("cline",),
        docs_url="https://docs.cline.bot/",
    ),
    AgentDescriptor(
        id="roo",
        name="Roo Code",
        vendor="Roo",
        aliases=("/api/roo",),
        config_files=(".roo/rules/auto-get-py.md", ".roo/mcp.json"),
        install="Roo Code reads `.roo/rules/` and `.roo/mcp.json`.",
        triggers=_MEDIA_TRIGGERS + ("roo",),
        docs_url="https://docs.roocode.com/",
    ),
    AgentDescriptor(
        id="windsurf",
        name="Windsurf",
        vendor="Codeium",
        aliases=("/api/windsurf",),
        config_files=(".windsurf/rules/auto-get-py.md", ".windsurf/mcp.json"),
        install="Windsurf reads `.windsurf/rules/` automatically.",
        triggers=_MEDIA_TRIGGERS + ("windsurf",),
        docs_url="https://docs.windsurf.com/",
    ),
    AgentDescriptor(
        id="continue",
        name="Continue",
        vendor="Continue",
        aliases=("/api/continue",),
        config_files=(".continue/rules/auto-get-py.md",),
        install="Continue loads rules from `.continue/rules/`.",
        triggers=_MEDIA_TRIGGERS + ("continue",),
        docs_url="https://docs.continue.dev/",
    ),
    AgentDescriptor(
        id="aider",
        name="Aider",
        vendor="Aider",
        aliases=("/api/aider",),
        config_files=("CONVENTIONS.md", ".aider.conf.yml"),
        install="Run `aider --read CONVENTIONS.md`, or rely on `.aider.conf.yml`.",
        triggers=_MEDIA_TRIGGERS + ("aider",),
        docs_url="https://aider.chat/docs/",
    ),
    AgentDescriptor(
        id="zed",
        name="Zed",
        vendor="Zed Industries",
        aliases=("/api/zed",),
        config_files=(".rules", ".zed/settings.json"),
        install="Zed reads `.rules` for its agent panel and `.zed/settings.json` "
                "for context servers.",
        triggers=_MEDIA_TRIGGERS + ("zed",),
        docs_url="https://zed.dev/docs/ai/rules",
    ),
    AgentDescriptor(
        id="amp",
        name="Amp",
        vendor="Sourcegraph",
        aliases=("/api/amp",),
        config_files=("AGENTS.md",),
        install="Amp reads AGENTS.md from the repository root.",
        triggers=_MEDIA_TRIGGERS + ("amp",),
        docs_url="https://ampcode.com/how-to-build-an-agent",
    ),
    AgentDescriptor(
        id="jules",
        name="Jules",
        vendor="Google",
        aliases=("/api/jules",),
        config_files=("AGENTS.md",),
        install="Jules reads AGENTS.md from the repository root.",
        triggers=_MEDIA_TRIGGERS + ("jules",),
        docs_url="https://jules.google/docs",
    ),
)


AGENTS_BY_ID: dict[str, AgentDescriptor] = {agent.id: agent for agent in AGENTS}


def all_aliases() -> list[str]:
    """Every URL prefix that must serve the canonical API, deduplicated."""
    seen: list[str] = []
    for agent in AGENTS:
        for alias in agent.aliases:
            if alias not in seen:
                seen.append(alias)
    return seen


def aliases_for(agent_id: str) -> tuple[str, ...]:
    agent = AGENTS_BY_ID.get(agent_id)
    return agent.aliases if agent else ()


def resolve_agent(identifier: str) -> AgentDescriptor | None:
    """Look up an agent by id or by one of its URL aliases."""
    if not identifier:
        return None
    key = identifier.strip().lower().strip("/")
    if key in AGENTS_BY_ID:
        return AGENTS_BY_ID[key]
    for agent in AGENTS:
        if agent.id == key:
            return agent
        for alias in agent.aliases:
            if alias.strip("/").lower() == key:
                return agent
    return None


def registry_payload() -> list[dict]:
    """Serialisable view of the registry, used by ``GET /agents``."""
    return [
        {
            "id": agent.id,
            "name": agent.name,
            "vendor": agent.vendor,
            "api_prefix": agent.api_prefix,
            "aliases": list(agent.aliases),
            "config_files": list(agent.config_files),
            "install": agent.install,
            "notes": agent.notes,
            "docs_url": agent.docs_url,
        }
        for agent in AGENTS
    ]
