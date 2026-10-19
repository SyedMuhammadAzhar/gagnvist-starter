"""Shared test fixtures: a miniature copy of the data release (see fixtures/README.md),
the stand-in model server (see standin.py) and a fake LUMI (see fake_lumi.py)."""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
import standin
from fake_lumi import FakeLumi, make_programs

from gagnvist.models.client import Endpoint, ModelClient
from gagnvist.search.table_index import build_index

FIXTURE_DATA = Path(__file__).parent / "fixtures" / "data"
SHARED_SETTINGS = Path(__file__).parents[1] / "gagnvist.toml"


def write_settings(
    folder: Path, env: dict[str, str] | None = None, changes: dict[str, str] | None = None
) -> Path:
    """A copy of gagnvist.toml in ``folder``, with ``changes`` ({old text: new text})
    made in it, and a .env next to it holding ``env``; returns gagnvist.toml's path."""
    text = SHARED_SETTINGS.read_text(encoding="utf-8")
    for old, new in (changes or {}).items():
        assert old in text, old
        text = text.replace(old, new)
    path = folder / "gagnvist.toml"
    path.write_text(text, encoding="utf-8")
    if env is not None:
        lines = [f"{name}={value}" for name, value in env.items()]
        (folder / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


@pytest.fixture
def data_folder() -> Path:
    return FIXTURE_DATA


@pytest.fixture
def table_database(tmp_path: Path) -> Path:
    """The table database built from the miniature data release."""
    path = tmp_path / "tables.sqlite"
    build_index(FIXTURE_DATA, path)
    return path


@pytest.fixture(scope="session")
def fake_programs(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return make_programs(tmp_path_factory.mktemp("fake-lumi-programs"))


@pytest.fixture
def fake_lumi(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_programs: Path) -> FakeLumi:
    """A fake LUMI on this computer (see fake_lumi.py)."""
    return FakeLumi(tmp_path, monkeypatch, fake_programs)


@pytest.fixture
def fake_lumi_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_programs: Path):  # type: ignore[no-untyped-def]
    """Settings that point at the fake LUMI, for tests that need only the settings."""
    return FakeLumi(tmp_path, monkeypatch, fake_programs).settings


@pytest.fixture
def standin_client() -> Iterator[ModelClient]:
    """A model client whose requests are answered by the stand-in, without a network."""
    url = "http://standin/v1"
    client = ModelClient(
        chat=Endpoint(url, "test-key", standin.CHAT_MODEL),
        embeddings=Endpoint(url, "test-key", standin.EMBEDDING_MODEL),
        http=httpx.Client(transport=httpx.MockTransport(standin.handle)),
    )
    yield client
    client.close()
