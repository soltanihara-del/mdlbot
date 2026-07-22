"""Sandbox-friendly FFprobe, remux/transcode, and HLS media processor."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any
from uuid import uuid4

from app.core.config import RuntimeSettings
from app.workers.client import MediaWorkerResult, ProgressCallback, WorkerFailure


MAX_PROBE_OUTPUT = 1024 * 1024
SAFE_CODEC = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


class MediaProcessor:
    """Process one immutable object without database, Redis, or bot credentials."""

    def __init__(self, settings: RuntimeSettings) -> None:
        self._objects = settings.storage_root.resolve()
        self._media = settings.media_root.resolve()
        self._hls = settings.hls_root.resolve()

    async def __call__(
        self,
        job: dict[str, Any],
        progress: ProgressCallback,
    ) -> MediaWorkerResult:
        payload = job["payload"]
        policy = job["policy"]
        source = self._managed_source(str(payload["storage_key"]))
        source_stat = source.stat()
        if source_stat.st_size != int(payload["size_bytes"]):
            raise WorkerFailure("media_source_size_mismatch")
        await progress({"stage": "probing", "percent": 1, "bytes": 0})
        probe = await self._probe(source, int(policy.get("media_probe_timeout", 30)))
        metadata = self._metadata(probe)
        media_kind = metadata.get("media_kind")
        if media_kind not in {"video", "audio"}:
            raise WorkerFailure("media_stream_not_found")
        direct = self._direct_play(metadata, str(payload.get("detected_mime", "")))
        timeout = int(policy.get("media_process_timeout", 3600))
        job_id = str(job["job_id"])
        variants: list[dict[str, Any]] = []

        if not direct:
            if not bool(policy.get("media_transcode_enabled", True)):
                raise WorkerFailure("media_transcode_disabled")
            await progress({"stage": "transcoding", "percent": 10, "bytes": 0})
            compatible_codecs = self._copy_compatible(metadata)
            kind = "remux" if compatible_codecs else "transcode"
            variant = await self._make_progressive(
                source,
                job_id=job_id,
                media_kind=str(media_kind),
                kind=kind,
                copy_codecs=compatible_codecs,
                timeout=timeout,
            )
            variants.append(variant)

        if bool(policy.get("media_hls_enabled", True)):
            await progress({"stage": "segmenting", "percent": 60, "bytes": 0})
            hls = await self._make_hls(
                source,
                job_id=job_id,
                media_kind=str(media_kind),
                segment_seconds=int(policy.get("media_hls_segment_seconds", 6)),
                timeout=timeout,
            )
            variants.append(hls)

        await progress(
            {"stage": "media_ready", "percent": 100, "bytes": source_stat.st_size}
        )
        return MediaWorkerResult(
            kind="media",
            size_bytes=source_stat.st_size,
            direct_play_compatible=direct,
            metadata=metadata,
            variants=variants,
        )

    def _managed_source(self, key: str) -> Path:
        relative = PurePosixPath(key)
        if relative.is_absolute() or ".." in relative.parts:
            raise WorkerFailure("media_source_path_invalid")
        source = self._objects.joinpath(*relative.parts)
        try:
            resolved = source.resolve(strict=True)
            resolved.relative_to(self._objects)
            source_stat = source.lstat()
        except (OSError, ValueError) as exc:
            raise WorkerFailure("media_source_path_invalid") from exc
        if source.is_symlink() or not stat.S_ISREG(source_stat.st_mode):
            raise WorkerFailure("media_source_path_invalid")
        return resolved

    async def _probe(self, source: Path, timeout: int) -> dict[str, Any]:
        stdout = await self._run(
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(source),
            timeout=timeout,
            output_limit=MAX_PROBE_OUTPUT,
        )
        try:
            value = json.loads(stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkerFailure("media_probe_invalid") from exc
        if not isinstance(value, dict):
            raise WorkerFailure("media_probe_invalid")
        return value

    @staticmethod
    def _metadata(probe: dict[str, Any]) -> dict[str, Any]:
        streams = probe.get("streams")
        if not isinstance(streams, list):
            streams = []
        sanitized: list[dict[str, Any]] = []
        media_kind = None
        duration_ms = 0
        for stream in streams[:32]:
            if not isinstance(stream, dict):
                continue
            codec_type = str(stream.get("codec_type", ""))
            codec = str(stream.get("codec_name", ""))
            if codec_type not in {"video", "audio", "subtitle"} or not SAFE_CODEC.fullmatch(codec):
                continue
            item: dict[str, Any] = {"type": codec_type, "codec": codec}
            for key in ("width", "height", "sample_rate", "channels", "bit_rate"):
                try:
                    number = int(stream[key])
                except (KeyError, TypeError, ValueError):
                    continue
                if 0 < number <= 10_000_000_000:
                    item[key] = number
            sanitized.append(item)
            if codec_type == "video":
                media_kind = "video"
            elif codec_type == "audio" and media_kind is None:
                media_kind = "audio"
            try:
                duration_ms = max(duration_ms, int(float(stream.get("duration", 0)) * 1000))
            except (TypeError, ValueError, OverflowError):
                pass
        format_value = probe.get("format") if isinstance(probe.get("format"), dict) else {}
        try:
            duration_ms = max(duration_ms, int(float(format_value.get("duration", 0)) * 1000))
        except (TypeError, ValueError, OverflowError):
            pass
        names = [
            name
            for name in str(format_value.get("format_name", "")).split(",")[:8]
            if SAFE_CODEC.fullmatch(name)
        ]
        return {
            "media_kind": media_kind,
            "duration_ms": max(0, min(duration_ms, 31_536_000_000)),
            "formats": names,
            "streams": sanitized,
        }

    @staticmethod
    def _direct_play(metadata: dict[str, Any], mime: str) -> bool:
        codecs = {stream["codec"] for stream in metadata["streams"]}
        if mime == "video/mp4":
            return bool(codecs & {"h264", "hevc"}) and not bool(
                codecs - {"h264", "hevc", "aac", "mp3", "mov_text"}
            )
        if mime in {"audio/mpeg", "audio/ogg"}:
            return not bool(codecs - {"mp3", "aac", "opus", "vorbis"})
        if mime == "video/webm":
            return not bool(codecs - {"vp8", "vp9", "av1", "opus", "vorbis"})
        return False

    @staticmethod
    def _copy_compatible(metadata: dict[str, Any]) -> bool:
        codecs = {stream["codec"] for stream in metadata["streams"]}
        return bool(codecs) and not bool(codecs - {"h264", "hevc", "aac", "mp3"})

    async def _make_progressive(
        self,
        source: Path,
        *,
        job_id: str,
        media_kind: str,
        kind: str,
        copy_codecs: bool,
        timeout: int,
    ) -> dict[str, Any]:
        output_id = uuid4().hex
        relative = Path(job_id) / f"{output_id}.mp4"
        final = self._media / relative
        temporary = self._media / ".incoming" / job_id / f"{output_id}.part"
        temporary.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        args = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-map_metadata", "-1"]
        if media_kind == "video":
            args.extend(["-map", "0:v:0", "-map", "0:a:0?"])
        else:
            args.extend(["-map", "0:a:0", "-vn"])
        if copy_codecs:
            args.extend(["-c", "copy"])
        elif media_kind == "video":
            args.extend(["-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-b:a", "160k"])
        else:
            args.extend(["-c:a", "aac", "-b:a", "192k"])
        args.extend(["-movflags", "+faststart", "-f", "mp4", str(temporary)])
        try:
            await self._run(*args, timeout=timeout, output_limit=64 * 1024)
            os.replace(temporary, final)
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
        return {
            "kind": kind,
            "quality": "source",
            "storage_key": relative.as_posix(),
            "mime_type": "video/mp4" if media_kind == "video" else "audio/mp4",
            "size_bytes": final.stat().st_size,
            "metadata": {"media_kind": media_kind},
            "segments": [],
        }

    async def _make_hls(
        self,
        source: Path,
        *,
        job_id: str,
        media_kind: str,
        segment_seconds: int,
        timeout: int,
    ) -> dict[str, Any]:
        output_id = uuid4().hex
        temporary = self._hls / ".incoming" / job_id / output_id
        final = self._hls / job_id / output_id
        temporary.mkdir(parents=True, exist_ok=False, mode=0o700)
        final.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        playlist = temporary / "index.m3u8"
        segment_pattern = temporary / "segment-%06d.ts"
        args = ["ffmpeg", "-nostdin", "-v", "error", "-i", str(source), "-map_metadata", "-1"]
        if media_kind == "video":
            args.extend(
                ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac"]
            )
        else:
            args.extend(["-map", "0:a:0", "-vn", "-c:a", "aac", "-b:a", "160k"])
        args.extend(
            [
                "-f",
                "hls",
                "-hls_time",
                str(max(2, min(20, segment_seconds))),
                "-hls_playlist_type",
                "vod",
                "-hls_segment_filename",
                str(segment_pattern),
                str(playlist),
            ]
        )
        try:
            await self._run(*args, timeout=timeout, output_limit=64 * 1024)
            durations = self._playlist_durations(playlist)
            files = sorted(temporary.glob("segment-*.ts"))
            if not files or len(files) != len(durations):
                raise WorkerFailure("media_hls_invalid")
            os.replace(temporary, final)
        except BaseException:
            for child in temporary.glob("*") if temporary.exists() else ():
                child.unlink(missing_ok=True)
            try:
                temporary.rmdir()
            except OSError:
                pass
            raise
        segments = []
        for sequence, (path, duration_ms) in enumerate(zip(sorted(final.glob("segment-*.ts")), durations)):
            segments.append(
                {
                    "sequence_number": sequence,
                    "storage_key": (Path(job_id) / output_id / path.name).as_posix(),
                    "size_bytes": path.stat().st_size,
                    "duration_ms": duration_ms,
                }
            )
        return {
            "kind": "hls",
            "quality": "source",
            "storage_key": (Path(job_id) / output_id / "index.m3u8").as_posix(),
            "mime_type": "application/vnd.apple.mpegurl",
            "size_bytes": sum(segment["size_bytes"] for segment in segments),
            "metadata": {"media_kind": media_kind, "segment_count": len(segments)},
            "segments": segments,
        }

    @staticmethod
    def _playlist_durations(path: Path) -> list[int]:
        values: list[int] = []
        try:
            lines = path.read_text(encoding="utf-8", errors="strict").splitlines()
        except (OSError, UnicodeError) as exc:
            raise WorkerFailure("media_hls_invalid") from exc
        for line in lines:
            if not line.startswith("#EXTINF:"):
                continue
            try:
                duration = float(line.removeprefix("#EXTINF:").split(",", 1)[0])
            except (ValueError, OverflowError) as exc:
                raise WorkerFailure("media_hls_invalid") from exc
            values.append(max(1, min(120_000, int(duration * 1000))))
        return values

    @staticmethod
    async def _run(
        *args: str,
        timeout: int,
        output_limit: int,
    ) -> bytes:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        except TimeoutError as exc:
            if "process" in locals():
                process.kill()
                await process.wait()
            raise WorkerFailure("media_process_timeout") from exc
        except OSError as exc:
            raise WorkerFailure("media_tool_unavailable") from exc
        if len(stdout) > output_limit or len(stderr) > output_limit:
            raise WorkerFailure("media_tool_output_limit")
        if process.returncode != 0:
            raise WorkerFailure("media_process_failed")
        return stdout
