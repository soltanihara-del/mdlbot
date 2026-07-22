"""Canonical URL intake validation before isolated-worker DNS pinning."""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import re
from urllib.parse import quote, unquote, urlsplit, urlunsplit

from app.core.errors import UnsafeUrl


CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
AMBIGUOUS_IPV4_RE = re.compile(r"^(?:0x[0-9a-f]+|0[0-7]+|\d+)$", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class NormalizedUrl:
    url: str
    scheme: str
    hostname: str
    port: int


def is_forbidden_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return True
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(
        (
            address.is_private,
            address.is_loopback,
            address.is_link_local,
            address.is_multicast,
            address.is_reserved,
            address.is_unspecified,
            not address.is_global,
        )
    )


def normalize_external_url(raw: str) -> NormalizedUrl:
    value = raw.strip()
    if not value or len(value) > 4096 or CONTROL_RE.search(value):
        raise UnsafeUrl("URL is empty, oversized, or contains control characters")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise UnsafeUrl("URL structure or port is invalid") from exc
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise UnsafeUrl("only HTTP and HTTPS URLs are accepted")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrl("URL credentials are not accepted")
    if parsed.fragment:
        raise UnsafeUrl("URL fragments are not accepted")
    if not parsed.hostname:
        raise UnsafeUrl("URL hostname is required")
    try:
        hostname = parsed.hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UnsafeUrl("URL hostname cannot be normalized") from exc
    if not hostname or len(hostname) > 253 or ".." in hostname:
        raise UnsafeUrl("URL hostname is invalid")
    if port is None:
        port = 443 if scheme == "https" else 80
    if port not in {80, 443}:
        raise UnsafeUrl("URL port is not allowed", context={"port": port})
    literal_address = None
    try:
        literal_address = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        if AMBIGUOUS_IPV4_RE.fullmatch(hostname) or hostname.replace(".", "").isdigit():
            raise UnsafeUrl("ambiguous numeric hostname is not accepted")
    else:
        if is_forbidden_ip(hostname.strip("[]")):
            raise UnsafeUrl("literal destination address is forbidden")
    decoded_path = unquote(parsed.path, errors="strict")
    if CONTROL_RE.search(decoded_path):
        raise UnsafeUrl("URL path contains control characters")
    path = quote(decoded_path or "/", safe="/%:@!$&'()*+,;=-._~")
    host_for_url = f"[{hostname}]" if isinstance(literal_address, ipaddress.IPv6Address) else hostname
    default_port = 443 if scheme == "https" else 80
    netloc = host_for_url if port == default_port else f"{host_for_url}:{port}"
    normalized = urlunsplit((scheme, netloc, path, parsed.query, ""))
    return NormalizedUrl(normalized, scheme, hostname, port)
