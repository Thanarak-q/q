"""YAML configuration loader.

Loads an optional YAML file that layers *on top* of the existing
env-based ``config.AppConfig``.  This allows users to specify target
auth, focus areas, parallel settings, and cost limits in a structured
way without touching environment variables.

Usage::

    from config_yaml.loader import load_yaml_config, inject_target_to_prompt

    qcfg = load_yaml_config("configs/my-app.yaml")
    extra_prompt = inject_target_to_prompt(qcfg)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any


@dataclass
class AuthConfig:
    """Target application authentication details."""

    login_url: str = ""
    username: str = ""
    password: str = ""
    totp_secret: str = ""
    login_flow: list[str] = field(default_factory=list)
    success_condition: str = ""


@dataclass
class TargetConfig:
    """Target application configuration."""

    url: str = ""
    auth: AuthConfig | None = None
    focus: list[str] = field(default_factory=list)
    avoid: list[str] = field(default_factory=list)


@dataclass
class QConfig:
    """Extended Q configuration loaded from YAML.

    This does NOT replace ``config.AppConfig`` — it supplements it
    with target-specific and workflow settings.
    """

    # Model overrides (applied to AppConfig if set)
    model: str = ""
    fallback_model: str = ""

    # Agent overrides
    max_steps: int | None = None
    parallel_enabled: bool = True
    parallel_max: int = 3

    # CTF
    flag_format: str = ""

    # Target
    target: TargetConfig | None = None

    # Output
    report_dir: str = "reports"
    session_dir: str = "sessions"
    verbose: bool = False

    # Cost limits
    max_cost_per_challenge: float | None = None
    warn_cost: float = 0.20

    # Source path for the YAML file
    _source_path: str = ""


def load_yaml_config(config_path: str | None = None) -> QConfig:
    """Load configuration from a YAML file.

    Falls back to sensible defaults if the file is missing or None.
    Environment variables override YAML values.

    Args:
        config_path: Path to YAML config file.

    Returns:
        QConfig with all settings populated.
    """
    config = QConfig()

    if config_path and os.path.exists(config_path):
        try:
            import yaml
        except ImportError:
            # pyyaml not installed — return defaults
            config._source_path = config_path
            return config

        with open(config_path, encoding="utf-8") as fh:
            data: dict[str, Any] = yaml.safe_load(fh) or {}

        config._source_path = config_path

        # Model settings
        config.model = data.get("model", "")
        config.fallback_model = data.get("fallback_model", "")

        # Agent settings
        agent = data.get("agent", {})
        if "max_steps" in agent:
            config.max_steps = int(agent["max_steps"])
        config.parallel_enabled = agent.get("parallel", True)
        config.parallel_max = agent.get("parallel_max", 3)

        # CTF settings
        ctf = data.get("ctf", {})
        config.flag_format = ctf.get("flag_format", "")

        # Target settings
        target_data = data.get("target", {})
        if target_data:
            auth_data = target_data.get("auth", {})
            auth = None
            if auth_data:
                auth = AuthConfig(
                    login_url=auth_data.get("login_url", ""),
                    username=auth_data.get("username", ""),
                    password=auth_data.get("password", ""),
                    totp_secret=auth_data.get("totp_secret", ""),
                    login_flow=auth_data.get("login_flow", []),
                    success_condition=auth_data.get("success_condition", ""),
                )
            config.target = TargetConfig(
                url=target_data.get("url", ""),
                auth=auth,
                focus=target_data.get("focus", []),
                avoid=target_data.get("avoid", []),
            )

        # Output settings
        output = data.get("output", {})
        config.report_dir = output.get("report_dir", "reports")
        config.session_dir = output.get("session_dir", "sessions")
        config.verbose = output.get("verbose", False)

        # Cost limits
        cost = data.get("cost", {})
        if "max_per_challenge" in cost:
            config.max_cost_per_challenge = float(cost["max_per_challenge"])
        config.warn_cost = float(cost.get("warn_at", 0.20))

    # Environment variable overrides
    if os.getenv("Q_MODEL"):
        config.model = os.getenv("Q_MODEL", "")
    if os.getenv("Q_MAX_STEPS"):
        config.max_steps = int(os.getenv("Q_MAX_STEPS", "15"))
    if os.getenv("Q_VERBOSE"):
        config.verbose = os.getenv("Q_VERBOSE", "").lower() == "true"

    return config


def inject_target_to_prompt(config: QConfig) -> str:
    """Generate prompt additions from target configuration.

    Args:
        config: QConfig with target info.

    Returns:
        Markdown string to append to the system prompt, or "".
    """
    if not config.target:
        return ""

    parts: list[str] = ["\n## Target Configuration"]

    if config.target.url:
        parts.append(f"Target URL: {config.target.url}")

    if config.target.auth:
        auth = config.target.auth
        parts.append("\nAuthentication available:")
        if auth.login_url:
            parts.append(f"- Login URL: {auth.login_url}")
        if auth.username:
            parts.append(f"- Username: {auth.username}")
        if auth.password:
            parts.append(f"- Password: {auth.password}")
        if auth.totp_secret:
            parts.append(f"- TOTP Secret: {auth.totp_secret}")
        if auth.login_flow:
            parts.append("- Login steps:")
            for i, step in enumerate(auth.login_flow, 1):
                parts.append(f"  {i}. {step}")
        if auth.success_condition:
            parts.append(f"- Success condition: {auth.success_condition}")

    if config.target.focus:
        parts.append("\nFocus testing on:")
        for f in config.target.focus:
            parts.append(f"- {f}")

    if config.target.avoid:
        parts.append("\nAvoid these paths (do NOT test):")
        for a in config.target.avoid:
            parts.append(f"- {a}")

    return "\n".join(parts) + "\n"


def apply_yaml_to_appconfig(qcfg: QConfig, app_config: Any) -> Any:
    """Apply QConfig overrides to an existing AppConfig.

    Modifies the AppConfig in-place by creating new frozen dataclass
    instances where needed.

    Args:
        qcfg: YAML-derived configuration.
        app_config: Existing config.AppConfig instance.

    Returns:
        A new AppConfig with overrides applied.
    """
    new_model = replace(
        app_config.model,
        default_model=qcfg.model or app_config.model.default_model,
        fallback_model=qcfg.fallback_model or app_config.model.fallback_model,
    )

    new_agent = replace(
        app_config.agent,
        max_iterations=qcfg.max_steps or app_config.agent.max_iterations,
        max_cost_per_challenge=(
            qcfg.max_cost_per_challenge
            if qcfg.max_cost_per_challenge is not None
            else app_config.agent.max_cost_per_challenge
        ),
    )

    new_log = replace(
        app_config.log,
        session_dir=(
            Path(qcfg.session_dir) if qcfg.session_dir else app_config.log.session_dir
        ),
    )

    return replace(
        app_config,
        model=new_model,
        agent=new_agent,
        log=new_log,
    )


def config_summary(qcfg: QConfig) -> dict[str, str]:
    """Build a display-friendly config summary dict.

    Args:
        qcfg: QConfig instance.

    Returns:
        Ordered dict of setting name → value string.
    """
    summary: dict[str, str] = {}
    if qcfg._source_path:
        summary["Config file"] = qcfg._source_path
    if qcfg.model:
        summary["Model"] = qcfg.model
    if qcfg.max_steps:
        summary["Max steps"] = str(qcfg.max_steps)
    summary["Parallel"] = (
        f"{'enabled' if qcfg.parallel_enabled else 'disabled'} (max {qcfg.parallel_max})"
    )
    if qcfg.flag_format:
        summary["Flag format"] = qcfg.flag_format
    if qcfg.target:
        if qcfg.target.url:
            summary["Target URL"] = qcfg.target.url
        if qcfg.target.auth and qcfg.target.auth.username:
            summary["Auth"] = qcfg.target.auth.username
        if qcfg.target.focus:
            summary["Focus"] = ", ".join(qcfg.target.focus)
        if qcfg.target.avoid:
            summary["Avoid"] = ", ".join(qcfg.target.avoid)
    if qcfg.max_cost_per_challenge is not None:
        summary["Cost limit"] = f"${qcfg.max_cost_per_challenge:.2f}/challenge"
    summary["Warn cost"] = f"${qcfg.warn_cost:.2f}"
    return summary
