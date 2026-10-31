"""Settings: shared ones in ``gagnvist.toml``, personal ones in ``.env``.

``gagnvist.toml`` holds what is the same for everyone (the hackathon's project on
JURECA, the shared models, where the data is), set by the organizers and committed with
the code.

``.env`` holds what is yours alone: your JURECA username, the path to your SSH key, your
team's key, and the address and key of any model server of your own. Copy
``example.env`` to ``.env`` and fill it in; git ignores ``.env``, so it is never
committed. A value in ``.env``, or in an environment variable of the same name, replaces
the same setting in ``gagnvist.toml``.

Each part of the program checks only the settings it needs, so for example the data can
be downloaded and indexed before JURECA access is set up.

The commands use JURECA unless ``GAGNVIST_CLUSTER`` in .env, or ``--cluster`` on the
command, names another supercomputer this edition knows (see :mod:`gagnvist.clusters`).
"""

from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from gagnvist.clusters import CLUSTERS, DEFAULT_CLUSTER, Cluster

DEFAULT_CONFIG_FILE = Path("gagnvist.toml")
ENV_FILE = ".env"  # next to gagnvist.toml

# The personal settings, by their name in .env and their place in gagnvist.toml. Your
# account on each supercomputer comes first (GAGNVIST_JURECA_USERNAME and
# GAGNVIST_JURECA_SSH_KEY for JURECA; the names are in the supercomputer's profile).
PERSONAL_SETTINGS: dict[str, tuple[str, str]] = {}
for _cluster in CLUSTERS.values():
    PERSONAL_SETTINGS[_cluster.username_setting] = (_cluster.name, "username")
    PERSONAL_SETTINGS[_cluster.ssh_key_setting] = (_cluster.name, "ssh_key")
PERSONAL_SETTINGS.update(
    {
        "GAGNVIST_TEAM_KEY": ("team", "key"),
        "GAGNVIST_CLUSTER": ("clusters", "default"),  # which supercomputer the commands use
        "GAGNVIST_CHAT_MODEL": ("models", "chat"),
        "GAGNVIST_CHAT_URL": ("models", "chat_url"),
        "GAGNVIST_CHAT_KEY": ("models", "chat_key"),
        "GAGNVIST_EMBEDDINGS_MODEL": ("models", "embeddings"),
        "GAGNVIST_EMBEDDINGS_URL": ("models", "embeddings_url"),
        "GAGNVIST_EMBEDDINGS_KEY": ("models", "embeddings_key"),
        # To change these without editing gagnvist.toml (which `git pull` updates):
        "GAGNVIST_SEARCH_INDEX": ("search", "index"),
        "GAGNVIST_SEARCH_CARDS": ("search", "cards"),
    }
)
for _cluster in CLUSTERS.values():  # the port of your tunnel to its shared models
    PERSONAL_SETTINGS[_cluster.local_port_setting] = (_cluster.name, "local_port")

# The personal settings of the LUMI edition of the starter kit (the repository's main
# branch). A .env written for it, or for both editions, is read without complaint
# here, and these lines of it are ignored.
IGNORED_SETTINGS = frozenset({"GAGNVIST_LUMI_USERNAME", "GAGNVIST_SSH_KEY", "GAGNVIST_LOCAL_PORT"})

# Team keys are 48 letters and digits (hexadecimal), made by the organizers.
TEAM_KEY_LENGTH = 48
_TEAM_KEY = re.compile(r"[0-9a-f]{48}")
# Characters that sneak in when a key is copied from a chat or a document.
_INVISIBLE = "\u200b\u200c\u200d\u2060\ufeff\u00a0"
_QUOTES = {('"', '"'), ("'", "'"), ("\u201c", "\u201d"), ("\u2018", "\u2019"), ("\u201e", "\u201c")}

# Values from the example files that mean "not filled in yet".
_EXAMPLE_VALUES = {
    *(f"your_{name}_username" for name in CLUSTERS),
    "paste-your-team-key-here",
    "project_000000000",
    "organizer_username",
}


