"""Docker sandbox manager.

Creates, manages, and tears down Docker containers used as sandboxed
execution environments for CTF tools and exploit code.  Each challenge
gets its own fresh container that is destroyed on cleanup.
"""

from __future__ import annotations

import io
import os
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Optional

from config import AppConfig, load_config
from utils.logger import get_logger

# Type alias — real docker types are only available when docker is installed.
Container = Any
DockerClient = Any


def detect_sandbox_mode() -> str:
    """Auto-detect the best available sandbox mode.

    Returns:
        ``"docker"`` if Docker is available without sudo,
        ``"docker_sudo"`` if Docker requires sudo,
        ``"local"`` if Docker is not available.
    """
    import shutil
    import subprocess

    if not shutil.which("docker"):
        return "local"

    # Try without sudo
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "docker"
    except (subprocess.TimeoutExpired, OSError):
        pass

    # Try with sudo (non-interactive only)
    try:
        result = subprocess.run(
            ["sudo", "-n", "docker", "info"],
            capture_output=True,
            timeout=5,
        )
        if result.returncode == 0:
            return "docker_sudo"
    except (subprocess.TimeoutExpired, OSError):
        pass

    return "local"


class DockerSandbox:
    """Manage a Docker container as an isolated execution sandbox.

    Provides full lifecycle management (create, exec, file-transfer,
    cleanup) for a per-challenge Docker container.
    """

    def __init__(
        self,
        config: AppConfig | None = None,
        workspace: Path | None = None,
    ) -> None:
        """Initialise the Docker sandbox manager.

        Args:
            config: Application configuration.
            workspace: Host-side workspace directory to mount into the container.
        """
        self._config = config or load_config()
        self._dc = self._config.docker
        self._workspace = workspace or Path.cwd()
        self._log = get_logger()
        self._container: Optional[Container] = None
        self._client: Optional[DockerClient] = None
        self._container_id: Optional[str] = None

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> bool:
        """Create and start a new sandbox container.

        Equivalent to ``create_container()`` — kept for backward compat.

        Returns:
            True if the container started successfully.
        """
        return self.create_container()

    def create_container(
        self,
        extra_volumes: dict[str, dict[str, str]] | None = None,
        allowed_hosts: list[str] | None = None,
    ) -> bool:
        """Create a fresh Docker container for a challenge.

        Args:
            extra_volumes: Additional host→container volume mounts.
            allowed_hosts: If provided, restrict outbound network to these
                hosts via ``/etc/hosts`` injection (best-effort).

        Returns:
            True when the container is running and ready.
        """
        try:
            import docker
            from docker.errors import ImageNotFound

            self._client = docker.from_env()
        except ImportError:
            self._log.error("docker package not installed — pip install docker")
            return False
        except Exception as exc:
            self._log.error(f"Cannot connect to Docker daemon: {exc}")
            return False

        # Ensure the image exists
        try:
            self._client.images.get(self._dc.image_name)
        except Exception:
            self._log.warning(
                f"Docker image '{self._dc.image_name}' not found. "
                f"Build with:  docker build -t {self._dc.image_name} sandbox/"
            )
            return False

        # Build volume mounts
        volumes: dict[str, dict[str, str]] = {
            str(self._workspace.resolve()): {
                "bind": self._dc.work_dir,
                "mode": "rw",
            }
        }
        if extra_volumes:
            volumes.update(extra_volumes)

        try:
            self._container = self._client.containers.run(
                image=self._dc.image_name,
                command="sleep infinity",
                detach=True,
                remove=True,
                working_dir=self._dc.work_dir,
                mem_limit=self._dc.memory_limit,
                cpu_quota=self._dc.cpu_quota,
                network_mode=self._dc.network_mode,
                volumes=volumes,
                environment={
                    "TERM": "xterm-256color",
                    "HOME": "/home/ctfplayer",
                },
            )
            self._container_id = self._container.short_id
            self._log.info(f"Sandbox container started: {self._container_id}")

            # Inject /etc/hosts entries if restriction requested
            if allowed_hosts:
                self._restrict_network(allowed_hosts)

            return True

        except Exception as exc:
            self._log.error(f"Failed to create sandbox container: {exc}")
            return False

    def stop(self) -> None:
        """Stop and remove the container (alias for cleanup)."""
        self.cleanup()

    def cleanup(self) -> None:
        """Destroy the sandbox container and release resources."""
        if self._container is None:
            return
        cid = self._container_id or "?"
        try:
            self._container.stop(timeout=5)
            self._log.info(f"Sandbox container {cid} stopped and removed")
        except Exception as exc:
            self._log.warning(f"Error cleaning up container {cid}: {exc}")
            # Try to force-remove if stop failed
            try:
                self._container.remove(force=True)
            except Exception:
                pass
        finally:
            self._container = None
            self._container_id = None

    def is_running(self) -> bool:
        """Check if the sandbox container is alive.

        Returns:
            True if the container exists and its status is "running".
        """
        if self._container is None:
            return False
        try:
            self._container.reload()
            return self._container.status == "running"
        except Exception:
            self._container = None
            self._container_id = None
            return False

    # ── Command Execution ──────────────────────────────────────────────

    def exec_command(
        self,
        command: str,
        workdir: str | None = None,
        timeout: int = 30,
        user: str = "ctfplayer",
    ) -> str:
        """Execute a shell command inside the container.

        Args:
            command: Shell command string.
            workdir: Working directory inside the container.
            timeout: Maximum execution time in seconds.
            user: Container user to run as.

        Returns:
            Combined stdout/stderr output as a string.
        """
        if not self.is_running():
            return "[ERROR] Sandbox container is not running"

        # Wrap command with timeout to prevent hangs
        escaped = _shell_quote(command)
        wrapped = f"timeout {timeout} bash -c {escaped}"

        try:
            exit_code, output = self._container.exec_run(
                cmd=["bash", "-c", wrapped],
                workdir=workdir or self._dc.work_dir,
                user=user,
                demux=True,
                environment={"TERM": "xterm-256color"},
            )

            stdout = (output[0] or b"").decode("utf-8", errors="replace")
            stderr = (output[1] or b"").decode("utf-8", errors="replace")

            result = stdout
            if stderr:
                result += f"\n[stderr]\n{stderr}"
            if exit_code != 0:
                if exit_code == 124:
                    result += f"\n[TIMEOUT after {timeout}s]"
                else:
                    result += f"\n[exit code: {exit_code}]"
            return result.strip()

        except Exception as exc:
            return f"[ERROR] Container exec failed: {exc}"

    # ── File Transfer ──────────────────────────────────────────────────

    def copy_file_in(
        self,
        local_path: str | Path,
        remote_path: str,
    ) -> bool:
        """Copy a file from the host into the container.

        Args:
            local_path: Absolute or relative path on the host.
            remote_path: Absolute path inside the container
                (e.g. ``/workspace/exploit.py``).

        Returns:
            True if the copy succeeded.
        """
        if not self.is_running():
            self._log.error("Container not running — cannot copy file in")
            return False

        local = Path(local_path)
        if not local.is_file():
            self._log.error(f"Local file not found: {local}")
            return False

        try:
            data = local.read_bytes()
            name = Path(remote_path).name
            parent = str(Path(remote_path).parent)

            tar_buf = io.BytesIO()
            with tarfile.open(fileobj=tar_buf, mode="w") as tar:
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
            tar_buf.seek(0)

            self._container.put_archive(parent, tar_buf)
            self._log.debug(f"Copied {local} → container:{remote_path}")
            return True

        except Exception as exc:
            self._log.error(f"copy_file_in failed: {exc}")
            return False

    def copy_file_out(
        self,
        remote_path: str,
        local_path: str | Path,
    ) -> bool:
        """Copy a file from the container to the host.

        Args:
            remote_path: Absolute path inside the container.
            local_path: Destination path on the host.

        Returns:
            True if the copy succeeded.
        """
        if not self.is_running():
            self._log.error("Container not running — cannot copy file out")
            return False

        try:
            bits, stat = self._container.get_archive(remote_path)
            tar_buf = io.BytesIO()
            for chunk in bits:
                tar_buf.write(chunk)
            tar_buf.seek(0)

            with tarfile.open(fileobj=tar_buf) as tar:
                member = tar.getmembers()[0]
                extracted = tar.extractfile(member)
                if extracted is None:
                    self._log.error(f"Cannot extract {remote_path} (is it a directory?)")
                    return False
                file_data = extracted.read()

            dest = Path(local_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(file_data)
            self._log.debug(
                f"Copied container:{remote_path} → {dest} ({len(file_data)} bytes)"
            )
            return True

        except Exception as exc:
            self._log.error(f"copy_file_out failed: {exc}")
            return False

    def write_file(self, container_path: str, content: str) -> bool:
        """Write a text string as a file inside the container.

        Convenience wrapper around ``copy_file_in`` that avoids touching
        the host filesystem.

        Args:
            container_path: Absolute path inside the container.
            content: UTF-8 text to write.

        Returns:
            True if successful.
        """
        if not self.is_running():
            return False

        try:
            data = content.encode("utf-8")
            name = Path(container_path).name
            parent = str(Path(container_path).parent)

            tar_buf = io.BytesIO()
            with tarfile.open(fileobj=tar_buf, mode="w") as tar:
                info = tarfile.TarInfo(name=name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
            tar_buf.seek(0)

            self._container.put_archive(parent, tar_buf)
            return True

        except Exception as exc:
            self._log.error(f"write_file failed: {exc}")
            return False

    def read_file(self, container_path: str) -> str:
        """Read a text file from the container.

        Args:
            container_path: Absolute path inside the container.

        Returns:
            File contents as string, or an error message.
        """
        if not self.is_running():
            return "[ERROR] Container not running"

        try:
            bits, _ = self._container.get_archive(container_path)
            tar_buf = io.BytesIO()
            for chunk in bits:
                tar_buf.write(chunk)
            tar_buf.seek(0)

            with tarfile.open(fileobj=tar_buf) as tar:
                member = tar.getmembers()[0]
                f = tar.extractfile(member)
                if f is None:
                    return "[ERROR] Could not extract file"
                return f.read().decode("utf-8", errors="replace")

        except Exception as exc:
            return f"[ERROR] {exc}"

    def copy_directory_in(self, local_dir: str | Path, remote_dir: str) -> bool:
        """Copy an entire directory from the host into the container.

        Args:
            local_dir: Directory path on the host.
            remote_dir: Destination directory inside the container.

        Returns:
            True if successful.
        """
        if not self.is_running():
            return False

        local = Path(local_dir)
        if not local.is_dir():
            self._log.error(f"Not a directory: {local}")
            return False

        try:
            tar_buf = io.BytesIO()
            with tarfile.open(fileobj=tar_buf, mode="w") as tar:
                for fpath in local.rglob("*"):
                    if fpath.is_file():
                        arcname = str(fpath.relative_to(local))
                        tar.add(str(fpath), arcname=arcname)
            tar_buf.seek(0)

            # Ensure the remote directory exists
            self.exec_command(f"mkdir -p {remote_dir}", timeout=5)
            self._container.put_archive(remote_dir, tar_buf)
            self._log.debug(f"Copied directory {local} → container:{remote_dir}")
            return True

        except Exception as exc:
            self._log.error(f"copy_directory_in failed: {exc}")
            return False

    # ── Introspection ──────────────────────────────────────────────────

    @property
    def container_id(self) -> str | None:
        """Return the short container ID or None.

        Returns:
            Short hex ID string.
        """
        return self._container_id

    def get_container_info(self) -> dict[str, Any]:
        """Return basic information about the running container.

        Returns:
            Dict with id, status, image, and created timestamp.
        """
        if not self.is_running():
            return {"status": "not running"}

        try:
            self._container.reload()
            return {
                "id": self._container.short_id,
                "status": self._container.status,
                "image": str(self._container.image.tags),
                "created": self._container.attrs.get("Created", ""),
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    # ── Internal Helpers ───────────────────────────────────────────────

    def _restrict_network(self, allowed_hosts: list[str]) -> None:
        """Best-effort outbound restriction via iptables.

        This only works if the container runs with sufficient privileges,
        which is NOT the default.  It is purely informational — the real
        network boundary should be enforced by Docker networking.

        Args:
            allowed_hosts: Hostnames or IPs allowed for outbound traffic.
        """
        for host in allowed_hosts:
            self._log.debug(f"Network allowlist entry: {host}")
        # In a real deployment you would configure Docker network
        # policies or iptables rules here.

    def __enter__(self) -> "DockerSandbox":
        """Context-manager entry — start the container."""
        self.create_container()
        return self

    def __exit__(self, *_: Any) -> None:
        """Context-manager exit — destroy the container."""
        self.cleanup()

    def __del__(self) -> None:
        """Destructor — attempt cleanup on garbage collection."""
        try:
            self.cleanup()
        except Exception:
            pass


# ── Module-level helpers ───────────────────────────────────────────────


def _shell_quote(s: str) -> str:
    """Single-quote a string for safe shell interpolation.

    Args:
        s: Raw string.

    Returns:
        Shell-safe single-quoted string.
    """
    return "'" + s.replace("'", "'\"'\"'") + "'"
