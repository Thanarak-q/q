"""Configuration management for ctf-agent.

Loads settings from ~/.q/settings.json with hardcoded defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

SETTINGS_FILE = Path.home() / ".q" / "settings.json"


def _load_settings() -> dict:
    """Read ~/.q/settings.json. Returns empty dict if missing or malformed."""
    try:
        return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


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
    fallback_model: str = ""
    brave_api_key: str = ""


@dataclass(frozen=True)
class AgentConfig:
    max_iterations: int = 15
    stall_threshold: int = 5
    context_limit_percent: int = 80
    tool_output_max_chars: int = 4000
    max_cost_per_challenge: float = 2.00


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
    mode: str = "single"
    max_parallel_solvers: int = 3
    recon_max_steps: int = 4
    analyst_max_steps: int = 6
    solver_max_steps: int = 8
    reporter_max_steps: int = 3
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


@dataclass(frozen=True)
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
        # Allow None fields to be set via object.__setattr__ since frozen=True
        for field_name, default in [
            ("model", ModelConfig()),
            ("agent", AgentConfig()),
            ("tool", ToolConfig()),
            ("docker", DockerConfig()),
            ("log", LogConfig()),
            ("pipeline", PipelineConfig()),
            ("browser_vision", BrowserVisionConfig()),
            ("ocr", OcrConfig()),
            ("team", TeamConfig()),
        ]:
            if getattr(self, field_name) is None:
                object.__setattr__(self, field_name, default)


# Pricing per 1M tokens (USD)
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "o3": {"input": 10.00, "output": 40.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    "claude-sonnet-4-5": {"input": 3.00, "output": 15.00},
    "claude-sonnet-4-5-20250514": {"input": 3.00, "output": 15.00},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.00},
    "claude-opus-4": {"input": 15.00, "output": 75.00},
    "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    "gemini-2.5-pro": {"input": 1.25, "output": 10.00},
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
        anthropic_api_key=s.get("anthropic_api_key", os.getenv("ANTHROPIC_API_KEY", "")),
        google_api_key=s.get("google_api_key", os.getenv("GOOGLE_API_KEY", "")),
        fallback_model=s.get("fallback_model", ""),
        brave_api_key=s.get("brave_api_key", os.getenv("BRAVE_API_KEY", "")),
    )

    agent = AgentConfig(
        max_iterations=s.get("max_iterations", 15),
        stall_threshold=s.get("stall_threshold", 5),
        context_limit_percent=s.get("context_limit_percent", 80),
        tool_output_max_chars=s.get("tool_output_max_chars", 4000),
        max_cost_per_challenge=s.get("max_cost_per_challenge", 2.00),
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
        recon_max_steps=s.get("recon_max_steps", 4),
        analyst_max_steps=s.get("analyst_max_steps", 6),
        solver_max_steps=s.get("solver_max_steps", 8),
        reporter_max_steps=s.get("reporter_max_steps", 3),
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
        task_timeout=s.get("team_task_timeout", 120),
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
