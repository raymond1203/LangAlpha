"""
Tests for SandboxConfig, DockerConfig, and backward-compat config loading.

Covers:
- SandboxConfig defaults
- DockerConfig defaults
- CoreConfig.daytona property shim
- AgentConfig.daytona property shim
- validate_api_keys() conditional on provider
- create_sandbox_config() with "sandbox" and "daytona" YAML keys
- SANDBOX_PROVIDER env var override
"""

import os
from unittest.mock import patch

import pytest

from ptc_agent.config.core import (
    CoreConfig,
    DaytonaConfig,
    DockerConfig,
    FilesystemConfig,
    LoggingConfig,
    MCPConfig,
    SandboxConfig,
    SecurityConfig,
)
from ptc_agent.config.utils import create_sandbox_config


# ---------------------------------------------------------------------------
# SandboxConfig / DockerConfig defaults
# ---------------------------------------------------------------------------


class TestSandboxConfigDefaults:
    def test_default_provider_is_daytona(self):
        cfg = SandboxConfig()
        assert cfg.provider == "daytona"

    def test_default_daytona_config(self):
        cfg = SandboxConfig()
        assert isinstance(cfg.daytona, DaytonaConfig)
        assert cfg.daytona.api_key == ""

    def test_default_docker_config(self):
        cfg = SandboxConfig()
        assert isinstance(cfg.docker, DockerConfig)


class TestDockerConfigDefaults:
    def test_defaults(self):
        cfg = DockerConfig()
        assert cfg.image == "langalpha-sandbox:latest"
        assert cfg.working_dir == "/home/daytona"
        assert cfg.memory_limit == "4g"
        assert cfg.cpu_count == 2.0
        assert cfg.dev_mode is False

    def test_custom(self):
        cfg = DockerConfig(image="custom:latest", memory_limit="8g", dev_mode=True)
        assert cfg.image == "custom:latest"
        assert cfg.memory_limit == "8g"
        assert cfg.dev_mode is True


# ---------------------------------------------------------------------------
# CoreConfig.daytona property shim
# ---------------------------------------------------------------------------


class TestCoreConfigDaytonaShim:
    def _make_core(self, **overrides) -> CoreConfig:
        defaults = dict(
            sandbox=SandboxConfig(daytona=DaytonaConfig(api_key="shim-test")),
            security=SecurityConfig(),
            mcp=MCPConfig(),
            logging=LoggingConfig(),
            filesystem=FilesystemConfig(),
        )
        defaults.update(overrides)
        return CoreConfig(**defaults)

    def test_daytona_returns_sandbox_daytona(self):
        cfg = self._make_core()
        assert cfg.daytona is cfg.sandbox.daytona
        assert cfg.daytona.api_key == "shim-test"

    def test_validate_api_keys_skips_for_docker(self):
        cfg = self._make_core(
            sandbox=SandboxConfig(provider="docker", daytona=DaytonaConfig(api_key=""))
        )
        cfg.validate_api_keys()  # Should not raise

    def test_validate_api_keys_requires_for_daytona(self):
        cfg = self._make_core(
            sandbox=SandboxConfig(provider="daytona", daytona=DaytonaConfig(api_key=""))
        )
        with pytest.raises(ValueError, match="DAYTONA_API_KEY"):
            cfg.validate_api_keys()


# ---------------------------------------------------------------------------
# create_sandbox_config — new "sandbox:" key
# ---------------------------------------------------------------------------


class TestCreateSandboxConfigNewFormat:
    def test_reads_sandbox_key(self):
        config_data = {
            "sandbox": {
                "provider": "daytona",
                "daytona": {
                    "base_url": "https://app.daytona.io/api",
                    "auto_stop_interval": 3600,
                    "auto_archive_interval": 86400,
                    "auto_delete_interval": 604800,
                    "python_version": "3.12",
                },
            }
        }
        cfg = create_sandbox_config(config_data)
        assert cfg.provider == "daytona"
        assert cfg.daytona.base_url == "https://app.daytona.io/api"

    def test_reads_docker_provider(self):
        config_data = {
            "sandbox": {
                "provider": "docker",
                "docker": {
                    "image": "my-image:latest",
                    "memory_limit": "8g",
                },
            }
        }
        cfg = create_sandbox_config(config_data)
        assert cfg.provider == "docker"
        assert cfg.docker.image == "my-image:latest"
        assert cfg.docker.memory_limit == "8g"

    def test_sandbox_key_defaults_to_daytona_provider(self):
        config_data = {
            "sandbox": {
                "daytona": {
                    "base_url": "https://test.io/api",
                    "auto_stop_interval": 3600,
                    "auto_archive_interval": 86400,
                    "auto_delete_interval": 604800,
                    "python_version": "3.12",
                },
            }
        }
        cfg = create_sandbox_config(config_data)
        assert cfg.provider == "daytona"


# ---------------------------------------------------------------------------
# create_sandbox_config — backward compat "daytona:" key
# ---------------------------------------------------------------------------


class TestCreateSandboxConfigBackwardCompat:
    def test_reads_daytona_key(self):
        """Top-level 'daytona:' key should produce SandboxConfig with provider='daytona'."""
        config_data = {
            "daytona": {
                "base_url": "https://app.daytona.io/api",
                "auto_stop_interval": 3600,
                "auto_archive_interval": 86400,
                "auto_delete_interval": 604800,
                "python_version": "3.12",
            }
        }
        cfg = create_sandbox_config(config_data)
        assert isinstance(cfg, SandboxConfig)
        assert cfg.provider == "daytona"
        assert cfg.daytona.base_url == "https://app.daytona.io/api"

    def test_missing_both_keys_raises(self):
        with pytest.raises(ValueError, match="sandbox.*daytona"):
            create_sandbox_config({})


# ---------------------------------------------------------------------------
# SANDBOX_PROVIDER env var override
# ---------------------------------------------------------------------------


class TestSandboxProviderEnvOverride:
    def test_env_overrides_provider(self):
        config_data = {
            "daytona": {
                "base_url": "https://app.daytona.io/api",
                "auto_stop_interval": 3600,
                "auto_archive_interval": 86400,
                "auto_delete_interval": 604800,
                "python_version": "3.12",
            }
        }
        with patch.dict(os.environ, {"SANDBOX_PROVIDER": "docker"}):
            cfg = create_sandbox_config(config_data)
        assert cfg.provider == "docker"

    def test_env_not_set_uses_config(self):
        config_data = {
            "sandbox": {
                "provider": "docker",
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("SANDBOX_PROVIDER", None)
            cfg = create_sandbox_config(config_data)
        assert cfg.provider == "docker"
