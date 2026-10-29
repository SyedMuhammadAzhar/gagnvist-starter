"""Getting the data ready on this computer, and checking that it is complete.

The data comes with the repository: one zip file, stored in pieces of under 50 MB
(``data-release/<name>.zip.part01``, ``.part02``, ...), because GitHub refuses large
files. :func:`get_data` joins the pieces, checks the zip against its checksum, unpacks
it, and then checks every file against ``SHA256SUMS.txt`` inside it. It can also take a
zip you have, or download one, if the organizers publish it elsewhere.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import httpx

from gagnvist.files import move_into_place

log = logging.getLogger(__name__)

_CHUNK_SIZE = 1 << 20  # read and write files in pieces of 1 MB
_ZIP_ROOT = "data"  # every file in the zip sits under data/
_WORK_PREFIX = ".gagnvist-"  # the folder used while unpacking, next to the data folder
_WINDOWS_PATH_LIMIT = 259  # characters in a path, unless long paths are turned on


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
    archive: Path | None = None,
    url: str = "",
    sha256: str = "",
    zip_file: Path | None = None,
    client: httpx.Client | None = None,
) -> CheckResult:
    """Unpack the data zip into ``target`` and check it.

    The zip is ``zip_file`` if given; otherwise ``archive``, the zip that comes with the
    repository (whole, or in pieces); otherwise it is downloaded from ``url``. ``target``
    must not exist yet, or be empty: nothing already there is overwritten.
    """
    if target.exists() and any(target.iterdir()):
        raise DataError(
            f"{target} already exists and is not empty; the data is not unpacked over it. "
            "To check the data that is there: gagnvist check-data"
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    for leftover in sorted(target.parent.glob(_WORK_PREFIX + "*")):
        log.warning(
            "note: %s was left by an earlier `gagnvist get-data` that was interrupted; it "
            "can be deleted to free disk space",
            leftover,
        )
    # Work next to the target, so unpacking ends with a quick rename rather than a copy.
    # A clean-up that fails (a file still locked on Windows) must not hide what went wrong:
    # what is left is reported by the next get-data (see above).
    with tempfile.TemporaryDirectory(
        prefix=_WORK_PREFIX, dir=target.parent, ignore_cleanup_errors=True
    ) as work:
        work_dir = Path(work)
        if zip_file is not None:
            source = zip_file
        elif archive is not None and _pieces(archive):
            pieces = _pieces(archive)
            _check_free_space(work_dir, sum(p.stat().st_size for p in pieces), "join the zip")
            source = _join(pieces, work_dir / "data.zip")
        elif archive is not None and archive.is_file():
            source = archive
        else:
            source = _download(url, work_dir / "data.zip", client)
        if sha256:
            _check_checksum(source, sha256)
        unpacked = _unpack(source, work_dir / "unpacked")
        if target.exists():
            target.rmdir()  # empty, as checked above
        move_into_place(unpacked, target)
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


def _pieces(archive: Path) -> list[Path]:
    """The pieces of ``archive`` (archive.part01, .part02, ...), in order; [] if none.

    Raises DataError if a piece is missing in the middle.
    """
    pieces = sorted(archive.parent.glob(archive.name + ".part*"))
    expected = [archive.parent / f"{archive.name}.part{n:02}" for n in range(1, len(pieces) + 1)]
    if pieces != expected:
        names = ", ".join(p.name for p in pieces)
        raise DataError(f"the pieces of {archive.name} are incomplete or misnamed: {names}")
    return pieces


def _join(pieces: list[Path], destination: Path) -> Path:
    """Join the pieces of a zip back into one file."""
    log.info("joining the %s pieces of %s", len(pieces), pieces[0].name.rsplit(".part", 1)[0])
    with destination.open("wb") as joined:
        for piece in pieces:
            with piece.open("rb") as f:
                while chunk := f.read(_CHUNK_SIZE):
                    joined.write(chunk)
    return destination


def _download(url: str, destination: Path, client: httpx.Client | None) -> Path:
    if not url:
        raise DataError(
            "the data zip was not found: it comes with the repository, in data-release/ "
            "(see [data] archive in gagnvist.toml); or pass a zip you have with --zip"
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
            names = z.namelist()
            for name in names:
                parts = PurePosixPath(name).parts
                if not parts or parts[0] != _ZIP_ROOT or ".." in parts or name.startswith("/"):
                    raise DataError(f"{archive.name} contains an unexpected entry: {name!r}")
            if os.name == "nt" and not _long_paths_enabled():
                too_long = too_long_for_windows(destination, names)
                if too_long > 0:
                    raise DataError(
                        f"the folder {destination.parent.parent} is too deep for Windows: some "
                        f"data files would get paths longer than {_WINDOWS_PATH_LIMIT} "
                        f"characters. Clone the starter kit again into a folder whose path "
                        f"is at least {too_long} characters shorter, such as "
                        f"C:\\gagnvist-starter, and set it up there (a folder that is set up "
                        f"cannot simply be moved: its .venv remembers where it was)"
                    )
            _check_free_space(destination.parent, sum(i.file_size for i in z.infolist()), "unpack")
            members = z.infolist()
            for done, member in enumerate(members, 1):
                z.extract(member, destination)
                if done % 1000 == 0 or done == len(members):
                    log.info("  %d of %d files unpacked", done, len(members))
    except zipfile.BadZipFile as e:
        raise DataError(f"{archive.name} is not a valid zip file") from e
    return destination / _ZIP_ROOT


def too_long_for_windows(destination: Path, names: list[str]) -> int:
    """By how many characters the longest unpacked path would exceed Windows' limit
    (0 or less: every path fits)."""
    longest = max((len(str(destination)) + 1 + len(name) for name in names), default=0)
    return longest - _WINDOWS_PATH_LIMIT


def _long_paths_enabled() -> bool:
    """Whether Windows allows long paths (a setting the Python installer offers)."""
    if sys.platform != "win32":
        return False
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\FileSystem"
        ) as key:
            return bool(winreg.QueryValueEx(key, "LongPathsEnabled")[0])
    except OSError:
        return False


def _check_free_space(folder: Path, needed: int, task: str) -> None:
    free = shutil.disk_usage(folder).free
    if free < needed + 200_000_000:  # and a little room to spare
        raise DataError(
            f"not enough free disk space to {task}: {needed / 1e9:.1f} GB are needed, "
            f"{free / 1e9:.1f} GB are free on the disk of {folder}"
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()
