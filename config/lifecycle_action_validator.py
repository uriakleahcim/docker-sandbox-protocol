"""Backward compatibility adapter for lifecycle action validator.
Delegates to the docker_sandbox package.
"""
import os
import sys

# Ensure src/ is on sys.path
REAL_DIR = os.path.dirname(os.path.realpath(__file__))
ROOT_DIR = os.environ.get("SANDBOX_ROOT", os.path.dirname(REAL_DIR) if os.path.basename(REAL_DIR) == "config" else REAL_DIR)
SRC_DIR = os.path.join(ROOT_DIR, "src")
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)

from docker_sandbox.config import SandboxConfig
from docker_sandbox.lifecycle import (
    normalize_lifecycle,
    validate_action_step,
    validate_agent_lifecycle as _validate_agent_lifecycle,
    validate_all_settings as _validate_all_settings,
)

CONFIG_DIR = os.environ.get("SANDBOX_CONFIG_DIR", REAL_DIR)
REGISTRY_PATH = os.environ.get("SANDBOX_REGISTRY_PATH", os.path.join(CONFIG_DIR, "lifecycle_action_registry.json"))
SCRIPTS_DIR = os.environ.get("SANDBOX_SCRIPTS_DIR", os.path.join(ROOT_DIR, "scripts"))


def load_registry():
    cfg = SandboxConfig(root_dir=ROOT_DIR, config_dir=CONFIG_DIR, registry_file=REGISTRY_PATH)
    return cfg.load_registry()


def validate_agent_lifecycle(agent_config):
    cfg = SandboxConfig(root_dir=ROOT_DIR, config_dir=CONFIG_DIR, registry_file=REGISTRY_PATH, scripts_dir=SCRIPTS_DIR)
    return _validate_agent_lifecycle(agent_config, config=cfg)


def validate_all_settings(settings_data):
    cfg = SandboxConfig(root_dir=ROOT_DIR, config_dir=CONFIG_DIR, registry_file=REGISTRY_PATH, scripts_dir=SCRIPTS_DIR)
    return _validate_all_settings(settings_data, config=cfg)
