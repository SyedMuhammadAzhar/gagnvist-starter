"""Reading the settings: gagnvist.toml, then .env, then the environment."""

import os
import re
import tomllib
from pathlib import Path

import pytest
from conftest import SHARED_SETTINGS, write_settings

from gagnvist.config import PERSONAL_SETTINGS, ConfigError, load_settings, team_key_problem

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
    (tmp_path / ".env").write_text(
        "GAGNVIST_LUMI_USERNAME=jon\nGAGNVIST_TEAMKEY=x\n", encoding="utf-8"
    )
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
        if key in ("chat", "embeddings", "local_port", "index", "cards"):
            continue  # shared defaults, which .env may replace
        assert key not in shared.get(section, {}), f"[{section}] {key} belongs in .env"


def test_a_env_file_saved_by_windows_tools_is_read_or_explained(tmp_path: Path) -> None:
    config = write_settings(tmp_path)
    env = tmp_path / ".env"
    env.write_bytes("\ufeffGAGNVIST_LUMI_USERNAME=me\r\n".encode())  # BOM and CRLF
    assert load_settings(config).lumi.username == "me"
    env.write_bytes("GAGNVIST_LUMI_USERNAME=me\n".encode("utf-16"))  # PowerShell's `>`
    with pytest.raises(ConfigError, match="UTF-16"):
        load_settings(config)
    env.write_bytes("GAGNVIST_SSH_KEY=C:\\Users\\\xde\xf3r\\key\n".encode("latin-1"))
    with pytest.raises(ConfigError, match="not saved as UTF-8"):
        load_settings(config)
    env.unlink()
    (tmp_path / ".env.txt").write_text("GAGNVIST_LUMI_USERNAME=me\n", encoding="utf-8")
    with pytest.raises(ConfigError, match=r"rename it to \.env"):
        load_settings(config)


def test_a_pasted_key_loses_invisible_characters_and_quotes(tmp_path: Path) -> None:
    key = "0123456789abcdef" * 3
    settings = load_settings(
        write_settings(tmp_path, {"GAGNVIST_TEAM_KEY": f"\u201c{key}\u201d\u200b"})
    )
    assert settings.shared_services.team_key == key
    settings.require_team_key()


@pytest.mark.parametrize(
    ("key", "problem"),
    [
        ("0123456789abcdef" * 3, None),
        ("team-01", "it has 7 characters (a team key has 48)"),
        ("0123456789ABCDEF" * 3, "other than 0-9 and a-f"),
        ("0123456789abcdef" * 3 + " x", "it contains spaces"),
    ],
)
def test_team_key_problems_are_put_in_words(key: str, problem: str | None) -> None:
    found = team_key_problem(key)
    assert found is None if problem is None else problem in (found or "")


def test_a_team_key_that_cannot_be_sent_is_refused(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, {"GAGNVIST_TEAM_KEY": "abc def"}))
    with pytest.raises(ConfigError, match="contains spaces"):
        settings.require_team_key()


def test_the_port_and_search_folders_can_be_set_in_env(tmp_path: Path) -> None:
    settings = load_settings(
        write_settings(
            tmp_path,
            {
                "GAGNVIST_LOCAL_PORT": "8790",
                "GAGNVIST_SEARCH_INDEX": "local/my-index",
                "GAGNVIST_SEARCH_CARDS": "local/my-cards",
            },
        )
    )
    assert settings.shared_services.local_port == 8790
    assert settings.search.index == tmp_path / "local" / "my-index"
    assert settings.search.cards == tmp_path / "local" / "my-cards"
    with pytest.raises(ConfigError, match=r"GAGNVIST_LOCAL_PORT in \.env must be a port number"):
        load_settings(write_settings(tmp_path, {"GAGNVIST_LOCAL_PORT": "eighty"}))


@pytest.mark.skipif(os.sep != "/", reason="on Windows a backslash is a folder separator anyway")
def test_a_search_folder_written_the_windows_way_works_here(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, {"GAGNVIST_SEARCH_INDEX": "local\\index-e5"}))
    assert settings.search.index == tmp_path / "local" / "index-e5"


def test_settings_saved_with_a_byte_order_mark_are_read(tmp_path: Path) -> None:
    path = write_settings(tmp_path, {"GAGNVIST_LUMI_USERNAME": "me"})
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert load_settings(path).lumi.username == "me"
    path.write_bytes("# Þ\n".encode("cp1252") + path.read_bytes()[3:])
    with pytest.raises(ConfigError, match="not saved as UTF-8"):
        load_settings(path)


def test_a_env_file_partly_in_utf16_is_explained(tmp_path: Path) -> None:
    path = write_settings(tmp_path, {"GAGNVIST_LUMI_USERNAME": "me"})
    with (tmp_path / ".env").open("ab") as f:  # as Windows PowerShell's `echo ... >> .env`
        f.write("GAGNVIST_LOCAL_PORT=8790\r\n".encode("utf-16-le"))
    with pytest.raises(ConfigError, match="UTF-16"):
        load_settings(path)


def test_a_windows_style_home_path_works_on_any_system(tmp_path: Path) -> None:
    settings = load_settings(write_settings(tmp_path, {"GAGNVIST_SSH_KEY": "~\\.ssh\\key"}))
    assert settings.lumi.ssh_key == Path.home() / ".ssh" / "key"


@pytest.mark.parametrize(
    "written",
    ["$HOME\\.ssh\\key", "$HOME/.ssh/key", "${HOME}/.ssh/key", "%USERPROFILE%\\.ssh\\key",
     "$env:USERPROFILE\\.ssh\\key", "$Env:UserProfile\\.ssh\\key"],
)  # fmt: skip
def test_a_home_folder_written_as_in_a_shell_works_too(tmp_path: Path, written: str) -> None:
    # The setup guides write $HOME\.ssh\...; .env does not expand it, so the kit does.
    settings = load_settings(write_settings(tmp_path, {"GAGNVIST_SSH_KEY": written}))
    assert settings.lumi.ssh_key == Path.home() / ".ssh" / "key"


def test_the_public_key_or_a_putty_key_is_refused(tmp_path: Path) -> None:
    public, putty = tmp_path / "id_lumi.pub", tmp_path / "lumi.ppk"
    public.write_text("ssh-ed25519 AAAA me", encoding="utf-8")
    putty.write_text("PuTTY-User-Key-File-3: ssh-ed25519\n", encoding="utf-8")
    for key, message in ((public, "public half"), (putty, "PuTTY key")):
        env = {"GAGNVIST_LUMI_USERNAME": "me", "GAGNVIST_SSH_KEY": key.as_posix()}
        with pytest.raises(ConfigError, match=message):
            load_settings(write_settings(tmp_path, env)).require_lumi_access()
