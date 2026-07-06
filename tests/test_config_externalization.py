"""Tests for externalized configuration loading (YAML).

Verifies that:
- Default loading (no env var) returns the built-in demo config.
- YAML loading with a valid file overrides defaults correctly.
- Malformed or missing YAML files fall back to defaults safely.
- Permission config produces correct PermissionContext objects.
- Users config produces correct user dicts with bcrypt-hashed passwords.
- The shipped deploy/config/*.yaml files are valid and load correctly.
"""
from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_CONFIG_DIR = _PROJECT_ROOT / "deploy" / "config"


# ---------------------------------------------------------------------------
# Permissions YAML loader
# ---------------------------------------------------------------------------


class TestPermissionsYamlLoader:
    """Verify permission_service.config.load_permission_config()."""

    def test_defaults_returned_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HONEYBADGE_PERMISSIONS_CONFIG", raising=False)
        from honeybadge.permission_service import config as cfg

        config = cfg.load_permission_config()
        assert "admin" in config
        assert "analyst" in config
        assert config["admin"].data_scope == "ALL"
        assert config["analyst"].org_ids == [1000]
        assert config["subsidiary_lead"].org_ids == [1021]

    def test_load_from_valid_yaml(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        yaml_content = """
permissions:
  custom_user:
    user_id: custom_user
    allowed_processes: [PTP]
    org_ids: [9999]
    dept_ids: null
    data_scope: ORG
"""
        yaml_file = tmp_path / "perms.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        monkeypatch.setenv("HONEYBADGE_PERMISSIONS_CONFIG", str(yaml_file))

        from honeybadge.permission_service import config as cfg

        result = cfg.load_permission_config()
        assert "custom_user" in result
        assert result["custom_user"].user_id == "custom_user"
        assert result["custom_user"].allowed_processes == ["PTP"]
        assert result["custom_user"].org_ids == [9999]
        assert result["custom_user"].data_scope == "ORG"

    def test_malformed_yaml_falls_back_to_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_file = tmp_path / "bad_perms.yaml"
        yaml_file.write_text("not_a_mapping: just_a_string", encoding="utf-8")
        monkeypatch.setenv("HONEYBADGE_PERMISSIONS_CONFIG", str(yaml_file))

        from honeybadge.permission_service import config as cfg

        result = cfg.load_permission_config()
        # Falls back to defaults
        assert "admin" in result
        assert "custom_user" not in result

    def test_missing_file_falls_back_to_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HONEYBADGE_PERMISSIONS_CONFIG", "/nonexistent/path/perms.yaml")

        from honeybadge.permission_service import config as cfg

        result = cfg.load_permission_config()
        assert "admin" in result
        assert "auditor" in result

    def test_shipped_permissions_yaml_is_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The deploy/config/permissions.yaml file must load without error."""
        yaml_path = _CONFIG_DIR / "permissions.yaml"
        if not yaml_path.exists():
            pytest.skip("deploy/config/permissions.yaml not present")
        monkeypatch.setenv("HONEYBADGE_PERMISSIONS_CONFIG", str(yaml_path))

        from honeybadge.permission_service import config as cfg

        result = cfg.load_permission_config()
        assert "admin" in result
        assert "analyst" in result
        assert "auditor" in result
        assert result["admin"].allowed_processes == ["PTP", "OTC"]
        assert result["subsidiary_lead"].org_ids == [1021]
        assert result["analyst"].data_scope == "ORG"

    def test_user_id_defaults_to_key_if_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_content = """
permissions:
  bob:
    allowed_processes: [PTP]
    org_ids: null
    dept_ids: null
    data_scope: ALL
"""
        yaml_file = tmp_path / "perms.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        monkeypatch.setenv("HONEYBADGE_PERMISSIONS_CONFIG", str(yaml_file))

        from honeybadge.permission_service import config as cfg

        result = cfg.load_permission_config()
        assert "bob" in result
        assert result["bob"].user_id == "bob"


# ---------------------------------------------------------------------------
# Users YAML loader
# ---------------------------------------------------------------------------


class TestUsersYamlLoader:
    """Verify server.auth.load_demo_users()."""

    def test_defaults_returned_when_env_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("HONEYBADGE_USERS_CONFIG", raising=False)
        from honeybadge.server import auth

        users = auth.load_demo_users()
        assert "admin" in users
        assert "analyst" in users
        assert "password_hash" in users["admin"]
        assert "password" not in users["admin"]  # plaintext not retained
        assert users["admin"]["roles"] == ["admin"]
        assert users["admin"]["org_id"] == 1000

    def test_load_from_valid_yaml(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        yaml_content = """
users:
  customuser:
    id: customuser
    username: customuser
    password: secretpass
    display_name: Custom User
    roles: [analyst]
    org_id: 5555
"""
        yaml_file = tmp_path / "users.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        monkeypatch.setenv("HONEYBADGE_USERS_CONFIG", str(yaml_file))

        from honeybadge.server import auth

        users = auth.load_demo_users()
        assert "customuser" in users
        assert users["customuser"]["username"] == "customuser"
        assert users["customuser"]["display_name"] == "Custom User"
        assert users["customuser"]["roles"] == ["analyst"]
        assert users["customuser"]["org_id"] == 5555
        # Password should be hashed (not plaintext)
        assert users["customuser"]["password_hash"] != "secretpass"
        assert "password" not in users["customuser"]
        # And the hash should verify against the plaintext
        assert auth.pwd_context.verify("secretpass", users["customuser"]["password_hash"])

    def test_malformed_yaml_falls_back_to_defaults(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_file = tmp_path / "bad_users.yaml"
        yaml_file.write_text("just_a_string_not_a_mapping", encoding="utf-8")
        monkeypatch.setenv("HONEYBADGE_USERS_CONFIG", str(yaml_file))

        from honeybadge.server import auth

        users = auth.load_demo_users()
        # Falls back to defaults
        assert "admin" in users
        assert "customuser" not in users

    def test_missing_file_falls_back_to_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HONEYBADGE_USERS_CONFIG", "/nonexistent/path/users.yaml")

        from honeybadge.server import auth

        users = auth.load_demo_users()
        assert "admin" in users
        assert "auditor" in users

    def test_shipped_users_yaml_is_valid(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The deploy/config/users.yaml file must load and hash passwords."""
        yaml_path = _CONFIG_DIR / "users.yaml"
        if not yaml_path.exists():
            pytest.skip("deploy/config/users.yaml not present")
        monkeypatch.setenv("HONEYBADGE_USERS_CONFIG", str(yaml_path))

        from honeybadge.server import auth

        users = auth.load_demo_users()
        assert "admin" in users
        assert "analyst" in users
        assert "auditor" in users
        assert "procurement_lead" in users
        assert "subsidiary_lead" in users
        # Passwords should be hashed and verifiable
        assert auth.pwd_context.verify("admin123", users["admin"]["password_hash"])
        assert auth.pwd_context.verify("analyst123", users["analyst"]["password_hash"])
        assert auth.pwd_context.verify("auditor123", users["auditor"]["password_hash"])
        assert auth.pwd_context.verify("lead123", users["procurement_lead"]["password_hash"])
        assert auth.pwd_context.verify("lead123", users["subsidiary_lead"]["password_hash"])
        # org_ids
        assert users["admin"]["org_id"] == 1000
        assert users["subsidiary_lead"]["org_id"] == 1021

    def test_entry_missing_password_raises_value_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        yaml_content = """
users:
  nopass:
    id: nopass
    username: nopass
    # password intentionally missing
    roles: [analyst]
"""
        yaml_file = tmp_path / "users.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        monkeypatch.setenv("HONEYBADGE_USERS_CONFIG", str(yaml_file))

        from honeybadge.server import auth

        # Should fall back to defaults (malformed entry)
        users = auth.load_demo_users()
        assert "admin" in users  # default
        assert "nopass" not in users

    def test_authenticate_user_with_yaml_loaded_users(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """authenticate_user must work with YAML-loaded users."""
        yaml_content = """
users:
  yamluser:
    id: yamluser
    username: yamluser
    password: yamlpass123
    display_name: YAML User
    roles: [analyst]
    org_id: 7777
"""
        yaml_file = tmp_path / "users.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")
        monkeypatch.setenv("HONEYBADGE_USERS_CONFIG", str(yaml_file))

        # Re-import auth module so DEMO_USERS picks up the env var
        import honeybadge.server.auth as auth_mod

        importlib.reload(auth_mod)

        user = auth_mod.authenticate_user("yamluser", "yamlpass123")
        assert user is not None
        assert user["username"] == "yamluser"
        assert user["org_id"] == 7777

        # Wrong password
        assert auth_mod.authenticate_user("yamluser", "wrong") is None

        # Unknown user
        assert auth_mod.authenticate_user("nobody", "yamlpass123") is None

        # Clean up: reload without env var to restore defaults
        monkeypatch.delenv("HONEYBADGE_USERS_CONFIG", raising=False)
        importlib.reload(auth_mod)


# ---------------------------------------------------------------------------
# Module-level singleton initialization
# ---------------------------------------------------------------------------


class TestModuleLevelSingletons:
    """Verify PERMISSION_CONFIG and DEMO_USERS are populated at import time."""

    def test_permission_config_singleton_populated(self) -> None:
        from honeybadge.permission_service.config import PERMISSION_CONFIG

        assert isinstance(PERMISSION_CONFIG, dict)
        assert len(PERMISSION_CONFIG) >= 5  # at least the 5 demo users
        assert "admin" in PERMISSION_CONFIG

    def test_demo_users_singleton_populated(self) -> None:
        from honeybadge.server.auth import DEMO_USERS

        assert isinstance(DEMO_USERS, dict)
        assert len(DEMO_USERS) >= 5
        assert "admin" in DEMO_USERS
        assert "password_hash" in DEMO_USERS["admin"]

    def test_demo_users_password_hash_not_plaintext(self) -> None:
        from honeybadge.server.auth import DEMO_USERS

        for username, user in DEMO_USERS.items():
            # bcrypt hashes start with $2
            assert user["password_hash"].startswith("$2"), (
                f"User {username} password_hash is not a bcrypt hash"
            )
            assert "password" not in user, f"User {username} retains plaintext 'password' key"


# ---------------------------------------------------------------------------
# Shipped config file structure
# ---------------------------------------------------------------------------


class TestShippedConfigFiles:
    """Verify the shipped deploy/config/*.yaml files exist and are well-formed."""

    def test_permissions_yaml_exists(self) -> None:
        assert (_CONFIG_DIR / "permissions.yaml").exists(), (
            "deploy/config/permissions.yaml must exist for externalized config"
        )

    def test_users_yaml_exists(self) -> None:
        assert (_CONFIG_DIR / "users.yaml").exists(), (
            "deploy/config/users.yaml must exist for externalized demo users"
        )

    def test_permissions_yaml_has_required_keys(self) -> None:
        import yaml

        path = _CONFIG_DIR / "permissions.yaml"
        if not path.exists():
            pytest.skip("permissions.yaml not present")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "permissions" in data
        perms = data["permissions"]
        for user_id, entry in perms.items():
            assert "allowed_processes" in entry, f"{user_id} missing allowed_processes"
            assert "data_scope" in entry, f"{user_id} missing data_scope"

    def test_users_yaml_has_required_keys(self) -> None:
        import yaml

        path = _CONFIG_DIR / "users.yaml"
        if not path.exists():
            pytest.skip("users.yaml not present")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert "users" in data
        for username, entry in data["users"].items():
            assert "password" in entry, f"{username} missing password"
            assert "roles" in entry, f"{username} missing roles"
            assert "org_id" in entry, f"{username} missing org_id"

    def test_env_example_documents_config_vars(self) -> None:
        env_example = (_PROJECT_ROOT / ".env.example").read_text(encoding="utf-8")
        assert "HONEYBADGE_PERMISSIONS_CONFIG" in env_example, (
            ".env.example must document HONEYBADGE_PERMISSIONS_CONFIG"
        )
        assert "HONEYBADGE_USERS_CONFIG" in env_example, (
            ".env.example must document HONEYBADGE_USERS_CONFIG"
        )
