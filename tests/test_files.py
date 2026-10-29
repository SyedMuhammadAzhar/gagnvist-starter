"""Moving finished files into place, also when Windows holds them locked for a moment."""

import os
from pathlib import Path

import pytest

from gagnvist import files


def test_a_locked_file_is_moved_once_it_is_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "new", tmp_path / "old"
    source.write_text("new", encoding="utf-8")
    target.write_text("old", encoding="utf-8")
    calls = []
    real_replace = os.replace

    def locked_twice(a: Path, b: Path) -> None:
        calls.append(a)
        if len(calls) <= 2:
            raise PermissionError("[WinError 5] Access is denied")
        real_replace(a, b)

    monkeypatch.setattr(files, "WINDOWS", True)
    monkeypatch.setattr(files, "PAUSE", 0)
    monkeypatch.setattr(files.os, "replace", locked_twice)
    files.move_into_place(source, target)
    assert len(calls) == 3
    assert target.read_text(encoding="utf-8") == "new"


def test_a_file_that_stays_locked_is_reported(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def locked(a: Path, b: Path) -> None:
        raise PermissionError("[WinError 5] Access is denied")

    monkeypatch.setattr(files, "WINDOWS", True)
    monkeypatch.setattr(files, "PAUSE", 0)
    monkeypatch.setattr(files.os, "replace", locked)
    with pytest.raises(PermissionError):
        files.move_into_place(tmp_path / "a", tmp_path / "b")


def test_elsewhere_a_permission_error_is_reported_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def locked(a: Path, b: Path) -> None:
        calls.append(a)
        raise PermissionError("not allowed")

    monkeypatch.setattr(files, "WINDOWS", False)
    monkeypatch.setattr(files.os, "replace", locked)
    with pytest.raises(PermissionError):
        files.move_into_place(tmp_path / "a", tmp_path / "b")
    assert len(calls) == 1


def test_a_folder_is_moved_into_place(tmp_path: Path) -> None:
    source = tmp_path / "unpacked"
    (source / "sub").mkdir(parents=True)
    (source / "sub" / "f.txt").write_text("x", encoding="utf-8")
    files.move_into_place(source, tmp_path / "data")
    assert (tmp_path / "data" / "sub" / "f.txt").read_text(encoding="utf-8") == "x"
