from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from app.usage import parse_usage_event, read_complete_lines


def valid_event() -> dict[str, object]:
    return {
        "request_id": "request_12345678",
        "remote_addr": "203.0.113.9",
        "response_bytes": 1024,
        "status": 206,
        "session_id": str(uuid4()),
        "link_id": str(uuid4()),
        "file_id": str(uuid4()),
        "user_id": str(uuid4()),
        "range": "bytes=100-1123",
    }


def test_usage_event_parser_extracts_bounded_range() -> None:
    event = parse_usage_event(json.dumps(valid_event()))
    assert event is not None
    assert event.response_bytes == 1024
    assert event.range_start == 100
    assert event.range_end == 1123


def test_usage_event_parser_rejects_malformed_or_unattributed_lines() -> None:
    assert parse_usage_event("not-json") is None
    value = valid_event()
    del value["session_id"]
    assert parse_usage_event(json.dumps(value)) is None
    value = valid_event()
    value["response_bytes"] = -1
    assert parse_usage_event(json.dumps(value)) is None


def test_reader_does_not_advance_over_partial_line(tmp_path: Path) -> None:
    path = tmp_path / "access.json"
    path.write_bytes(b'{"first":1}\n{"partial":')
    lines, offset = read_complete_lines(path, 0)
    assert lines == ['{"first":1}\n']
    assert offset == len(b'{"first":1}\n')
