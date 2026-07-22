from __future__ import annotations

import pytest

from app.core.errors import UnsafeUrl
from app.services.url_policy import is_forbidden_ip, normalize_external_url


def test_normalizes_public_http_urls_and_idna() -> None:
    normalized = normalize_external_url(" HTTPS://BÜCHER.example./a file?q=1 ")
    assert normalized.url == "https://xn--bcher-kva.example/a%20file?q=1"
    assert normalized.hostname == "xn--bcher-kva.example"
    assert normalized.port == 443


@pytest.mark.parametrize(
    "value",
    (
        "ftp://example.com/file",
        "https://user:secret@example.com/file",
        "https://example.com/file#fragment",
        "http://127.0.0.1/file",
        "http://169.254.169.254/latest/meta-data",
        "http://2130706433/file",
        "http://0x7f000001/file",
        "https://example.com:22/file",
    ),
)
def test_rejects_unsafe_or_ambiguous_urls(value: str) -> None:
    with pytest.raises(UnsafeUrl):
        normalize_external_url(value)


@pytest.mark.parametrize(
    ("address", "forbidden"),
    (
        ("127.0.0.1", True),
        ("10.0.0.1", True),
        ("100.64.0.1", True),
        ("169.254.169.254", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("1.1.1.1", False),
        ("2606:4700:4700::1111", False),
    ),
)
def test_forbidden_ip_classification(address: str, forbidden: bool) -> None:
    assert is_forbidden_ip(address) is forbidden
