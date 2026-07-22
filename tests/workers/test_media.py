from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import RuntimeSettings
from app.workers.client import WorkerFailure
from app.workers.media import MediaProcessor


def processor(tmp_path: Path) -> MediaProcessor:
    objects = tmp_path / "objects"
    media = tmp_path / "media"
    hls = tmp_path / "hls"
    for path in (objects, media, hls):
        path.mkdir()
    return MediaProcessor(
        RuntimeSettings(
            app_env="test",
            storage_root=objects,
            media_root=media,
            hls_root=hls,
        )
    )


def test_media_metadata_is_bounded_and_drops_untrusted_tags(tmp_path: Path) -> None:
    value = processor(tmp_path)._metadata(
        {
            "format": {
                "format_name": "matroska,webm",
                "duration": "12.5",
                "tags": {"comment": "untrusted"},
            },
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080},
                {"codec_type": "audio", "codec_name": "aac", "channels": 2, "tags": {"title": "x"}},
            ],
        }
    )
    assert value["media_kind"] == "video"
    assert value["duration_ms"] == 12_500
    assert value["streams"][0]["codec"] == "h264"
    assert "tags" not in value and "tags" not in value["streams"][1]


def test_media_source_must_remain_beneath_object_root(tmp_path: Path) -> None:
    with pytest.raises(WorkerFailure, match="media_source_path_invalid"):
        processor(tmp_path)._managed_source("../outside")


def test_direct_play_requires_a_browser_compatible_container_and_codecs(tmp_path: Path) -> None:
    media = processor(tmp_path)
    compatible = {
        "streams": [
            {"type": "video", "codec": "h264"},
            {"type": "audio", "codec": "aac"},
        ]
    }
    assert media._direct_play(compatible, "video/mp4") is True
    compatible["streams"].append({"type": "subtitle", "codec": "ass"})
    assert media._direct_play(compatible, "video/mp4") is False


def test_hls_playlist_parser_rejects_invalid_duration(tmp_path: Path) -> None:
    playlist = tmp_path / "index.m3u8"
    playlist.write_text("#EXTM3U\n#EXTINF:not-a-number,\nsegment.ts\n", encoding="utf-8")
    with pytest.raises(WorkerFailure, match="media_hls_invalid"):
        MediaProcessor._playlist_durations(playlist)
