"""Configuration management for ctf-agent.

Loads settings from ~/.q/settings.json with hardcoded defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SETTINGS_FILE = Path.home() / ".q" / "settings.json"


_KNOWN_SETTINGS_KEYS: set[str] = {
    "fast_model", "default_model", "reasoning_model",
    "openai_api_key", "anthropic_api_key", "google_api_key", "glm_api_key", "brave_api_key",
    "temperature", "max_tokens", "streaming", "fallback_model",
    "max_iterations", "stall_threshold", "context_limit_percent",
    "tool_output_max_chars", "max_cost_per_challenge", "max_cost_per_turn",
    "max_tokens_per_turn", "max_cost_per_session",
    "shell_timeout", "python_timeout", "network_timeout", "browser_timeout_ms",
    "docker_image", "docker_mem", "docker_cpu_quota",
    "log_level", "log_dir", "session_dir",
    "browser_watch", "browser_slow_mo", "browser_viewport_w", "browser_viewport_h",
    "max_parallel_solvers", "fast_path_enabled",
    "team_enabled", "team_max_agents", "team_budget_multiplier", "team_task_timeout",
    "ocr_enabled", "ocr_model", "ocr_max_tokens",
    "plan_mode", "sandbox_mode",
    "category_models",
}


def _load_settings() -> dict:
    """Read ~/.q/settings.json. Returns empty dict if missing or malformed."""
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

    unknown = set(data.keys()) - _KNOWN_SETTINGS_KEYS
    if unknown:
        import sys
        print(
            f"Warning: unknown keys in {SETTINGS_FILE}: {', '.join(sorted(unknown))}",
            file=sys.stderr,
        )
    return data


@dataclass(frozen=True)
class ModelConfig:
    fast_model: str = "gpt-4o-mini"
    default_model: str = "gpt-4o"
    reasoning_model: str = "o3"
    api_key: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096
    streaming: bool = True
    anthropic_api_key: str = ""
    google_api_key: str = ""
    glm_api_key: str = ""
    fallback_model: str = ""
    brave_api_key: str = ""
    category_models: tuple[tuple[str, str], ...] = ()

    def get_model_for_category(self, category: str) -> str | None:
        """Return the model override for a category, or None."""
        for cat, model in self.category_models:
            if cat == category:
                return model
        return None


@dataclass(frozen=True)
class AgentConfig:
    max_iterations: int = 15
    stall_threshold: int = 5
    context_limit_percent: int = 80
    tool_output_max_chars: int = 4000
    max_cost_per_challenge: float = 2.00
    max_cost_per_turn: float = 0.50
    max_tokens_per_turn: int = 50000
    max_cost_per_session: float = 10.00


@dataclass(frozen=True)
class ToolConfig:
    shell_timeout: int = 30
    python_timeout: int = 60
    network_timeout: int = 30
    browser_timeout_ms: int = 30000


@dataclass(frozen=True)
class DockerConfig:
    image_name: str = "ctf-agent-sandbox"
    memory_limit: str = "512m"
    cpu_quota: int = 50000
    network_mode: str = "bridge"
    work_dir: str = "/workspace"


@dataclass(frozen=True)
class LogConfig:
    level: str = "INFO"
    log_dir: Path = Path.home() / ".q" / "logs"
    session_dir: Path = Path.home() / ".q" / "sessions"


@dataclass(frozen=True)
class BrowserVisionConfig:
    watch_mode: bool = True
    slow_mo_ms: int = 300
    viewport_width: int = 1280
    viewport_height: int = 720


@dataclass(frozen=True)
class PipelineConfig:
    max_parallel_solvers: int = 3
    fast_path_enabled: bool = True


@dataclass(frozen=True)
class TeamConfig:
    enabled: bool = False
    max_agents: int = 2
    budget_multiplier: float = 2.0
    task_timeout: int = 300


@dataclass(frozen=True)
class OcrConfig:
    enabled: bool = True
    model: str = "gpt-4o-mini"
    max_tokens: int = 500


@dataclass
class AppConfig:
    model: ModelConfig = None
    agent: AgentConfig = None
    tool: ToolConfig = None
    docker: DockerConfig = None
    log: LogConfig = None
    pipeline: PipelineConfig = None
    browser_vision: BrowserVisionConfig = None
    ocr: OcrConfig = None
    team: TeamConfig = None
    plan_mode: bool = True
    sandbox_mode: str = "docker"

    def __post_init__(self):
        if self.model is None:
            self.model = ModelConfig()
        if self.agent is None:
            self.agent = AgentConfig()
        if self.tool is None:
            self.tool = ToolConfig()
        if self.docker is None:
            self.docker = DockerConfig()
        if self.log is None:
            self.log = LogConfig()
        if self.pipeline is None:
            self.pipeline = PipelineConfig()
        if self.browser_vision is None:
            self.browser_vision = BrowserVisionConfig()
        if self.ocr is None:
            self.ocr = OcrConfig()
        if self.team is None:
            self.team = TeamConfig()


# Pricing per 1M tokens (USD) — updated 2025-Q4
MODEL_PRICING: dict[str, dict[str, float]] = {
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "o3": {"input": 10.00, "output": 40.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "o4-mini": {"input": 1.10, "output": 4.40},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    # Anthropic
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "claude-opus-4-6": {"input": 15.00, "output": 75.00},
    "claude-sonnet-4": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.00},
    "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
    # Google
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
    # Zhipu AI GLM (prices in USD, converted from RMB at ~7 RMB/USD)
    "glm-4": {"input": 14.00, "output": 14.00},
    "glm-4-plus": {"input": 14.00, "output": 14.00},
    "glm-4-air": {"input": 0.14, "output": 0.14},
    "glm-4-airx": {"input": 0.14, "output": 0.14},
    "glm-4-long": {"input": 0.14, "output": 0.14},
    "glm-4-flash": {"input": 0.00, "output": 0.00},
    "glm-4-flashx": {"input": 0.00, "output": 0.00},
}


def load_config() -> AppConfig:
    """Load config from ~/.q/settings.json with hardcoded defaults."""
    s = _load_settings()

    model = ModelConfig(
        fast_model=s.get("fast_model", "gpt-4o-mini"),
        default_model=s.get("default_model", "gpt-4o"),
        reasoning_model=s.get("reasoning_model", "o3"),
        api_key=s.get("openai_api_key", os.getenv("OPENAI_API_KEY", "")),
        temperature=s.get("temperature", 0.2),
        max_tokens=s.get("max_tokens", 4096),
        streaming=s.get("streaming", True),
        anthropic_api_key=s.get(
            "anthropic_api_key", os.getenv("ANTHROPIC_API_KEY", "")
        ),
        google_api_key=s.get("google_api_key", os.getenv("GOOGLE_API_KEY", "")),
        glm_api_key=s.get("glm_api_key", os.getenv("GLM_API_KEY", "")),
        fallback_model=s.get("fallback_model", ""),
        category_models=tuple(
            (k, v) for k, v in s.get("category_models", {}).items()
        ),
        brave_api_key=s.get("brave_api_key", os.getenv("BRAVE_API_KEY", "")),
    )

    agent = AgentConfig(
        max_iterations=s.get("max_iterations", 15),
        stall_threshold=s.get("stall_threshold", 5),
        context_limit_percent=s.get("context_limit_percent", 80),
        tool_output_max_chars=s.get("tool_output_max_chars", 4000),
        max_cost_per_challenge=s.get("max_cost_per_challenge", 2.00),
        max_cost_per_turn=s.get("max_cost_per_turn", 0.50),
        max_tokens_per_turn=s.get("max_tokens_per_turn", 50000),
        max_cost_per_session=s.get("max_cost_per_session", 10.00),
    )

    tool = ToolConfig(
        shell_timeout=s.get("shell_timeout", 30),
        python_timeout=s.get("python_timeout", 60),
        network_timeout=s.get("network_timeout", 30),
        browser_timeout_ms=s.get("browser_timeout_ms", 30000),
    )

    docker = DockerConfig(
        image_name=s.get("docker_image", "ctf-agent-sandbox"),
        memory_limit=s.get("docker_mem", "512m"),
        cpu_quota=s.get("docker_cpu_quota", 50000),
    )

    log = LogConfig(
        level=s.get("log_level", "INFO"),
        log_dir=Path(s.get("log_dir", str(Path.home() / ".q" / "logs"))),
        session_dir=Path(s.get("session_dir", str(Path.home() / ".q" / "sessions"))),
    )

    browser_vision = BrowserVisionConfig(
        watch_mode=s.get("browser_watch", True),
        slow_mo_ms=s.get("browser_slow_mo", 300),
        viewport_width=s.get("browser_viewport_w", 1280),
        viewport_height=s.get("browser_viewport_h", 720),
    )

    pipeline = PipelineConfig(
        max_parallel_solvers=s.get("max_parallel_solvers", 3),
        fast_path_enabled=s.get("fast_path_enabled", True),
    )

    ocr = OcrConfig(
        enabled=s.get("ocr_enabled", True),
        model=s.get("ocr_model", "gpt-4o-mini"),
        max_tokens=s.get("ocr_max_tokens", 500),
    )

    team = TeamConfig(
        enabled=s.get("team_enabled", False),
        max_agents=s.get("team_max_agents", 2),
        budget_multiplier=s.get("team_budget_multiplier", 2.0),
        task_timeout=s.get("team_task_timeout", 300),
    )

    return AppConfig(
        model=model,
        agent=agent,
        tool=tool,
        docker=docker,
        log=log,
        pipeline=pipeline,
        browser_vision=browser_vision,
        ocr=ocr,
        team=team,
        plan_mode=s.get("plan_mode", True),
        sandbox_mode=s.get("sandbox_mode", "docker"),
    )
