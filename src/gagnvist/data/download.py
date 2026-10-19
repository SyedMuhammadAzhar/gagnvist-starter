"""Getting the data onto this computer, and checking that it is complete.

The organizers publish the data folder as one zip file. :func:`get_data` downloads it
(or takes a zip you already have), checks the zip against its published checksum,
unpacks it, and then checks every file against ``SHA256SUMS.txt`` inside it.
"""

from __future__ import annotations

import hashlib
import logging
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import httpx

log = logging.getLogger(__name__)

_CHUNK_SIZE = 1 << 20  # read and write files in pieces of 1 MB
_ZIP_ROOT = "data"  # every file in the zip sits under data/


class DataError(Exception):
    """The data could not be downloaded, unpacked or verified."""


@dataclass
class CheckResult:
    """The outcome of checking a data folder against SHA256SUMS.txt."""

    files_checked: int = 0
    missing: list[str] = field(default_factory=list)
    damaged: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.damaged


def get_data(
    target: Path,
    *,
    url: str = "",
    sha256: str = "",
    zip_file: Path | None = None,
    client: httpx.Client | None = None,
) -> CheckResult:
    """Download (or take) the data zip, unpack it into ``target`` and check it.

    ``target`` must not exist yet, or be empty: nothing already there is overwritten.
    """
    if target.exists() and any(target.iterdir()):
        raise DataError(
            f"{target} already exists and is not empty; the data is not unpacked over it"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    # Work next to the target, so unpacking ends with a quick rename rather than a copy.
    with tempfile.TemporaryDirectory(prefix=".gagnvist-", dir=target.parent) as work:
        work_dir = Path(work)
        archive = zip_file or _download(url, work_dir / "data.zip", client)
        if sha256:
            _check_checksum(archive, sha256)
        unpacked = _unpack(archive, work_dir / "unpacked")
        if target.exists():
            target.rmdir()  # empty, as checked above
        unpacked.rename(target)
    return check_data(target)


def check_data(folder: Path) -> CheckResult:
    """Check every file listed in ``folder/SHA256SUMS.txt`` against its checksum."""
    listing = folder / "SHA256SUMS.txt"
    if not listing.is_file():
        raise DataError(f"{listing} not found: is {folder} the data folder?")
    result = CheckResult()
    lines = listing.read_text(encoding="utf-8").splitlines()
    for number, line in enumerate(lines, 1):
        expected, _, relative = line.partition("  ")
        path = folder / relative
        if not path.is_file():
            result.missing.append(relative)
        elif _sha256(path) != expected:
            result.damaged.append(relative)
        result.files_checked += 1
        if number % 1000 == 0:
            log.info("  checked %s of %s files", f"{number:,}", f"{len(lines):,}")
    return result


def _download(url: str, destination: Path, client: httpx.Client | None) -> Path:
    if not url:
        raise DataError(
            "no download address: set [data] download_url in gagnvist.toml, "
            "or pass a zip you already have with --zip"
        )
    log.info("downloading %s", url)
    own_client = client is None
    http = client or httpx.Client(follow_redirects=True, timeout=60)
    try:
        with http.stream("GET", url) as response:
            response.raise_for_status()
            total = int(response.headers.get("content-length", 0))
            received, next_report = 0, 0.1
            with destination.open("wb") as f:
                for chunk in response.iter_bytes(_CHUNK_SIZE):
                    f.write(chunk)
                    received += len(chunk)
                    if total and received / total >= next_report:
                        log.info(
                            "  %3.0f%% of %s MB", 100 * received / total, f"{total / 1e6:,.0f}"
                        )
                        next_report += 0.1
    except httpx.HTTPError as e:
        raise DataError(f"the download failed: {e}") from e
    finally:
        if own_client:
            http.close()
    return destination


def _check_checksum(archive: Path, expected: str) -> None:
    log.info("checking the zip's checksum")
    actual = _sha256(archive)
    if actual != expected.lower():
        raise DataError(
            f"{archive.name} is damaged or not the published file "
            f"(checksum {actual}, expected {expected})"
        )


def _unpack(archive: Path, destination: Path) -> Path:
    """Unpack the zip into ``destination`` and return the data folder inside it."""
    log.info("unpacking %s", archive.name)
    try:
        with zipfile.ZipFile(archive) as z:
            for name in z.namelist():
                parts = PurePosixPath(name).parts
                if not parts or parts[0] != _ZIP_ROOT or ".." in parts or name.startswith("/"):
                    raise DataError(f"{archive.name} contains an unexpected entry: {name!r}")
            z.extractall(destination)
    except zipfile.BadZipFile as e:
        raise DataError(f"{archive.name} is not a valid zip file") from e
    return destination / _ZIP_ROOT


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
