from app.bot.progress import human_bytes


def test_human_bytes_has_stable_binary_units() -> None:
    assert human_bytes(0) == "0 B"
    assert human_bytes(1536) == "1.5 KiB"
    assert human_bytes(5 * 1024**3) == "5.0 GiB"
