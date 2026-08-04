"""Preflight checks for the things a run silently degrades without.

Motivation: a run was once started against a Docker that answered `docker info`
successfully but could not actually execute anything, because PATH resolved to the
Windows `docker.exe` under WSL rather than a Linux client. Every sandbox execution
failed while the crew kept spending money writing code it could not test.

`docker info` is therefore not a sufficient check. What matters is whether a
container can run *and* see a bind-mounted sandbox directory, which is what
:func:`check_docker` actually verifies.

Run standalone::

    uv run python -m engineering_team.preflight
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str
    remedy: str = ""

    def render(self) -> str:
        mark = "PASS" if self.ok else "FAIL"
        line = f"  [{mark}] {self.name}: {self.detail}"
        if not self.ok and self.remedy:
            line += f"\n         -> {self.remedy}"
        return line


WSL_INTEGRATION_OFF = (
    "Docker Desktop > Settings > Resources > WSL Integration > enable this distro, "
    "then Apply & Restart. A Windows docker.exe on PATH cannot bind-mount Linux paths."
)

WSL_STALE_SESSION = (
    "Docker Desktop is running and integration IS enabled for this distro, but this "
    "shell's mount namespace predates it, so the injected binary and socket are stale. "
    "Run `wsl --shutdown` in Windows PowerShell, then open a new terminal. "
    "(Toggling the integration setting will not fix an already-running session.)"
)


def _wsl_docker_diagnosis() -> str:
    """Distinguish 'integration never enabled' from 'this session missed the injection'.

    Docker Desktop injects its CLI and socket into running distros as bind mounts. A
    shell started before Docker Desktop keeps a namespace without them — and may hold
    mounts marked `//deleted` from an earlier Desktop lifetime. That is not a settings
    problem and toggling the setting does not repair it.
    """
    if not Path("/mnt/wsl/docker-desktop").exists():
        return WSL_INTEGRATION_OFF

    distro = os.environ.get("WSL_DISTRO_NAME", "")
    injected = Path("/mnt/wsl/docker-desktop-bind-mounts") / distro
    stale_mount = False
    try:
        stale_mount = "//deleted" in Path("/proc/self/mountinfo").read_text(
            encoding="utf-8"
        )
    except OSError:
        pass

    if injected.exists() or stale_mount:
        return WSL_STALE_SESSION
    return WSL_INTEGRATION_OFF


# Kept for callers that want the generic message without diagnosis.
WSL_REMEDY = WSL_INTEGRATION_OFF


def check_docker(timeout: int = 120) -> CheckResult:
    """Verify a container can run and actually see a bind-mounted host directory."""
    binary = shutil.which("docker")
    if binary is None:
        return CheckResult("docker", False, "no Linux docker on PATH", _wsl_docker_diagnosis())

    # Under WSL, a Windows binary starts containers but silently mounts nothing.
    if binary.startswith("/mnt/"):
        return CheckResult(
            "docker",
            False,
            f"PATH resolves to a Windows binary ({binary}); bind mounts will be empty",
            _wsl_docker_diagnosis(),
        )

    try:
        info = subprocess.run(
            [binary, "info"], capture_output=True, text=True, timeout=timeout
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return CheckResult("docker", False, f"docker info failed: {exc}", _wsl_docker_diagnosis())

    if info.returncode != 0:
        detail = (info.stderr or info.stdout).strip().splitlines()
        return CheckResult(
            "docker", False, detail[0] if detail else "daemon unreachable", _wsl_docker_diagnosis()
        )

    # The check that matters: does the container see what we mounted?
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "probe.txt").write_text("ok", encoding="utf-8")
        try:
            run = subprocess.run(
                [
                    binary, "run", "--rm",
                    "-v", f"{tmp}:/probe",
                    "-w", "/probe",
                    "busybox:latest",
                    "cat", "probe.txt",
                ],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return CheckResult("docker", False, f"container run failed: {exc}", _wsl_docker_diagnosis())

    if run.returncode != 0 or run.stdout.strip() != "ok":
        return CheckResult(
            "docker",
            False,
            "container ran but the bind mount was empty — host files are invisible to it",
            _wsl_docker_diagnosis(),
        )

    return CheckResult("docker", True, f"{binary}, bind mounts working")


def check_api_key(name: str = "OPENROUTER_API_KEY") -> CheckResult:
    """Confirm a key is set without ever revealing its value."""
    value = os.environ.get(name)
    if not value:
        return CheckResult(
            name, False, "not set", f"add {name} to .env (never print its value)"
        )
    return CheckResult(name, True, f"set ({len(value)} chars)")


def check_uv() -> CheckResult:
    binary = shutil.which("uv")
    if binary is None:
        return CheckResult("uv", False, "not on PATH", "install uv: pip install uv")
    return CheckResult("uv", True, binary)


def run_all(*, require_docker: bool = True) -> list[CheckResult]:
    checks = [check_uv(), check_api_key()]
    if require_docker:
        checks.append(check_docker())
    return checks


def assert_ready(*, require_docker: bool = True) -> None:
    """Raise before a run rather than failing silently partway through it.

    Raises:
        RuntimeError: If any check fails.
    """
    results = run_all(require_docker=require_docker)
    print("Preflight:")
    for result in results:
        print(result.render())

    failed = [r for r in results if not r.ok]
    if failed:
        raise RuntimeError(
            "Preflight failed: "
            + ", ".join(r.name for r in failed)
            + ". Fix the above before running; otherwise agents write code they cannot test."
        )
    print()


if __name__ == "__main__":
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv(usecwd=True))
    try:
        assert_ready()
    except RuntimeError as exc:
        print(f"\n{exc}")
        raise SystemExit(1) from exc
    print("All preflight checks passed.")
