"""Offline tests for the security-critical pure logic of docker_sandbox.

Covers network-posture parsing, the semantic-version / preset-resolution engine,
and lifecycle action validation.  These are the core policy-decision functions of
the framework; everything runs without touching a Docker daemon.
"""
import os
import sys
import unittest
from unittest import mock

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from docker_sandbox.client import Sandbox
from docker_sandbox.config import SandboxConfig
from docker_sandbox.lifecycle import (
    normalize_lifecycle,
    validate_action_step,
    validate_agent_lifecycle,
    validate_all_settings,
)


class ParseNetworkSettingsTests(unittest.TestCase):
    """Network-posture parsing: ON / PROXY / LOCAL / legacy, and crash regressions."""

    def setUp(self):
        self.sandbox = Sandbox()

    def test_legacy_bare_boolean_network_does_not_crash(self):
        # Legacy configs may express network as a bare boolean. That previously
        # raised AttributeError ('bool' object has no attribute 'get').
        allow_host, allow_external, allow_containers, ports = (
            self.sandbox.parse_network_settings({"name": "x", "network": True})
        )
        self.assertIsInstance(allow_host, bool)
        self.assertEqual(allow_containers, ["*"])

    def test_legacy_empty_list_network_does_not_crash(self):
        allow_host, allow_external, allow_containers, ports = (
            self.sandbox.parse_network_settings({"name": "x", "network": []})
        )
        self.assertIsInstance(allow_host, bool)
        self.assertEqual(ports, [])

    def test_full_access_posture(self):
        agent = {
            "name": "a",
            "network": {
                "host_access": {"enabled": True, "allowed_ports": [3000]},
                "external_access": ["*"],
                "container_access": ["*"],
            },
        }
        allow_host, allow_external, allow_containers, ports = (
            self.sandbox.parse_network_settings(agent)
        )
        self.assertTrue(allow_host)
        self.assertEqual(allow_external, ["*"])
        self.assertEqual(allow_containers, ["*"])
        self.assertEqual(ports, ["3000:3000"])

    def test_loopback_scope_binds_to_host(self):
        agent = {
            "name": "a",
            "network": {
                "host_access": {
                    "enabled": True,
                    "allowed_ports": ["18080:8080"],
                    "published_port_scope": "loopback",
                },
                "external_access": ["*"],
                "container_access": ["*"],
            },
        }
        _, _, _, ports = self.sandbox.parse_network_settings(agent)
        self.assertEqual(ports, ["127.0.0.1:18080:8080"])

    def test_public_scope_binds_without_host(self):
        agent = {
            "name": "a",
            "network": {
                "host_access": {
                    "enabled": True,
                    "allowed_ports": ["18080:8080"],
                    "published_port_scope": "public",
                },
            },
        }
        _, _, _, ports = self.sandbox.parse_network_settings(agent)
        self.assertEqual(ports, ["18080:8080"])

    def test_legacy_deny_private_lan_maps_to_loopback(self):
        agent = {
            "name": "a",
            "network": {
                "host_access": {
                    "enabled": True,
                    "allowed_ports": [5000],
                    "deny_private_lan": True,
                },
            },
        }
        _, _, _, ports = self.sandbox.parse_network_settings(agent)
        self.assertEqual(ports, ["127.0.0.1:5000:5000"])

    def test_no_network_key_defaults_to_open(self):
        allow_host, allow_external, allow_containers, ports = (
            self.sandbox.parse_network_settings({"name": "a"})
        )
        self.assertTrue(allow_host)
        self.assertEqual(allow_external, ["*"])
        self.assertEqual(ports, [])


