#!/usr/bin/env python3
"""Unit tests for docker_sandbox SDK framework and client."""
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from docker_sandbox import (
    ConfigError,
    ConfiguredCommandError,
    Sandbox,
    SandboxConfig,
    StatusReport,
    TargetNotFoundError,
    validate_agent_lifecycle,
)


class SandboxSDKTests(unittest.TestCase):
    def setUp(self):
        self.config = SandboxConfig(
            root_dir=REPO_ROOT,
            config_dir=os.path.join(REPO_ROOT, "config"),
        )
        self.sandbox = Sandbox(self.config)

    def test_status_returns_structured_report(self):
        report = self.sandbox.status()
        self.assertIsInstance(report, StatusReport)
        if report.docker_available:
            self.assertIsNone(report.docker_error)
            self.assertIsInstance(report.groups, dict)

    def test_explain_validates_known_container(self):
        results = self.sandbox.explain("bias-graph-feed")
        self.assertIn("bias-graph-feed", results)
        res = results["bias-graph-feed"]
        self.assertTrue(res.is_valid)
        self.assertEqual(res.container_name, "bias-graph-feed")
        self.assertIn("host_prepare", res.phases)

    def test_explain_invalid_container(self):
        results = self.sandbox.explain("nonexistent-container-xyz")
        self.assertIn("nonexistent-container-xyz", results)
        res = results["nonexistent-container-xyz"]
        self.assertFalse(res.is_valid)
        self.assertTrue(any("not defined" in err for err in res.errors))

    def test_in_cmd_resolves_programmatic_invocation(self):
        fake_agent = {
            "name": "test-agent",
            "commands": {
                "run": {
                    "default": {"function": "exec_cmd", "args": ["--silent"], "allow_user_args": True},
                    "functions": {
                        "exec_cmd": {
                            "argv": ["python3", "-m", "worker"],
                            "args": ["--flag"],
                            "allow_args": True,
                        }
                    },
                }
            },
        }

        with mock.patch.object(self.sandbox.config, "load_settings", return_value=({"containers": [fake_agent]}, False)):
            inv = self.sandbox.in_cmd("test-agent", "run", ".", ["extra_arg"])
            self.assertEqual(inv.container_name, "test-agent")
            self.assertEqual(inv.command_type, "run")
            self.assertEqual(inv.target_name, "exec_cmd")
            self.assertEqual(
                inv.argv,
                ["python3", "-m", "worker", "--flag", "--silent", "extra_arg"],
            )

    def test_in_cmd_raises_target_not_found(self):
        with self.assertRaises(TargetNotFoundError):
            self.sandbox.in_cmd("unknown-agent-123", "run", ".")

    def test_in_cmd_raises_configured_command_error_on_disallowed_args(self):
        fake_agent = {
            "name": "strict-agent",
            "commands": {
                "run": {
                    "default": {"function": "fixed_cmd", "allow_user_args": False},
                    "functions": {
                        "fixed_cmd": {
                            "argv": ["ls"],
                            "allow_args": False,
                        }
                    },
                }
            },
        }

        with mock.patch.object(self.sandbox.config, "load_settings", return_value=({"containers": [fake_agent]}, False)):
            with self.assertRaises(ConfiguredCommandError):
                self.sandbox.in_cmd("strict-agent", "run", ".", ["illegal_arg"])

    def test_target_resolution_wildcard(self):
        settings = {"containers": [{"name": "c1"}, {"name": "c2"}]}
        targets, is_bulk = self.sandbox.config.resolve_targets("*", settings)
        self.assertEqual(targets, ["c1", "c2"])
        self.assertTrue(is_bulk)

    def test_config_directory_selects_its_parent_as_root(self):
        config = SandboxConfig(config_dir=os.path.join(REPO_ROOT, "config"))
        self.assertEqual(config.root_dir, REPO_ROOT)
        self.assertEqual(config.config_dir, os.path.join(REPO_ROOT, "config"))

    def test_docker_context_is_scoped_to_child_processes(self):
        before = os.environ.get("DOCKER_CONTEXT")
        config = SandboxConfig(root_dir=REPO_ROOT, docker_context="sdk-test-context")
        self.assertEqual(config.docker_environment()["DOCKER_CONTEXT"], "sdk-test-context")
        self.assertEqual(os.environ.get("DOCKER_CONTEXT"), before)

    def test_compose_environment_carries_the_selected_docker_context(self):
        config = SandboxConfig(root_dir=REPO_ROOT, docker_context="sdk-test-context")
        env = config.get_compose_environment({"name": "example", "environment": {"EXAMPLE": "1"}})
        self.assertEqual(env["DOCKER_CONTEXT"], "sdk-test-context")
        self.assertEqual(env["EXAMPLE"], "1")


if __name__ == "__main__":
    unittest.main()
