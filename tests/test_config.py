"""Reading the settings: gagnvist.toml, then .env, then the environment."""

import re
import tomllib
from pathlib import Path

import pytest
from conftest import SHARED_SETTINGS, write_settings

from gagnvist.config import PERSONAL_SETTINGS, ConfigError, load_settings

EXAMPLE_ENV = Path(__file__).parents[1] / "example.env"


@pytest.fixture(autouse=True)
def no_personal_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings in the environment of whoever runs the tests must not leak in."""
    for name in PERSONAL_SETTINGS:
        monkeypatch.delenv(name, raising=False)


def test_shared_settings_load_and_paths_are_relative_to_them(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    assert settings.data.folder == tmp_path / "data"
    assert settings.search.index == tmp_path / "index"
    assert settings.shared_services.local_port == 8765
    assert settings.models.embeddings == "bge-m3"


def test_personal_settings_come_from_env(tmp_path: Path) -> None:
    key = tmp_path / "keys" / "id_ed25519_lumi"
    env = {"GAGNVIST_LUMI_USERNAME": "jon", "GAGNVIST_SSH_KEY": "keys/id_ed25519_lumi",
           "GAGNVIST_TEAM_KEY": "team-07"}  # fmt: skip
    settings = load_settings(write_settings(tmp_path, env))
    assert settings.lumi.username == "jon"
    assert settings.lumi.ssh_key == key  # relative to the settings' folder
    assert settings.shared_services.team_key == "team-07"


def test_the_environment_wins_over_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GAGNVIST_TEAM_KEY", "from-the-environment")
    settings = load_settings(write_settings(tmp_path, {"GAGNVIST_TEAM_KEY": "from-env-file"}))
    assert settings.shared_services.team_key == "from-the-environment"


def test_your_own_server_replaces_the_shared_model(tmp_path: Path) -> None:
    env = {"GAGNVIST_CHAT_MODEL": "my-run", "GAGNVIST_CHAT_URL": "http://127.0.0.1:8801/v1",
           "GAGNVIST_CHAT_KEY": "abc"}  # fmt: skip
    models = load_settings(write_settings(tmp_path, env)).models
    assert (models.chat, models.chat_url, models.chat_key) == (
        "my-run",
        "http://127.0.0.1:8801/v1",
        "abc",
    )
    assert models.embeddings == "bge-m3" and models.embeddings_url == ""


def test_env_lines_may_have_quotes_comments_and_windows_paths(tmp_path: Path) -> None:
    write_settings(tmp_path)
    (tmp_path / ".env").write_text(
        "\ufeff# my settings\n"
        "\n"
        "export GAGNVIST_LUMI_USERNAME=jon  # this part is a comment\n"
        'GAGNVIST_TEAM_KEY="key with # inside"\n'
        "GAGNVIST_SSH_KEY=C:\\Users\\Jón\\.ssh\\id_ed25519_lumi\n",
        encoding="utf-8",
    )
    settings = load_settings(tmp_path / "gagnvist.toml")
    assert settings.lumi.username == "jon"
    assert settings.shared_services.team_key == "key with # inside"
    assert str(settings.lumi.ssh_key).endswith("C:\\Users\\Jón\\.ssh\\id_ed25519_lumi")


def test_a_misspelt_name_in_env_is_reported(tmp_path: Path) -> None:
    write_settings(tmp_path)
    (tmp_path / ".env").write_text("GAGNVIST_LUMI_USERNAME=jon\nGAGNVIST_TEAMKEY=x\n")
    with pytest.raises(ConfigError, match=r"\.env, line 2: expected NAME=value"):
        load_settings(tmp_path / "gagnvist.toml")


def test_example_env_copied_unchanged_asks_for_the_real_values(tmp_path: Path) -> None:
    settings_file = write_settings(tmp_path)
    (tmp_path / ".env").write_text(EXAMPLE_ENV.read_text(encoding="utf-8"), encoding="utf-8")
    settings = load_settings(settings_file)
    with pytest.raises(ConfigError, match=r"GAGNVIST_LUMI_USERNAME in \.env"):
        settings.require_lumi_access()
    with pytest.raises(ConfigError, match=r"GAGNVIST_TEAM_KEY in \.env"):
        settings.require_team_key()


def test_without_env_the_message_says_how_to_make_one(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path))
    with pytest.raises(ConfigError, match=r"copy example\.env to \.env"):
        settings.require_team_key()


def test_a_missing_settings_file_is_explained(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="run gagnvist in the starter kit's folder"):
        load_settings(tmp_path / "gagnvist.toml")


@pytest.mark.parametrize("value", ['"8765"', "80", "70000", "true"])
def test_a_port_that_is_not_a_port_number_is_reported(tmp_path: Path, value: str) -> None:
    path = write_settings(tmp_path, changes={"local_port = 8765": f"local_port = {value}"})
    with pytest.raises(ConfigError, match="port number"):
        load_settings(path)


def test_the_gateway_must_be_filled_in_by_the_organizers(tmp_path: Path) -> None:
    filled_in = re.search(
        r'(?m)^gateway_user = "[^"]*"', SHARED_SETTINGS.read_text(encoding="utf-8")
    )
    assert filled_in
    path = write_settings(tmp_path, changes={filled_in[0]: 'gateway_user = "organizer_username"'})
    with pytest.raises(ConfigError, match="gateway_user"):
        load_settings(path).require_gateway()


def test_the_shared_settings_hold_nothing_personal() -> None:
    shared = tomllib.loads(SHARED_SETTINGS.read_text(encoding="utf-8"))
    for section, key in PERSONAL_SETTINGS.values():
        if key in ("chat", "embeddings"):
            continue  # the shared models' names, which .env may replace
        assert key not in shared.get(section, {}), f"[{section}] {key} belongs in .env"