class ConfigError(Exception):
    """A setting is missing, malformed, or still holds an example value."""


@dataclass(frozen=True)
class ClusterSettings:
    """One supercomputer as the settings describe it: your account on it, the
    hackathon's project there, and where its shared models run."""

    name: str  # "jureca", or another name in gagnvist.clusters.CLUSTERS
    username: str
    ssh_key: Path | None  # your private key for it; None until set
    host: str
    project: str
    container: str  # the software for model jobs: a container image there
    gateway_user: str  # the organizer whose job serves the shared models
    gateway_job: str  # the name of that job
    gateway_port: int  # the port it listens on, on its node
    local_port: int  # the port on this computer where the tunnel to the shared models ends

    @property
    def profile(self) -> Cluster:
        """The facts about this supercomputer (see gagnvist.clusters)."""
        return CLUSTERS[self.name]


@dataclass(frozen=True)
class ModelSettings:
    chat: str
    embeddings: str
    # The address and key of a model server you run yourself; empty for the shared models.
    chat_url: str
    chat_key: str
    embeddings_url: str
    embeddings_key: str


@dataclass(frozen=True)
class DataSettings:
    folder: Path  # where the data is unpacked
    archive: Path | None  # the data zip that comes with the repository (whole or in pieces)
    download_url: str  # where to download the zip instead, if it does not come with it
    sha256: str  # the zip's checksum


@dataclass(frozen=True)
class SearchSettings:
    index: Path  # the vector index used to find tables; made with [models] embeddings
    cards: Path  # the table cards whose texts build-vectors embeds


@dataclass(frozen=True)
class Settings:
    clusters: dict[str, ClusterSettings]  # every supercomputer gagnvist.toml describes, by name
    team_key: str  # your team's key, which the shared models ask for
    models: ModelSettings
    data: DataSettings
    search: SearchSettings
    project_folder: Path  # the folder gagnvist.toml is in
    default_cluster: str = DEFAULT_CLUSTER  # whose shared models the commands use

    @property
    def local_folder(self) -> Path:
        """Files made on this computer, such as the table database (not committed)."""
        return self.project_folder / "local"

    @property
    def table_database(self) -> Path:
        return self.local_folder / "tables.sqlite"

    def cluster(self, name: str | None = None) -> ClusterSettings:
        """The settings of the supercomputer called ``name``: by default the one the
        commands use (GAGNVIST_CLUSTER in .env, or --cluster)."""
        name = name or self.default_cluster
        try:
            return self.clusters[name]
        except KeyError:
            if name in CLUSTERS:
                raise ConfigError(
                    f"this starter kit is not set up for {CLUSTERS[name].label}: gagnvist.toml "
                    f"has no [{name}] section (get the latest version of the starter kit)"
                ) from None
            raise ConfigError(
                f"there is no supercomputer called {name!r}: GAGNVIST_CLUSTER (or --cluster) "
                f"is {' or '.join(CLUSTERS)}"
            ) from None

    def using_cluster(self, name: str) -> Settings:
        """The same settings, with the commands using the supercomputer ``name``."""
        self.cluster(name)  # known, and set up
        return replace(self, default_cluster=name)

    def with_cluster(self, account: ClusterSettings) -> Settings:
        """The same settings, with ``account`` in place of that supercomputer's."""
        return replace(self, clusters={**self.clusters, account.name: account})

    def require_access(self, name: str | None = None) -> None:
        """Raise ConfigError unless everything needed to reach the supercomputer ``name``
        (by default the one the commands use) is filled in."""
        account = self.cluster(name)
        facts = account.profile
        if not account.username or account.username in _EXAMPLE_VALUES:
            raise ConfigError(_personal(facts.username_setting, f"your {facts.label} username"))
        if account.project in _EXAMPLE_VALUES:
            raise ConfigError(
                f"the hackathon's {facts.label} project is missing in gagnvist.toml "
                f"([{account.name}] project)"
            )
        if account.ssh_key is None:
            raise ConfigError(_personal(facts.ssh_key_setting, "the path to your own SSH key"))
        if not account.ssh_key.is_file():
            raise ConfigError(
                f"your SSH key was not found at {account.ssh_key} "
                f"(check {facts.ssh_key_setting} in .env)"
            )
        if account.ssh_key.suffix == ".pub":
            raise ConfigError(
                f"{facts.ssh_key_setting} points to {account.ssh_key.name}, the public half "
                "of the key: give the private key, the same name without .pub"
            )
        with account.ssh_key.open("rb") as f:
            if f.read(20).startswith(b"PuTTY-User-Key-File"):
                raise ConfigError(
                    f"{account.ssh_key} is a PuTTY key, which ssh cannot read: in PuTTYgen, "
                    "load it and choose Conversions, Export OpenSSH key "
                    f"(see {facts.docs})"
                )

    def require_team_key(self) -> None:
        """Raise ConfigError unless the team key is filled in and can be sent.

        A key that is filled in but does not look like a team key is allowed here (see
        :func:`team_key_problem`, which ``gagnvist jureca check`` reports)."""
        key = self.team_key
        if not key or key in _EXAMPLE_VALUES:
            raise ConfigError(_personal("GAGNVIST_TEAM_KEY", "your team's key"))
        if not key.isascii() or any(c.isspace() for c in key):
            raise ConfigError(
                f"GAGNVIST_TEAM_KEY in .env is not a key: {team_key_problem(key)}. "
                "Copy the key again, exactly as the organizers sent it."
            )

    def require_gateway(self, name: str | None = None) -> None:
        """Raise ConfigError unless the organizers have said where the shared models on
        the supercomputer ``name`` (by default the one the commands use) run."""
        account = self.cluster(name)
        if account.gateway_user in _EXAMPLE_VALUES:
            raise ConfigError(
                f"[{account.name}] gateway_user is not filled in in gagnvist.toml: the "
                "organizers set it (get the latest version of the starter kit)"
            )


