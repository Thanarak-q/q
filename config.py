"""Configuration management for ctf-agent.

Loads settings from environment variables / .env file with sensible defaults.
Supports multi-model strategy, cost budgets, and sandbox mode selection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class ModelConfig:
    """LLM model configuration with multi-model tiers."""

    fast_model: str = os.getenv("FAST_MODEL", "gpt-4o-mini")
    default_model: str = os.getenv("DEFAULT_MODEL", "gpt-4o")
    reasoning_model: str = os.getenv("REASONING_MODEL", "o3")
    api_key: str = os.getenv("OPENAI_API_KEY", "")
    temperature: float = float(os.getenv("CTF_TEMPERATURE", "0.2"))
    max_tokens: int = int(os.getenv("CTF_MAX_TOKENS", "4096"))


@dataclass(frozen=True)
class AgentConfig:
    """Agent loop configuration."""

    max_iterations: int = int(os.getenv("MAX_ITERATIONS", "30"))
    stall_threshold: int = int(os.getenv("STALL_THRESHOLD", "5"))
    context_limit_percent: int = int(os.getenv("CONTEXT_LIMIT_PERCENT", "80"))
    tool_output_max_chars: int = int(os.getenv("TOOL_OUTPUT_MAX_CHARS", "4000"))
    max_cost_per_challenge: float = float(os.getenv("MAX_COST_PER_CHALLENGE", "2.00"))


@dataclass(frozen=True)
class ToolConfig:
    """Tool execution configuration."""

    shell_timeout: int = int(os.getenv("TOOL_TIMEOUT_SHELL", "30"))
    python_timeout: int = int(os.getenv("TOOL_TIMEOUT_PYTHON", "60"))
    network_timeout: int = int(os.getenv("TOOL_TIMEOUT_NETWORK", "30"))


@dataclass(frozen=True)
class DockerConfig:
    """Docker sandbox configuration."""

    image_name: str = os.getenv("DOCKER_IMAGE", "ctf-agent-sandbox")
    memory_limit: str = os.getenv("DOCKER_MEM", "512m")
    cpu_quota: int = int(os.getenv("DOCKER_CPU_QUOTA", "50000"))
    network_mode: str = "bridge"
    work_dir: str = "/workspace"


@dataclass(frozen=True)
class LogConfig:
    """Logging configuration."""

    level: str = os.getenv("LOG_LEVEL", "INFO")
    log_dir: Path = Path(os.getenv("LOG_DIR", "logs"))
    session_dir: Path = Path(os.getenv("SESSION_DIR", "sessions"))


@dataclass(frozen=True)
class AppConfig:
    """Top-level application configuration aggregating all sub-configs."""

    model: ModelConfig = field(default_factory=ModelConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    tool: ToolConfig = field(default_factory=ToolConfig)
    docker: DockerConfig = field(default_factory=DockerConfig)
    log: LogConfig = field(default_factory=LogConfig)
    sandbox_mode: str = os.getenv("SANDBOX_MODE", "docker")


# Pricing per 1M tokens (USD) – updated as of 2025 pricing
MODEL_PRICING: dict[str, dict[str, float]] = {
    "gpt-4o": {"input": 2.50, "output": 10.00},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "o3": {"input": 10.00, "output": 40.00},
    "o3-mini": {"input": 1.10, "output": 4.40},
    "gpt-4-turbo": {"input": 10.00, "output": 30.00},
}


def load_config() -> AppConfig:
    """Load and return the application configuration.

    Returns:
        AppConfig with all sub-configurations populated from env vars.
    """
    return AppConfig()
