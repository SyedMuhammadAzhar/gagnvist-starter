"""Downloading, unpacking and checking the data."""

import hashlib
import shutil
import zipfile
from pathlib import Path

import httpx
import pytest

from gagnvist.data.download import DataError, check_data, get_data


def _zip_of(folder: Path, destination: Path, extra: dict[str, bytes] | None = None) -> Path:
    """A zip shaped like the published one: every file under data/."""
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder.rglob("*")):
            if path.is_file():
                z.write(path, "data/" + path.relative_to(folder).as_posix())
        for name, content in (extra or {}).items():
            z.writestr(name, content)
    return destination


def test_fixture_data_checks_out(data_folder: Path) -> None:
    result = check_data(data_folder)
    assert result.ok
    assert result.files_checked == 26


def test_damaged_and_missing_files_are_found(data_folder: Path, tmp_path: Path) -> None:
    copy = tmp_path / "data"
    shutil.copytree(data_folder, copy)
    damaged = next(copy.rglob("data.px"))
    damaged.write_bytes(damaged.read_bytes() + b" ")
    missing = next(copy.rglob("metadata.json"))
    missing.unlink()
    result = check_data(copy)
    assert not result.ok
    assert [str(copy / d) for d in result.damaged] == [str(damaged)]
    assert [str(copy / m) for m in result.missing] == [str(missing)]


def test_get_data_from_a_zip_you_have(data_folder: Path, tmp_path: Path) -> None:
    archive = _zip_of(data_folder, tmp_path / "data.zip")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    result = get_data(tmp_path / "data", zip_file=archive, sha256=checksum)
    assert result.ok
    assert (tmp_path / "data" / "catalogue.csv").is_file()


def test_a_zip_with_the_wrong_checksum_is_refused(data_folder: Path, tmp_path: Path) -> None:
    archive = _zip_of(data_folder, tmp_path / "data.zip")
    with pytest.raises(DataError, match="damaged or not the published file"):
        get_data(tmp_path / "data", zip_file=archive, sha256="0" * 64)
    assert not (tmp_path / "data").exists()


def test_a_zip_reaching_outside_the_data_folder_is_refused(
    data_folder: Path, tmp_path: Path
) -> None:
    archive = _zip_of(data_folder, tmp_path / "data.zip", extra={"data/../evil.txt": b"x"})
    with pytest.raises(DataError, match="unexpected entry"):
        get_data(tmp_path / "data", zip_file=archive)


def test_existing_data_is_never_overwritten(data_folder: Path, tmp_path: Path) -> None:
    archive = _zip_of(data_folder, tmp_path / "data.zip")
    target = tmp_path / "data"
    target.mkdir()
    (target / "my-notes.txt").write_text("keep me", encoding="utf-8")
    with pytest.raises(DataError, match="not empty"):
        get_data(target, zip_file=archive)
    assert (target / "my-notes.txt").read_text(encoding="utf-8") == "keep me"


def test_download_from_the_published_address(data_folder: Path, tmp_path: Path) -> None:
    archive = _zip_of(data_folder, tmp_path / "published.zip").read_bytes()

    def serve(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/data.zip"
        return httpx.Response(200, content=archive, headers={"content-length": str(len(archive))})

    client = httpx.Client(transport=httpx.MockTransport(serve))
    result = get_data(
        tmp_path / "data",
        url="https://example.org/data.zip",
        sha256=hashlib.sha256(archive).hexdigest(),
        client=client,
    )
    assert result.ok


def test_a_failed_download_is_reported(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(404)))
    with pytest.raises(DataError, match="download failed"):
        get_data(tmp_path / "data", url="https://example.org/missing.zip", client=client)


def _split(archive: Path, pieces: int) -> None:
    """Store ``archive`` as pieces, as data-release/ does, and remove the whole file."""
    content = archive.read_bytes()
    size = len(content) // pieces + 1
    for number in range(pieces):
        piece = archive.with_name(f"{archive.name}.part{number + 1:02}")
        piece.write_bytes(content[number * size : (number + 1) * size])
    archive.unlink()


def test_get_data_joins_the_pieces_that_come_with_the_repository(
    data_folder: Path, tmp_path: Path
) -> None:
    (tmp_path / "release").mkdir()
    archive = _zip_of(data_folder, tmp_path / "release" / "data.zip")
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    _split(archive, 3)
    result = get_data(tmp_path / "data", archive=archive, sha256=checksum)
    assert result.ok and result.files_checked == 26
    assert sorted(p.name for p in (tmp_path / "release").iterdir()) == [
        "data.zip.part01",
        "data.zip.part02",
        "data.zip.part03",
    ]  # the pieces are left as they were


def test_a_missing_piece_is_reported(data_folder: Path, tmp_path: Path) -> None:
    archive = _zip_of(data_folder, tmp_path / "data.zip")
    _split(archive, 3)
    (tmp_path / "data.zip.part02").unlink()
    with pytest.raises(DataError, match="incomplete or misnamed"):
        get_data(tmp_path / "data", archive=archive)


def test_without_the_zip_the_message_says_where_it_should_be(tmp_path: Path) -> None:
    with pytest.raises(DataError, match="comes with the repository"):
        get_data(tmp_path / "data", archive=tmp_path / "data-release" / "data.zip")