class VersionEngineTests(unittest.TestCase):
    """Semantic version parsing, comparison, and specifier matching."""

    def test_parse_version_strips_v_prefix(self):
        self.assertEqual(Sandbox.parse_version("v1.2.3"), [1, 2, 3])

    def test_parse_version_handles_non_numeric(self):
        # e.g. pre-release suffixes -> kept as tokens for mixed comparison
        parsed = Sandbox.parse_version("1.2.0-rc1")
        self.assertEqual(parsed[0], 1)
        self.assertEqual(parsed[1], 2)

    def test_compare_versions_ordering(self):
        self.assertLess(Sandbox.compare_versions("1.0.0", "2.0.0"), 0)
        self.assertGreater(Sandbox.compare_versions("2.0.0", "1.9.0"), 0)
        self.assertEqual(Sandbox.compare_versions("1.2.3", "1.2.3"), 0)
        # shorter version is "less" when prefix matches
        self.assertLess(Sandbox.compare_versions("1.2", "1.2.1"), 0)

    def test_match_specifier_any(self):
        self.assertTrue(Sandbox.match_version("1.0.0", "*"))
        self.assertTrue(Sandbox.match_version("1.0.0", "default"))
        self.assertTrue(Sandbox.match_version("1.0.0", ""))

    def test_match_exact_and_range(self):
        self.assertTrue(Sandbox.match_version("2.5.0", "==2.5.0"))
        self.assertFalse(Sandbox.match_version("2.5.1", "==2.5.0"))
        self.assertTrue(Sandbox.match_version("2.6.0", ">=2.5.0"))
        self.assertFalse(Sandbox.match_version("2.4.0", ">=2.5.0"))
        self.assertTrue(Sandbox.match_version("2.4.9", "<2.5.0"))
        self.assertTrue(Sandbox.match_version("2.5.1", "~=2.5.0"))

    def test_match_compatible_release_bounds(self):
        # ~=2.5 means >=2.5, compatible within major.minor
        self.assertTrue(Sandbox.match_version("2.5.9", "~=2.5"))
        self.assertTrue(Sandbox.match_version("2.5.0", "~=2.5"))
        self.assertFalse(Sandbox.match_version("2.6.0", "~=2.5"))
        self.assertFalse(Sandbox.match_version("3.0.0", "~=2.5"))

    def test_match_validates_unsupported_op_is_exact(self):
        # no operator prefix -> treated as exact
        self.assertTrue(Sandbox.match_version("1.2.3", "1.2.3"))
        self.assertFalse(Sandbox.match_version("1.2.4", "1.2.3"))


class ResolveRequirementsTests(unittest.TestCase):
    def setUp(self):
        self.config = SandboxConfig(root_dir=REPO_ROOT)

    def test_resolve_selects_default_version(self):
        sandbox = Sandbox(self.config)
        with mock.patch.object(
            self.config,
            "load_presets",
            return_value={
                "nodejs": {
                    "versions": {"18.0.0": {"command": "npm-install"}, "20.0.0": {"command": "npm20"}},
                    "default_version": "18.0.0",
                }
            },
        ):
            cmds, env = sandbox.resolve_requirements(["nodejs"])
        self.assertIn("npm-install", cmds)

    def test_resolve_selects_highest_matching(self):
        sandbox = Sandbox(self.config)
        with mock.patch.object(
            self.config,
            "load_presets",
            return_value={
                "nodejs": {
                    "versions": {"18.0.0": {"command": "a", "env": {"V": "18"}}, "20.0.0": {"command": "b", "env": {"V": "20"}}},
                    "default_version": "18.0.0",
                }
            },
        ):
            cmds, env = sandbox.resolve_requirements(["nodejs >=19"])
        self.assertEqual(cmds, ["b"])
        self.assertEqual(env, {"V": "20"})

    def test_resolve_unknown_preset_skipped(self):
        sandbox = Sandbox(self.config)
        with mock.patch.object(self.config, "load_presets", return_value={}):
            cmds, env = sandbox.resolve_requirements(["does-not-exist"])
        self.assertEqual(cmds, [])
        self.assertEqual(env, {})


