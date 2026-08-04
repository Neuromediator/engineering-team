"""Tests for preflight checks.

These exist because a run once started against a Docker that answered `docker info`
successfully but could not bind-mount anything, so every sandbox execution failed
while the crew kept spending money. `docker info` passing is not the same as Docker
working.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from engineering_team import preflight  # noqa: E402


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class DockerCheckTest(unittest.TestCase):
    def test_missing_binary_fails(self):
        with mock.patch("shutil.which", return_value=None):
            result = preflight.check_docker()
        self.assertFalse(result.ok)
        self.assertIn("no docker on PATH", result.detail)

    def test_windows_binary_under_wsl_is_rejected(self):
        """The regression this module exists for: docker.exe runs but mounts nothing."""
        win = "/mnt/c/Program Files/Docker/Docker/resources/bin/docker"
        with mock.patch("shutil.which", return_value=win):
            result = preflight.check_docker()

        self.assertFalse(result.ok)
        self.assertIn("Windows binary", result.detail)
        self.assertIn("WSL Integration", result.remedy)

    def test_windows_binary_rejected_without_invoking_it(self):
        """Rejection must be by path, before any subprocess call."""
        win = "/mnt/c/Program Files/Docker/Docker/resources/bin/docker"
        with (
            mock.patch("shutil.which", return_value=win),
            mock.patch("subprocess.run") as run,
        ):
            preflight.check_docker()
        run.assert_not_called()

    def test_daemon_unreachable_fails(self):
        with (
            mock.patch("shutil.which", return_value="/usr/bin/docker"),
            mock.patch(
                "subprocess.run",
                return_value=_completed(1, stderr="Cannot connect to the daemon"),
            ),
        ):
            result = preflight.check_docker()
        self.assertFalse(result.ok)
        self.assertIn("Cannot connect", result.detail)

    def test_empty_bind_mount_fails_even_though_container_ran(self):
        """A container that starts but sees no files is worse than one that fails."""
        with (
            mock.patch("shutil.which", return_value="/usr/bin/docker"),
            mock.patch(
                "subprocess.run",
                side_effect=[_completed(0), _completed(0, stdout="")],
            ),
        ):
            result = preflight.check_docker()

        self.assertFalse(result.ok)
        self.assertIn("bind mount was empty", result.detail)

    def test_working_docker_passes(self):
        with (
            mock.patch("shutil.which", return_value="/usr/bin/docker"),
            mock.patch(
                "subprocess.run",
                side_effect=[_completed(0), _completed(0, stdout="ok\n")],
            ),
        ):
            result = preflight.check_docker()
        self.assertTrue(result.ok)

    def test_timeout_is_reported_not_raised(self):
        with (
            mock.patch("shutil.which", return_value="/usr/bin/docker"),
            mock.patch(
                "subprocess.run", side_effect=subprocess.TimeoutExpired("docker", 5)
            ),
        ):
            result = preflight.check_docker()
        self.assertFalse(result.ok)


class ApiKeyCheckTest(unittest.TestCase):
    def test_missing_key_fails(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            result = preflight.check_api_key("SOME_KEY")
        self.assertFalse(result.ok)

    def test_present_key_passes(self):
        with mock.patch.dict("os.environ", {"SOME_KEY": "abcdef"}):
            result = preflight.check_api_key("SOME_KEY")
        self.assertTrue(result.ok)

    def test_key_value_is_never_revealed(self):
        secret = "sk-or-v1-supersecretvalue"
        with mock.patch.dict("os.environ", {"SOME_KEY": secret}):
            result = preflight.check_api_key("SOME_KEY")
        rendered = result.render() + result.detail
        self.assertNotIn(secret, rendered)
        self.assertIn(str(len(secret)), result.detail)


class AssertReadyTest(unittest.TestCase):
    def test_raises_when_a_check_fails(self):
        failing = preflight.CheckResult("docker", False, "broken", "fix it")
        with mock.patch.object(preflight, "run_all", return_value=[failing]):
            with self.assertRaises(RuntimeError) as ctx:
                preflight.assert_ready()
        self.assertIn("docker", str(ctx.exception))

    def test_passes_when_all_checks_pass(self):
        ok = preflight.CheckResult("docker", True, "fine")
        with mock.patch.object(preflight, "run_all", return_value=[ok]):
            preflight.assert_ready()  # must not raise

    def test_docker_can_be_skipped(self):
        with mock.patch.object(preflight, "check_docker") as check:
            preflight.run_all(require_docker=False)
        check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