def load_settings(path: Path = DEFAULT_CONFIG_FILE) -> Settings:
    """Read gagnvist.toml, then .env next to it, then the environment.

    Relative paths are relative to the folder gagnvist.toml is in.
    """
    if not path.is_file():
        raise ConfigError(
            f"{path} not found: run gagnvist in the starter kit's folder, or give the "
            "settings file with --config"
        )
    try:
        # utf-8-sig: an editor on Windows may have saved it with a byte-order mark
        raw = tomllib.loads(path.read_bytes().decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise ConfigError(
            f"{path} is not saved as UTF-8: `git checkout gagnvist.toml` brings back the original"
        ) from None
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(
            f"{path} is not valid TOML: {e}. (A Windows path must be written with "
            "forward slashes, or in single quotes.)"
        ) from e
    base = path.resolve().parent
    env_file = base / ENV_FILE
    if not env_file.is_file() and (base / f"{ENV_FILE}.txt").is_file():
        raise ConfigError(
            f"found {ENV_FILE}.txt but no {ENV_FILE}: rename it to {ENV_FILE} (Windows hides "
            "the .txt ending, and Notepad adds it; in Notepad choose 'All files' when saving)"
        )
    personal = read_env_file(env_file) if env_file.is_file() else {}
    personal.update({name: os.environ[name] for name in PERSONAL_SETTINGS if name in os.environ})
    for name, value in personal.items():
        section, key = PERSONAL_SETTINGS[name]
        if key == "local_port":
            raw.setdefault(section, {})[key] = _port_text(name, value)
        elif section == "search" and os.sep == "/":
            # a folder written the Windows way (local\index-e5), say by a teammate
            raw.setdefault(section, {})[key] = value.replace("\\", "/")
        else:
            raw.setdefault(section, {})[key] = value

    models = _section(raw, "models")
    data = _section(raw, "data")
    search = _section(raw, "search")
    archive = _text(data, "data", "archive", required=False)
    # The default supercomputer must be described; any other one of this edition may be.
    clusters = {}
    for name in CLUSTERS:
        if _describes_cluster(raw.get(name)):
            clusters[name] = _cluster_settings(raw, name, base)
        elif name == DEFAULT_CLUSTER:
            raise ConfigError(f"gagnvist.toml has no [{name}] section")
    default_cluster = _text(raw.get("clusters") or {}, "clusters", "default", required=False)
    if default_cluster and default_cluster not in CLUSTERS:
        raise ConfigError(
            f"GAGNVIST_CLUSTER in .env is {default_cluster!r}: it is {' or '.join(CLUSTERS)}"
        )
    return Settings(
        clusters=clusters,
        team_key=_text(raw.get("team") or {}, "team", "key", required=False),
        default_cluster=default_cluster or DEFAULT_CLUSTER,
        models=ModelSettings(
            chat=_text(models, "models", "chat"),
            embeddings=_text(models, "models", "embeddings"),
            chat_url=_text(models, "models", "chat_url", required=False),
            chat_key=_text(models, "models", "chat_key", required=False),
            embeddings_url=_text(models, "models", "embeddings_url", required=False),
            embeddings_key=_text(models, "models", "embeddings_key", required=False),
        ),
        data=DataSettings(
            folder=base / _text(data, "data", "folder"),
            archive=base / archive if archive else None,
            download_url=_text(data, "data", "download_url", required=False),
            sha256=_text(data, "data", "sha256", required=False).lower(),
        ),
        search=SearchSettings(
            index=base / _text(search, "search", "index"),
            cards=base / (_text(search, "search", "cards", required=False) or "cards"),
        ),
        project_folder=base,
    )


def _describes_cluster(section: Any) -> bool:
    """Whether a [section] of gagnvist.toml describes a supercomputer (and does not just
    hold the personal settings for one, which .env may put there anyway)."""
    return isinstance(section, dict) and any(
        key in section for key in ("host", "project", "container", "gateway_user")
    )


def _cluster_settings(raw: dict[str, Any], name: str, base: Path) -> ClusterSettings:
    """The [name] section of gagnvist.toml, with the personal settings for that
    supercomputer from .env."""
    section = _section(raw, name)
    ssh_key = _text(section, name, "ssh_key", required=False)
    return ClusterSettings(
        name=name,
        username=_text(section, name, "username", required=False),
        ssh_key=_key_path(base, ssh_key) if ssh_key else None,
        host=_text(section, name, "host"),
        project=_text(section, name, "project"),
        container=_text(section, name, "container"),
        gateway_user=_text(section, name, "gateway_user"),
        gateway_job=_text(section, name, "gateway_job"),
        gateway_port=_port(section, name, "gateway_port"),
        local_port=_port(section, name, "local_port"),
    )


def team_key_problem(key: str) -> str | None:
    """What is wrong with a team key, in words; None if it looks right."""
    if _TEAM_KEY.fullmatch(key):
        return None
    found = [f"it has {len(key)} characters (a team key has {TEAM_KEY_LENGTH})"]
    if any(c in "\"'\u201c\u201d\u2018\u2019\u201e" for c in key):
        found.append("it contains quote marks")
    if any(c.isspace() for c in key):
        found.append("it contains spaces")
    if not key.isascii():
        found.append("it contains characters other than letters and digits")
    elif len(key) == TEAM_KEY_LENGTH and not found[1:]:
        found = ["it contains characters other than 0-9 and a-f"]
    return ", ".join(found)


def read_env_file(path: Path) -> dict[str, str]:
    """The settings in a .env file: one ``NAME=value`` per line.

    Blank lines and lines that start with ``#`` are skipped. A value may be put in
    quotes; otherwise a `` #`` and everything after it is a comment. Every name must be
    one of PERSONAL_SETTINGS, so that a misspelt name is reported, not ignored (the LUMI
    edition's names, IGNORED_SETTINGS, are skipped quietly).
    """
    raw = path.read_bytes()
    # UTF-16 has a zero byte in every letter of .env; a file that is partly UTF-16 (as
    # after Windows PowerShell's `echo ... >> .env`) has no byte-order mark to tell.
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")) or b"\x00" in raw:
        raise ConfigError(
            f"{path} is saved as UTF-16 (as Windows PowerShell's `>` and Notepad's "
            "'Unicode' do): save it as UTF-8 instead (in Notepad: File, Save as, Encoding: UTF-8)"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ConfigError(
            f"{path} is not saved as UTF-8: save it as UTF-8 (in Notepad: File, Save as, "
            "Encoding: UTF-8)"
        ) from None
    values = {}
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, equals, value = line.removeprefix("export ").partition("=")
        name, value = name.strip(), value.strip(_INVISIBLE + " \t")
        if not equals or (name not in PERSONAL_SETTINGS and name not in IGNORED_SETTINGS):
            known = ", ".join(PERSONAL_SETTINGS)
            raise ConfigError(f"{path}, line {number}: expected NAME=value, NAME one of {known}")
        if name in IGNORED_SETTINGS:
            continue
        if len(value) >= 2 and (value[0], value[-1]) in _QUOTES:
            value = value[1:-1].strip(_INVISIBLE)
        else:
            value = value.split(" #", 1)[0].strip(_INVISIBLE + " \t")
        values[name] = value
    return values


# How a home folder is written in a shell (PowerShell, Command Prompt, macOS, Linux):
# none of these is expanded in .env, so they are turned into ~ first.
_HOME_WRITTEN = re.compile(
    r"^(?:\$HOME|\$\{HOME\}|%USERPROFILE%|\$env:USERPROFILE)(?=[\\/]|$)", re.I
)


def _key_path(base: Path, text: str) -> Path:
    """The SSH key's path: ``~`` (or ``$HOME``, ``%USERPROFILE%``, ``$env:USERPROFILE``)
    is your home folder, and a relative path is relative to the folder gagnvist.toml is in."""
    text = _HOME_WRITTEN.sub("~", text)
    if text.startswith("~") and os.sep == "/":
        text = "~/" + text[1:].lstrip("\\/").replace("\\", "/")  # ~\.ssh\key on macOS
    try:
        return base / Path(text).expanduser()
    except RuntimeError:  # no home folder could be found for ~
        raise ConfigError(
            f"the SSH key {text}: the ~ could not be turned into your home folder; "
            "write the whole path instead"
        ) from None


def _port_text(name: str, value: str) -> int:
    """A port number given as text in .env, as a number (checked later like any port)."""
    try:
        return int(value)
    except ValueError:
        raise ConfigError(f"{name} in .env must be a port number, 1024 to 65535") from None


def _personal(name: str, what: str) -> str:
    return (
        f"set {what} as {name} in .env (copy example.env to .env first, if you have not; "
        ".env stays on your computer)"
    )


def _section(raw: dict[str, Any], name: str) -> dict[str, Any]:
    section = raw.get(name)
    if not isinstance(section, dict):
        raise ConfigError(f"gagnvist.toml has no [{name}] section")
    return section


def _text(section: dict[str, Any], name: str, key: str, *, required: bool = True) -> str:
    value = section.get(key, "")
    if not isinstance(value, str):
        raise ConfigError(f"[{name}] {key} in gagnvist.toml must be text in quotes")
    if required and not value.strip():
        raise ConfigError(f"[{name}] {key} is empty in gagnvist.toml")
    return value.strip()


def _port(section: dict[str, Any], name: str, key: str) -> int:
    value = section.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or not 1024 <= value <= 65535:
        raise ConfigError(f"[{name}] {key} in gagnvist.toml must be a port number, 1024 to 65535")
    return value
