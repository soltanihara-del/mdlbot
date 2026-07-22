"""Strict reads for Docker Secret and permission-restricted credential files."""

from __future__ import annotations

import os
from pathlib import Path
import stat

from app.core.errors import SecretFileError


MAX_SECRET_BYTES = 16 * 1024


def read_secret_file(
    path: str | Path,
    *,
    minimum_length: int = 1,
    maximum_bytes: int = MAX_SECRET_BYTES,
) -> str:
    """Read one UTF-8 secret without following symlinks or exposing its value."""

    secret_path = Path(path)
    try:
        file_stat = secret_path.lstat()
    except OSError as exc:
        raise SecretFileError(
            "secret file is unavailable", context={"path": str(secret_path)}
        ) from exc

    if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
        raise SecretFileError(
            "secret path must be a regular non-symlink file",
            context={"path": str(secret_path)},
        )
    if file_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise SecretFileError(
            "secret file must not be group/world writable",
            context={"path": str(secret_path)},
        )
    if file_stat.st_size > maximum_bytes:
        raise SecretFileError(
            "secret file exceeds the size limit", context={"path": str(secret_path)}
        )

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(secret_path, flags)
        try:
            raw = os.read(descriptor, maximum_bytes + 1)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise SecretFileError(
            "secret file could not be read safely", context={"path": str(secret_path)}
        ) from exc

    if len(raw) > maximum_bytes:
        raise SecretFileError(
            "secret file exceeds the size limit", context={"path": str(secret_path)}
        )
    try:
        value = raw.decode("utf-8").strip("\r\n")
    except UnicodeDecodeError as exc:
        raise SecretFileError(
            "secret file is not valid UTF-8", context={"path": str(secret_path)}
        ) from exc
    if "\x00" in value or len(value) < minimum_length:
        raise SecretFileError(
            "secret value is empty or malformed", context={"path": str(secret_path)}
        )
    return value
