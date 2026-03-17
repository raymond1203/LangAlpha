"""Docker sandbox provider — runs sandboxes as local Docker containers.

Uses ``aiodocker`` for all container operations. Two file-I/O modes are
supported:

* **tar mode** (default) -- files are transferred via the Docker
  ``put_archive`` / ``get_archive`` API.
* **bind-mount mode** (``dev_mode=True``) -- a host directory is mounted
  into the container so the host filesystem can be used directly.
"""

from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import shlex
import tarfile
import uuid
from typing import Any

import structlog

from ptc_agent.config.core import DockerConfig
from ptc_agent.core.sandbox.providers._chart_capture import (
    build_code_wrapper,
    extract_artifacts,
)
from ptc_agent.core.sandbox.runtime import (
    CodeRunResult,
    ExecResult,
    RuntimeState,
    SandboxProvider,
    SandboxRuntime,
    SandboxTransientError,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# State mapping
# ---------------------------------------------------------------------------
_DOCKER_STATE_MAP: dict[str, RuntimeState] = {
    "running": RuntimeState.RUNNING,
    "created": RuntimeState.STOPPED,
    "exited": RuntimeState.STOPPED,
    "paused": RuntimeState.STOPPED,
    "dead": RuntimeState.ERROR,
    "restarting": RuntimeState.STARTING,
    "removing": RuntimeState.STOPPING,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_memory(limit_str: str) -> int:
    """Convert a human-friendly memory string (e.g. ``"4g"``) to bytes."""
    limit_str = limit_str.strip().lower()
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([kmgt])?b?", limit_str)
    if not match:
        raise ValueError(f"Cannot parse memory limit: {limit_str!r}")
    value = float(match.group(1))
    suffix = match.group(2) or ""
    multipliers = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
    return int(value * multipliers[suffix])


# ---------------------------------------------------------------------------
# DockerRuntime
# ---------------------------------------------------------------------------


class DockerRuntime(SandboxRuntime):
    """Runtime that wraps a single Docker container."""

    def __init__(
        self,
        container: Any,  # aiodocker.containers.DockerContainer
        *,
        runtime_id: str,
        working_dir: str = "/home/sandbox",
        dev_mode: bool = False,
        host_work_dir: str | None = None,
    ) -> None:
        self._container = container
        self._id = runtime_id
        self._working_dir = working_dir
        self._dev_mode = dev_mode
        self._host_work_dir = host_work_dir

    # -- Properties --

    @property
    def id(self) -> str:
        return self._id

    @property
    def working_dir(self) -> str:
        return self._working_dir

    async def fetch_working_dir(self) -> str:
        return self._working_dir

    # -- Lifecycle --

    async def start(self, timeout: int = 120) -> None:
        await self._container.start()

    async def stop(self, timeout: int = 60) -> None:
        await self._container.stop(t=timeout)

    async def delete(self) -> None:
        try:
            await self._container.stop(t=5)
        except Exception:
            pass
        await self._container.delete(force=True)

    async def get_state(self) -> RuntimeState:
        info = await self._container.show()
        status = info.get("State", {}).get("Status", "unknown")
        return _DOCKER_STATE_MAP.get(status, RuntimeState.ERROR)

    # -- Execution --

    async def exec(self, command: str, timeout: int = 60) -> ExecResult:
        try:
            exec_obj = await self._container.exec(
                cmd=["bash", "-c", command],
                workdir=self._working_dir,
            )
            # Read all output from the multiplexed stream
            stdout_parts: list[str] = []

            async def _read_stream() -> None:
                async with exec_obj.start() as stream:
                    while True:
                        msg = await stream.read_out()
                        if msg is None:
                            break
                        stdout_parts.append(msg.data.decode("utf-8", errors="replace"))

            await asyncio.wait_for(_read_stream(), timeout=timeout)

            combined = "".join(stdout_parts)

            # Get exit code
            inspect = await exec_obj.inspect()
            exit_code = inspect.get("ExitCode", -1)

            return ExecResult(stdout=combined, stderr="", exit_code=exit_code)
        except asyncio.TimeoutError:
            return ExecResult(stdout="", stderr="timeout", exit_code=-1)
        except Exception as e:
            if _is_container_gone(e):
                raise SandboxTransientError(str(e)) from e
            return ExecResult(stdout="", stderr=str(e), exit_code=-1)

    async def code_run(
        self,
        code: str,
        env: dict[str, str] | None = None,
        timeout: int = 300,
    ) -> CodeRunResult:
        wrapper = build_code_wrapper(code)
        encoded = base64.b64encode(wrapper.encode("utf-8")).decode("ascii")

        script_name = f"_exec_{uuid.uuid4().hex[:8]}.py"
        script_path = f"{self._working_dir}/{script_name}"

        # Write script via exec (avoids tar overhead for a single small file)
        write_cmd = (
            f"python3 -c \"import base64,sys; "
            f"sys.stdout.buffer.write(base64.b64decode('{encoded}'))\" "
            f"> {script_path}"
        )
        write_result = await self.exec(write_cmd, timeout=15)
        if write_result.exit_code != 0:
            return CodeRunResult(
                stdout="",
                stderr=f"Failed to write script: {write_result.stderr or write_result.stdout}",
                exit_code=write_result.exit_code,
                artifacts=[],
            )

        # Build environment exports
        env_prefix = ""
        if env:
            exports = " ".join(f"{k}={_shell_escape(v)}" for k, v in env.items())
            env_prefix = f"export {exports} && "

        stderr_path = f"{self._working_dir}/_stderr_{uuid.uuid4().hex[:8]}.txt"
        run_cmd = f"{env_prefix}python3 {script_path} 2>{stderr_path}"

        # Run the code — we parse combined stdout for artifacts
        exec_result = await self.exec(run_cmd, timeout=timeout)

        # Extract chart artifacts from stdout markers
        artifacts, clean_stdout = extract_artifacts(exec_result.stdout)

        # Read stderr from temp file only on failure (avoids extra exec round-trip
        # on the happy path — the consumer only needs stderr for auto-install detection)
        stderr = ""
        if exec_result.exit_code != 0:
            try:
                cat_result = await self.exec(f"cat {stderr_path} 2>/dev/null", timeout=5)
                if cat_result.exit_code == 0:
                    stderr = cat_result.stdout
            except Exception:
                pass

        # Cleanup temp files (best-effort)
        try:
            await self.exec(f"rm -f {script_path} {stderr_path}", timeout=5)
        except Exception:
            pass

        return CodeRunResult(
            stdout=clean_stdout,
            stderr=stderr,
            exit_code=exec_result.exit_code,
            artifacts=artifacts,
        )

    # -- File I/O --

    async def upload_file(self, content: bytes, dest_path: str) -> None:
        if self._dev_mode and self._host_work_dir:
            self._host_write(dest_path, content)
        else:
            await self._tar_upload(dest_path, content)

    async def upload_files(self, files: list[tuple[bytes | str, str]]) -> None:
        if self._dev_mode and self._host_work_dir:
            for source, dest in files:
                data = _read_source(source)
                self._host_write(dest, data)
            return

        # Tar mode: batch all files into a single tar + one put_archive call.
        prepared: list[tuple[bytes, str]] = []
        parent_dirs: set[str] = set()
        for source, dest in files:
            data = _read_source(source)
            prepared.append((data, dest))
            parent = os.path.dirname(dest)
            if parent:
                parent_dirs.add(parent)

        if not prepared:
            return

        # Best-effort mkdir for parent dirs (tar extraction at "/" should
        # create them anyway, but this avoids permission issues).
        if parent_dirs:
            mkdir_cmd = "mkdir -p " + " ".join(
                f"'{d}'" for d in sorted(parent_dirs)
            )
            await self.exec(mkdir_cmd, timeout=30)

        # Build one tar archive with full absolute paths.
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            for data, dest_path in prepared:
                tar_name = dest_path.lstrip("/")
                info = tarfile.TarInfo(name=tar_name)
                info.size = len(data)
                info.mode = 0o644
                tar.addfile(info, io.BytesIO(data))
        buf.seek(0)

        await self._container.put_archive("/", buf.read())

    async def download_file(self, path: str) -> bytes:
        if self._dev_mode and self._host_work_dir:
            return self._host_read(path)
        return await self._exec_download(path)

    async def list_files(self, directory: str) -> list[dict[str, Any]]:
        resolved = directory if os.path.isabs(directory) else f"{self._working_dir}/{directory}"
        result = await self.exec(
            f"find {shlex.quote(resolved)} -maxdepth 1 -mindepth 1 -printf '%f\\t%y\\n' 2>/dev/null || "
            f"ls -1 {shlex.quote(resolved)} 2>/dev/null",
            timeout=15,
        )
        entries: list[dict[str, Any]] = []
        if result.exit_code != 0 or not result.stdout.strip():
            return entries
        for line in result.stdout.strip().split("\n"):
            if "\t" in line:
                name, ftype = line.split("\t", 1)
                entries.append({"name": name, "is_dir": ftype == "d"})
            else:
                entries.append({"name": line.strip(), "is_dir": False})
        return entries

    # -- Capabilities & metadata --

    @property
    def capabilities(self) -> set[str]:
        return {"exec", "code_run", "file_io"}

    async def archive(self) -> None:
        raise NotImplementedError("Docker provider does not support archive")

    async def get_metadata(self) -> dict[str, Any]:
        state = await self.get_state()
        return {
            "id": self._id,
            "working_dir": self._working_dir,
            "state": state.value,
            "dev_mode": self._dev_mode,
            "provider": "docker",
        }

    # -- Internal: tar-based file I/O --

    async def _tar_upload(self, dest_path: str, content: bytes) -> None:
        """Upload a single file into the container via a tar archive.

        Uses ``put_archive("/", ...)`` with the full path encoded in the tar
        entry so we don't depend on the parent directory already existing.
        """
        parent = os.path.dirname(dest_path)
        if parent:
            await self.exec(f"mkdir -p {shlex.quote(parent)}", timeout=10)

        buf = io.BytesIO()
        tar_name = dest_path.lstrip("/")
        with tarfile.open(fileobj=buf, mode="w") as tar:
            info = tarfile.TarInfo(name=tar_name)
            info.size = len(content)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(content))
        buf.seek(0)

        await self._container.put_archive("/", buf.read())

    async def _exec_download(self, path: str) -> bytes:
        """Download a file via exec + base64 (avoids Docker archive API issues)."""
        result = await self.exec(
            f"test -f {shlex.quote(path)} && base64 {shlex.quote(path)}", timeout=60,
        )
        if result.exit_code != 0:
            raise FileNotFoundError(f"File not found or unreadable: {path}")
        return base64.b64decode(result.stdout)

    # -- Internal: bind-mount file I/O --

    def _host_resolve(self, sandbox_path: str) -> str:
        """Map a sandbox path to a host filesystem path."""
        assert self._host_work_dir is not None
        if sandbox_path.startswith(self._working_dir + "/"):
            relative = sandbox_path[len(self._working_dir) + 1 :]
        elif sandbox_path.startswith(self._working_dir):
            relative = sandbox_path[len(self._working_dir) :]
        else:
            relative = sandbox_path.lstrip("/")
        return os.path.join(self._host_work_dir, relative)

    def _host_write(self, sandbox_path: str, content: bytes) -> None:
        host_path = self._host_resolve(sandbox_path)
        os.makedirs(os.path.dirname(host_path), exist_ok=True)
        with open(host_path, "wb") as f:
            f.write(content)

    def _host_read(self, sandbox_path: str) -> bytes:
        host_path = self._host_resolve(sandbox_path)
        if not os.path.exists(host_path):
            raise FileNotFoundError(f"File not found: {sandbox_path}")
        with open(host_path, "rb") as f:
            return f.read()


# ---------------------------------------------------------------------------
# DockerProvider
# ---------------------------------------------------------------------------


class DockerProvider(SandboxProvider):
    """Provider that manages sandboxes as Docker containers."""

    def __init__(self, config: DockerConfig, working_dir: str | None = None) -> None:
        self._config = config
        # filesystem.working_directory is the single source of truth;
        # fall back to DockerConfig.working_dir only if not provided.
        self._working_dir = working_dir or config.working_dir
        self._client: Any | None = None  # aiodocker.Docker (lazy)

    async def _get_client(self) -> Any:
        """Return the aiodocker client, creating it lazily."""
        if self._client is None:
            import aiodocker

            self._client = aiodocker.Docker()
        return self._client

    # -- SandboxProvider interface --

    async def create(
        self,
        *,
        env_vars: dict[str, str] | None = None,
        mcp_packages: list[str] | None = None,
        **kwargs: Any,
    ) -> DockerRuntime:
        client = await self._get_client()
        await self._ensure_image(client)

        runtime_id = f"docker-{uuid.uuid4().hex[:12]}"
        container_name = f"langalpha-sandbox-{runtime_id}"

        # Build container config
        host_config: dict[str, Any] = {
            "Memory": _parse_memory(self._config.memory_limit),
            "NanoCpus": int(self._config.cpu_count * 1e9),
            "NetworkMode": self._config.network_mode,
            "AutoRemove": False,  # We manage removal ourselves
        }

        binds: list[str] = list(self._config.volumes)  # extra user-defined mounts
        host_work_dir: str | None = None

        if self._config.dev_mode and self._config.host_work_dir:
            host_work_dir = self._config.host_work_dir
            os.makedirs(host_work_dir, exist_ok=True)
            binds.append(f"{host_work_dir}:{self._working_dir}")

        if binds:
            host_config["Binds"] = binds

        container_config: dict[str, Any] = {
            "Image": self._config.image,
            "Cmd": ["sleep", "infinity"],
            "WorkingDir": self._working_dir,
            "Hostname": "sandbox",
            "HostConfig": host_config,
        }

        if env_vars:
            container_config["Env"] = [f"{k}={v}" for k, v in env_vars.items()]

        container_obj = await client.containers.create(
            config=container_config,
            name=container_name,
        )
        await container_obj.start()

        logger.info(
            "Docker container started",
            container_name=container_name,
            runtime_id=runtime_id,
            image=self._config.image,
        )

        runtime = DockerRuntime(
            container_obj,
            runtime_id=runtime_id,
            working_dir=self._working_dir,
            dev_mode=self._config.dev_mode,
            host_work_dir=host_work_dir,
        )

        # Install MCP npm packages if needed (mirrors Daytona snapshot behavior)
        if mcp_packages:
            pkgs = " ".join(mcp_packages)
            logger.info("Installing MCP packages in Docker container", packages=pkgs)
            result = await runtime.exec(f"npm install -g {pkgs}", timeout=120)
            if result.exit_code != 0:
                logger.warning(
                    "Failed to install MCP packages (npx will download on demand)",
                    packages=pkgs,
                    output=result.stdout,
                )

        return runtime

    async def get(self, sandbox_id: str) -> DockerRuntime:
        client = await self._get_client()
        container_name = f"langalpha-sandbox-{sandbox_id}"

        try:
            container_obj = await client.containers.get(container_name)
        except Exception as e:
            raise RuntimeError(
                f"Docker container not found: {container_name}"
            ) from e

        info = await container_obj.show()
        mounts = info.get("Mounts", [])

        # Detect dev_mode from existing bind mounts
        dev_mode = False
        host_work_dir = None
        for mount in mounts:
            if mount.get("Destination") == self._working_dir:
                dev_mode = True
                host_work_dir = mount.get("Source")
                break

        return DockerRuntime(
            container_obj,
            runtime_id=sandbox_id,
            working_dir=self._working_dir,
            dev_mode=dev_mode,
            host_work_dir=host_work_dir,
        )

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as e:
                logger.debug("Failed to close Docker client", error=str(e))
            finally:
                self._client = None

    def is_transient_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        transient_markers = (
            "connection refused",
            "connection reset",
            "connection aborted",
            "broken pipe",
            "timed out",
            "timeout",
        )
        return any(marker in msg for marker in transient_markers)

    # -- Internal --

    async def _ensure_image(self, client: Any) -> None:
        """Ensure the sandbox image exists, auto-building from Dockerfile.sandbox if needed."""
        try:
            await client.images.inspect(self._config.image)
            logger.debug("Docker image found", image=self._config.image)
            return
        except Exception:
            pass  # Image not found -- try to build

        logger.info(
            "Docker image not found, attempting to build",
            image=self._config.image,
        )

        # Look for Dockerfile.sandbox relative to the repo root
        dockerfile_name = "Dockerfile.sandbox"
        # Try common locations
        search_paths = [
            os.path.join(os.getcwd(), dockerfile_name),
        ]
        # Also check relative to this file's location (up to repo root)
        module_dir = os.path.dirname(os.path.abspath(__file__))
        for _ in range(6):  # Walk up to 6 levels
            candidate = os.path.join(module_dir, dockerfile_name)
            search_paths.append(candidate)
            module_dir = os.path.dirname(module_dir)

        dockerfile_path = None
        for path in search_paths:
            if os.path.isfile(path):
                dockerfile_path = path
                break

        if dockerfile_path is None:
            raise RuntimeError(
                f"Docker image {self._config.image!r} not found and "
                f"{dockerfile_name} not found in any search path. "
                f"Build the image manually or place {dockerfile_name} in the repo root."
            )

        build_context = os.path.dirname(dockerfile_path)
        image_tag = self._config.image

        logger.info(
            "Building Docker sandbox image",
            dockerfile=dockerfile_path,
            tag=image_tag,
        )

        # Use aiodocker to build
        try:
            # aiodocker build expects a tar context or path
            async for log_line in client.images.build(
                path=build_context,
                dockerfile=os.path.basename(dockerfile_path),
                tag=image_tag,
                rm=True,
            ):
                if isinstance(log_line, dict) and "stream" in log_line:
                    line = log_line["stream"].strip()
                    if line:
                        logger.debug("Docker build", log=line)
                elif isinstance(log_line, dict) and "error" in log_line:
                    raise RuntimeError(f"Docker build failed: {log_line['error']}")
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"Failed to build Docker image {image_tag!r}: {e}"
            ) from e

        logger.info("Docker sandbox image built", image=image_tag)


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _read_source(source: bytes | str) -> bytes:
    """Read file content from bytes or a local file path."""
    if isinstance(source, str):
        with open(source, "rb") as f:
            return f.read()
    return source


def _shell_escape(value: str) -> str:
    """Shell-escape a value for use in an export command."""
    return "'" + value.replace("'", "'\\''") + "'"


def _is_container_gone(exc: Exception) -> bool:
    """Check if an exception indicates the container no longer exists."""
    msg = str(exc).lower()
    return "no such container" in msg or "not found" in msg or "409" in msg
