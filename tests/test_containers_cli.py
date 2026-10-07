#!/usr/bin/env python3
import os
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.path.join(REPO_ROOT, "config")
if CONFIG_DIR not in sys.path:
    sys.path.insert(0, CONFIG_DIR)

import containers_cli


class RuntimeSecurityOptionsTests(unittest.TestCase):
    def test_appends_non_root_hardening_options(self):
        cmd = ["docker", "run"]

        containers_cli.append_runtime_security_options(
            cmd,
            {
                "run_as_user": "977:977",
                "cap_drop": ["ALL"],
                "no_new_privileges": True,
            },
        )

        self.assertEqual(
            cmd,
            [
                "docker",
                "run",
                "--user",
                "977:977",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges=true",
            ],
        )

    def test_ignores_unset_hardening_options(self):
        cmd = ["docker", "run"]

        containers_cli.append_runtime_security_options(cmd, {})

        self.assertEqual(cmd, ["docker", "run"])


class ConfiguredContainerCommandTests(unittest.TestCase):
    def setUp(self):
        self.agent = {
            "name": "searxng",
            "commands": {
                "open": {
                    "default": {
                        "target": "home",
                        "args": [],
                        "allow_user_args": False,
                    },
                    "targets": {
                        "home": {
                            "type": "url",
                            "value": "http://127.0.0.1:18080",
                            "requires_running": True,
                            "allow_args": False,
                        }
                    },
                },
                "run": {
                    "default": {
                        "function": "http_get",
                        "args": ["http://127.0.0.1:8080/config"],
                        "allow_user_args": False,
                    },
                    "functions": {
                        "http_get": {
                            "argv": ["python3", "-c", "print('ok')"],
                            "args": ["--fixed"],
                            "allow_args": True,
                        }
                    },
                },
            },
        }

    def test_default_adds_configured_args(self):
        name, entry, args = containers_cli.resolve_configured_invocation(
            self.agent, "run", ".", []
        )

        self.assertEqual(name, "http_get")
        self.assertIs(entry, self.agent["commands"]["run"]["functions"]["http_get"])
        self.assertEqual(
            args,
            ["--fixed", "http://127.0.0.1:8080/config"],
        )

    def test_default_rejects_caller_args(self):
        with self.assertRaisesRegex(
            containers_cli.ConfiguredCommandError,
            "does not allow caller-supplied arguments",
        ):
            containers_cli.resolve_configured_invocation(
                self.agent, "run", ".", ["unexpected"]
            )

    def test_named_function_can_accept_caller_args(self):
        _, _, args = containers_cli.resolve_configured_invocation(
            self.agent, "run", "http_get", ["https://example.com"]
        )

        self.assertEqual(args, ["--fixed", "https://example.com"])

    @mock.patch.object(containers_cli, "get_docker_unavailable_reason")
    @mock.patch.object(containers_cli, "load_settings")
    def test_container_only_request_prints_command_catalog(
        self,
        load_settings,
        docker_reason,
    ):
        load_settings.return_value = {"containers": [self.agent]}
        output = StringIO()

        with redirect_stdout(output):
            result = containers_cli.do_in(["c", "searxng"])

        self.assertEqual(result, 0)
        self.assertIn("CONFIGURED COMMANDS: searxng", output.getvalue())
        self.assertIn("OPEN selectors", output.getvalue())
        self.assertIn("default → home", output.getvalue())
        self.assertIn("RUN selectors", output.getvalue())
        self.assertIn("default → http_get", output.getvalue())
        self.assertIn("http_get", output.getvalue())
        docker_reason.assert_not_called()

    @mock.patch.object(containers_cli.subprocess, "run")
    @mock.patch.object(containers_cli, "is_container_running", return_value=True)
    @mock.patch.object(containers_cli, "get_docker_unavailable_reason", return_value=None)
    @mock.patch.object(containers_cli, "resolve_container_name", return_value="searxng")
    @mock.patch.object(containers_cli, "load_settings")
    def test_run_executes_direct_argv(
        self,
        load_settings,
        _resolve_container_name,
        _docker_reason,
        _is_running,
        subprocess_run,
    ):
        load_settings.return_value = {"containers": [self.agent]}
        subprocess_run.return_value.returncode = 0

        result = containers_cli.do_in(["c", "searxng", "run", "."])

        self.assertEqual(result, 0)
        subprocess_run.assert_called_once_with(
            [
                "docker",
                "exec",
                "searxng",
                "python3",
                "-c",
                "print('ok')",
                "--fixed",
                "http://127.0.0.1:8080/config",
            ]
        )

    @mock.patch.object(containers_cli.subprocess, "Popen")
    @mock.patch.object(containers_cli.shutil, "which", return_value="/usr/bin/xdg-open")
    @mock.patch.object(containers_cli, "is_container_running", return_value=True)
    @mock.patch.object(containers_cli, "get_docker_unavailable_reason", return_value=None)
    @mock.patch.object(containers_cli, "resolve_container_name", return_value="searxng")
    @mock.patch.object(containers_cli, "load_settings")
    def test_open_default_uses_configured_host_url(
        self,
        load_settings,
        _resolve_container_name,
        _docker_reason,
        _is_running,
        _which,
        popen,
    ):
        load_settings.return_value = {"containers": [self.agent]}

        result = containers_cli.do_in(["c", "searxng", "open", "."])

        self.assertEqual(result, 0)
        popen.assert_called_once_with(
            ["/usr/bin/xdg-open", "http://127.0.0.1:18080"],
            stdout=containers_cli.subprocess.DEVNULL,
            stderr=containers_cli.subprocess.DEVNULL,
            start_new_session=True,
        )


if __name__ == "__main__":
    unittest.main()
