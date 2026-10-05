"""SSRF guard boundary tests with real invalid URLs."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from newbot.domain.errors import NetworkAccessDenied
from newbot.policy.network import HostResolver, NetworkGuard, PinnedTarget

PUBLIC = "93.184.216.34"


def _resolver(*addresses: str) -> HostResolver:
    async def resolve(host: str) -> Sequence[str]:
        return addresses

    return resolve


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/admin",
        "http://192.168.1.10/",
        "http://100.64.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:169.254.169.254]/",
    ],
)
async def test_private_and_metadata_ip_literals_are_blocked(url: str) -> None:
    with pytest.raises(NetworkAccessDenied):
        await NetworkGuard().resolve(url)


@pytest.mark.parametrize(
    "url", ["http://localhost/x", "http://api.local/x", "http://svc.internal/x"]
)
async def test_local_hostnames_are_blocked(url: str) -> None:
    with pytest.raises(NetworkAccessDenied):
        await NetworkGuard(resolver=_resolver(PUBLIC)).resolve(url)


async def test_hostname_resolving_to_a_private_address_is_blocked() -> None:
    with pytest.raises(NetworkAccessDenied):
        await NetworkGuard(resolver=_resolver("10.0.0.7")).resolve(
            "https://evil.example.com/x"
        )


async def test_resolution_failure_fails_closed() -> None:
    async def failing(host: str) -> Sequence[str]:
        raise OSError("dns down")

    with pytest.raises(NetworkAccessDenied):
        await NetworkGuard(resolver=failing).resolve("https://example.com/")


@pytest.mark.parametrize(
    "url", ["file:///etc/passwd", "http:///nohost", "ftp://example.com/x"]
)
async def test_non_http_or_hostless_urls_are_rejected(url: str) -> None:
    with pytest.raises(NetworkAccessDenied):
        await NetworkGuard().resolve(url)


@pytest.mark.parametrize(
    "url", ["http://[::1/", "http://example.com:99999/", "http://example.com:abc/"]
)
async def test_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises(NetworkAccessDenied):
        await NetworkGuard(resolver=_resolver(PUBLIC)).resolve(url)


async def test_public_targets_are_allowed() -> None:
    await NetworkGuard(resolver=_resolver(PUBLIC)).resolve(
        "https://example.com/path?q=1"
    )
    await NetworkGuard().resolve(f"http://{PUBLIC}/")


async def test_explicit_whitelist_opens_a_private_target() -> None:
    await NetworkGuard(allowed_cidrs=["10.0.0.0/8"]).resolve("http://10.0.0.1/admin")


async def test_resolve_pins_the_validated_address() -> None:
    target = await NetworkGuard(resolver=_resolver(PUBLIC)).resolve(
        "https://example.com:8443/path?q=1"
    )

    assert target == PinnedTarget(
        url="https://example.com:8443/path?q=1",
        scheme="https",
        host="example.com",
        port=8443,
        address=PUBLIC,
    )
    assert target.connect_url == f"https://{PUBLIC}:8443/path?q=1"


async def test_resolve_pins_an_ip_literal() -> None:
    target = await NetworkGuard().resolve(f"http://{PUBLIC}/x")

    assert target.address == PUBLIC
    assert target.connect_url == f"http://{PUBLIC}/x"


async def test_ipv6_literal_connect_url_is_bracketed() -> None:
    target = await NetworkGuard().resolve("http://[2001:4860:4860::8888]/dns")

    assert target.host == "2001:4860:4860::8888"
    assert target.connect_url == "http://[2001:4860:4860::8888]/dns"
