from __future__ import annotations

from pathlib import Path

import pytest

from app.workers.downloads import PinnedResolver, safe_filename, sniff_mime


def test_safe_filename_removes_paths_and_control_characters() -> None:
    assert safe_filename(" ../bad/\x00name.pdf ") == "_bad_name.pdf"
    assert safe_filename("... ") == "download.bin"


@pytest.mark.parametrize(
    ("prefix", "expected"),
    (
        (b"\x89PNG\r\n\x1a\nrest", "image/png"),
        (b"%PDF-1.7 rest", "application/pdf"),
        (b"\x00\x00\x00\x18ftypisomrest", "video/mp4"),
        (b"unknown", "application/octet-stream"),
    ),
)
def test_mime_sniffing_uses_content(tmp_path: Path, prefix: bytes, expected: str) -> None:
    target = tmp_path / "misleading.exe"
    target.write_bytes(prefix)
    assert sniff_mime(target, target.name) == expected


@pytest.mark.asyncio
async def test_pinned_resolver_cannot_resolve_another_hostname() -> None:
    resolver = PinnedResolver("example.com", ["1.1.1.1"])
    with pytest.raises(OSError, match="hostname mismatch"):
        await resolver.resolve("internal.example", 443)
