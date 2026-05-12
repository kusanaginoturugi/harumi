from __future__ import annotations

import fnmatch
from pathlib import Path
from dataclasses import dataclass
from pathlib import PurePosixPath


IGNORED_DIR_NAMES = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    ".cache",
    "__pycache__",
    "dist",
    "build",
}

IGNORED_FILE_NAMES = {
    ".DS_Store",
    "Thumbs.db",
    ".harumiignore",
}


@dataclass(frozen=True)
class IgnorePattern:
    value: str
    anchored: bool
    directory_only: bool


@dataclass(frozen=True)
class IgnoreMatcher:
    root_path: Path
    patterns: tuple[IgnorePattern, ...]


def load_ignore_matcher(root_path: Path) -> IgnoreMatcher:
    ignore_file = root_path / ".harumiignore"
    patterns: list[IgnorePattern] = []
    if ignore_file.exists():
        try:
            for raw_line in ignore_file.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                directory_only = line.endswith("/")
                if directory_only:
                    line = line[:-1]
                anchored = line.startswith("/")
                if anchored:
                    line = line[1:]
                if not line:
                    continue
                patterns.append(
                    IgnorePattern(
                        value=line,
                        anchored=anchored,
                        directory_only=directory_only,
                    )
                )
        except OSError:
            pass
    return IgnoreMatcher(root_path=root_path, patterns=tuple(patterns))


def _relative_posix(path: Path, root_path: Path) -> str | None:
    try:
        return path.resolve().relative_to(root_path.resolve()).as_posix()
    except ValueError:
        return None


def _pattern_matches(
    pattern: IgnorePattern,
    *,
    relative_path: str,
    name: str,
    is_directory: bool,
) -> bool:
    if pattern.directory_only:
        prefix = pattern.value.rstrip("/")
        if relative_path == prefix or relative_path.startswith(prefix + "/"):
            return True
        if pattern.anchored:
            return False
        for part in PurePosixPath(relative_path).parts:
            if fnmatch.fnmatch(part, prefix):
                return True
        return False

    if "/" not in pattern.value:
        return fnmatch.fnmatch(name, pattern.value)

    rel = PurePosixPath(relative_path)
    if pattern.anchored:
        return rel.match(pattern.value)
    return rel.match(pattern.value) or rel.match(f"**/{pattern.value}")


def _is_ignored_by_matcher(path: Path, matcher: IgnoreMatcher, *, is_directory: bool) -> bool:
    relative_path = _relative_posix(path, matcher.root_path)
    if relative_path is None or relative_path == ".":
        return False
    for pattern in matcher.patterns:
        if _pattern_matches(
            pattern,
            relative_path=relative_path,
            name=path.name,
            is_directory=is_directory,
        ):
            return True
    return False


def is_ignored_directory(path: Path, matcher: IgnoreMatcher | None = None) -> bool:
    if path.name in IGNORED_DIR_NAMES:
        return True
    if matcher is None:
        return False
    return _is_ignored_by_matcher(path, matcher, is_directory=True)


def is_ignored_file(path: Path, matcher: IgnoreMatcher | None = None) -> bool:
    if path.name in IGNORED_FILE_NAMES:
        return True
    if matcher is None:
        return False
    return _is_ignored_by_matcher(path, matcher, is_directory=False)
