"""Outbound URL guard against server-side request forgery (S3)."""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv4Network, IPv6Address, IPv6Network
from urllib.parse import SplitResult, urlsplit, urlunsplit

from newbot.domain.errors import NetworkAccessDenied

HostResolver = Callable[[str], Awaitable[Sequence[str]]]

_BLOCKED_NETWORKS: tuple[IPv4Network | IPv6Network, ...] = tuple(
    ipaddress.ip_network(entry)
    for entry in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "224.0.0.0/4",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::/128",
        "::1/128",
        "100::/64",
        "2001::/32",
        "2001:db8::/32",
        "2002::/16",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)

_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_LOCAL_HOSTNAMES = ("localhost",)
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


@dataclass(frozen=True, slots=True)
class PinnedTarget:
    """A validated outbound target whose connection address is pinned.

    ``host``/``port`` keep the operator-facing identity (``host`` is the TLS
    SNI name); ``address`` is the validated IP the socket connects to, so a
    second, rebinding resolution cannot redirect the connection.
    """

    url: str
    scheme: str
    host: str
    port: int
    address: str

    @property
    def connect_url(self) -> str:
        """The request URL with the host replaced by the pinned address."""
        parts = urlsplit(self.url)
        address = f"[{self.address}]" if ":" in self.address else self.address
        if self.port != _default_port(self.scheme):
            address = f"{address}:{self.port}"
        return urlunsplit((self.scheme, address, parts.path, parts.query, ""))


class NetworkGuard:
    """Decides whether an outbound HTTP URL may be requested."""

    def __init__(
        self,
        *,
        allowed_cidrs: Iterable[str] = (),
        resolver: HostResolver | None = None,
    ) -> None:
        self._allowed = tuple(
            ipaddress.ip_network(entry, strict=False) for entry in allowed_cidrs
        )
        self._resolve = resolver or _default_resolver

    async def resolve(self, url: str) -> PinnedTarget:
        """Validate ``url`` and return it with the connection address pinned.

        Every resolved address is checked; the first survives as the pinned
        connection address, so the request cannot be re-resolved to a private
        target between validation and connect.
        """
        scheme, host, port = _split(url)
        literal = _as_ip(host)
        if literal is not None:
            self._check(literal, url)
            return PinnedTarget(
                url=url, scheme=scheme, host=host, port=port, address=str(literal)
            )
        if _is_local_name(host):
            raise NetworkAccessDenied(f"blocked local host {host!r} in {url!r}")
        try:
            addresses = await self._resolve(host)
        except OSError as exc:
            raise NetworkAccessDenied(f"cannot resolve {host!r}: {exc}") from exc
        if not addresses:
            raise NetworkAccessDenied(f"cannot resolve {host!r}")
        resolved: list[IPv4Address | IPv6Address] = []
        for raw in addresses:
            address = _as_ip(raw)
            if address is None:
                raise NetworkAccessDenied(f"resolver returned invalid address {raw!r}")
            self._check(address, url)
            resolved.append(address)
        return PinnedTarget(
            url=url, scheme=scheme, host=host, port=port, address=str(resolved[0])
        )

    def _check(self, address: IPv4Address | IPv6Address, url: str) -> None:
        if any(
            address in network
            for network in self._allowed
            if network.version == address.version
        ):
            return
        if _is_blocked(address):
            raise NetworkAccessDenied(f"blocked address {address} in {url!r}")

async def _default_resolver(host: str) -> Sequence[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


def _split(url: str) -> tuple[str, str, int]:
    try:
        parts: SplitResult = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError as exc:
        raise NetworkAccessDenied(f"invalid URL {url!r}: {exc}") from exc
    if parts.scheme not in {"http", "https"}:
        raise NetworkAccessDenied(f"unsupported scheme in {url!r}")
    if not host:
        raise NetworkAccessDenied(f"missing host in {url!r}")
    return parts.scheme, host, port or _default_port(parts.scheme)


def _default_port(scheme: str) -> int:
    return 443 if scheme == "https" else 80


def _as_ip(host: str) -> IPv4Address | IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _is_local_name(host: str) -> bool:
    name = host.rstrip(".").lower()
    return name in _LOCAL_HOSTNAMES or name.endswith(_LOCAL_HOST_SUFFIXES)


def _is_blocked(address: IPv4Address | IPv6Address) -> bool:
    if isinstance(address, IPv6Address):
        mapped = address.ipv4_mapped
        if mapped is not None:
            return _is_blocked(mapped)
        sixtofour = address.sixtofour
        if sixtofour is not None:
            return _is_blocked(sixtofour)
        teredo = address.teredo
        if teredo is not None:
            return any(_is_blocked(part) for part in teredo)
        if address in _NAT64:
            return _is_blocked(IPv4Address(address.packed[-4:]))
    return any(
        address in network
        for network in _BLOCKED_NETWORKS
        if network.version == address.version
    )