class LifecycleValidationTests(unittest.TestCase):
    def setUp(self):
        self.config = SandboxConfig(root_dir=REPO_ROOT)
        self.registry = self.config.load_registry()

    def test_normalize_lifecycle_legacy_pre_start(self):
        agent = {"pre_start": ["mkdir -p /tmp/work", "touch /tmp/flag"]}
        lifecycle = normalize_lifecycle(agent)
        self.assertEqual(lifecycle["host_prepare"][0]["@action"], "ensure_dir")
        self.assertEqual(lifecycle["host_prepare"][1]["@action"], "require_file")

    def test_action_step_rejects_function_dispatch(self):
        errors = []
        validate_action_step("host_prepare", {"@function": "x"}, 0, self.registry, self.config.scripts_dir, errors)
        self.assertTrue(any("@function" in e for e in errors))

    def test_action_step_requires_action(self):
        errors = []
        validate_action_step("host_prepare", {"path": "/tmp/x"}, 0, self.registry, self.config.scripts_dir, errors)
        self.assertTrue(any("missing @action" in e for e in errors))

    def test_action_step_unknown_action(self):
        errors = []
        validate_action_step("host_prepare", {"@action": "nope"}, 0, self.registry, self.config.scripts_dir, errors)
        self.assertTrue(any("unknown action" in e for e in errors))

    def test_action_step_phase_mismatch(self):
        errors = []
        validate_action_step("image_prepare", {"@action": "ensure_dir", "path": "/tmp/x"}, 0, self.registry, self.config.scripts_dir, errors)
        self.assertTrue(any("not allowed in phase" in e for e in errors))

    def test_action_step_missing_required_arg(self):
        errors = []
        validate_action_step("host_prepare", {"@action": "ensure_dir"}, 0, self.registry, self.config.scripts_dir, errors)
        self.assertTrue(any("missing required argument" in e for e in errors))

    def test_action_step_relative_path_rejected(self):
        errors = []
        validate_action_step("host_prepare", {"@action": "ensure_dir", "path": "relative/path"}, 0, self.registry, self.config.scripts_dir, errors)
        self.assertTrue(any("must be absolute" in e for e in errors))

    def test_valid_agent_lifecycle_has_no_errors(self):
        agent = {
            "name": "ok",
            "lifecycle": {
                "host_prepare": [{"@action": "ensure_dir", "path": "/tmp/ok"}],
                "container_startup": {"behavior": "NEVER", "steps": []},
            },
        }
        errors = validate_agent_lifecycle(agent, registry=self.registry, scripts_dir=self.config.scripts_dir)
        self.assertEqual(errors, [])

    def test_validate_all_settings_surfaces_errors_by_name(self):
        settings = {
            "containers": [
                {"name": "bad", "lifecycle": {"host_prepare": [{"@action": "doesnotexist"}]}},
                {"name": "good", "lifecycle": {"host_prepare": []}},
            ]
        }
        all_errors = validate_all_settings(settings, registry=self.registry, scripts_dir=self.config.scripts_dir)
        self.assertIn("bad", all_errors)
        self.assertNotIn("good", all_errors)


class AppendSecurityOptionsTests(unittest.TestCase):
    def test_appends_run_as_user_and_cap_drop(self):
        cmd = ["docker", "run"]
        Sandbox.append_runtime_security_options(cmd, {"run_as_user": "1001:1001", "cap_drop": "ALL"})
        self.assertIn("--user", cmd)
        self.assertIn("1001:1001", cmd)
        self.assertIn("--cap-drop", cmd)

    def test_string_cap_drop_normalized_to_list(self):
        cmd = []
        Sandbox.append_runtime_security_options(cmd, {"cap_drop": "NET_ADMIN"})
        self.assertEqual(cmd.count("--cap-drop"), 1)

    def test_no_new_privileges(self):
        cmd = []
        Sandbox.append_runtime_security_options(cmd, {"no_new_privileges": True})
        self.assertIn("--security-opt", cmd)


if __name__ == "__main__":
    unittest.main()