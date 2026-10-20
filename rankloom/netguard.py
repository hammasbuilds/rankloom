"""Fetching a URL a user typed, without letting them aim the server at itself.

A site audit fetches arbitrary URLs, which is the textbook route to server-side request forgery:
`http://127.0.0.1:8000/`, a cloud metadata address, or a public name that resolves to a private
one. Each hop of a redirect chain is checked, every resolved address must be public, and the
socket is connected to the address that was checked - not re-resolved - so a name cannot pass
the check and then point somewhere else when the connection is made.
"""

from __future__ import annotations

import gzip
import http.client
import io
import ipaddress
import socket
import ssl
import time
import zlib
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

USER_AGENT = "RankloomBot/0.1 (+https://github.com/hammasbuilds/rankloom)"
ALLOWED_PORTS = {80, 443}


class FetchRefused(Exception):
    """The URL was refused before any connection was made."""


class FetchFailed(Exception):
    """The connection or the response failed."""


@dataclass
class Response:
    url: str
    status: int
    headers: dict[str, str]
    body: bytes
    elapsed_ms: int
    chain: list[tuple[int, str]] = field(default_factory=list)
    truncated: bool = False

    def text(self) -> str:
        charset = "utf-8"
        ctype = self.headers.get("content-type", "")
        if "charset=" in ctype:
            charset = ctype.split("charset=")[-1].split(";")[0].strip() or "utf-8"
        try:
            return self.body.decode(charset, errors="replace")
        except LookupError:
            return self.body.decode("utf-8", errors="replace")


def is_public_address(addr: str) -> bool:
    ip = ipaddress.ip_address(addr.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def check_url(url: str) -> tuple[str, str, int, str]:
    """(scheme, host, port, path) for a URL we are willing to fetch, else FetchRefused."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchRefused("Only http and https addresses can be audited.")
    if not parts.hostname:
        raise FetchRefused("That address has no host name.")
    if parts.username or parts.password:
        raise FetchRefused("Addresses with a user name or password in them are refused.")
    port = parts.port or (443 if parts.scheme == "https" else 80)
    if port not in ALLOWED_PORTS:
        raise FetchRefused("Only the standard web ports (80 and 443) can be audited.")
    host = parts.hostname.rstrip(".").lower()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise FetchRefused("Local addresses cannot be audited.")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parts.scheme, host, port, path


def resolve_public(host: str, port: int) -> str:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchFailed(f"The name {host} does not resolve.") from exc
    addrs = [info[4][0] for info in infos]
    if not addrs:
        raise FetchFailed(f"The name {host} does not resolve.")
    blocked = [a for a in addrs if not is_public_address(a)]
    if blocked:
        raise FetchRefused(f"{host} resolves to a private or reserved address.")
    return addrs[0]


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._ip, self.port), self.timeout)


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        self._ctx = ssl.create_default_context()
        super().__init__(host, port, timeout=timeout, context=self._ctx)
        self._ip = ip

    def connect(self) -> None:
        sock = socket.create_connection((self._ip, self.port), self.timeout)
        self.sock = self._ctx.wrap_socket(sock, server_hostname=self.host)


def safe_fetch(
    url: str, *, max_bytes: int = 3_000_000, timeout: float = 15.0, max_redirects: int = 5
) -> Response:
    chain: list[tuple[int, str]] = []
    started = time.monotonic()
    current = url
    for _ in range(max_redirects + 1):
        scheme, host, port, path = check_url(current)
        ip = resolve_public(host, port)
        cls = _PinnedHTTPS if scheme == "https" else _PinnedHTTP
        conn = cls(host, ip, port, timeout)
        try:
            conn.request(
                "GET",
                path,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                    "Accept-Encoding": "gzip, deflate",
                    "Host": host if port in (80, 443) else f"{host}:{port}",
                },
            )
            resp = conn.getresponse()
            headers = {k.lower(): v for k, v in resp.getheaders()}
            if resp.status in (301, 302, 303, 307, 308) and "location" in headers:
                chain.append((resp.status, current))
                current = urljoin(current, headers["location"])
                resp.read(65536)
                continue
            raw = resp.read(max_bytes + 1)
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise FetchFailed(f"Could not fetch {current}: {exc}") from exc
        finally:
            conn.close()
        truncated = len(raw) > max_bytes
        raw = raw[:max_bytes]
        body = _decode(raw, headers.get("content-encoding", ""), max_bytes)
        return Response(
            url=current,
            status=resp.status,
            headers=headers,
            body=body,
            elapsed_ms=int((time.monotonic() - started) * 1000),
            chain=chain,
            truncated=truncated,
        )
    raise FetchFailed(f"More than {max_redirects} redirects starting from {url}.")


def _decode(raw: bytes, encoding: str, limit: int) -> bytes:
    encoding = encoding.lower().strip()
    try:
        if encoding == "gzip":
            return gzip.GzipFile(fileobj=io.BytesIO(raw)).read(limit * 4)
        if encoding == "deflate":
            try:
                return zlib.decompressobj().decompress(raw, limit * 4)
            except zlib.error:
                return zlib.decompressobj(-zlib.MAX_WBITS).decompress(raw, limit * 4)
    except (OSError, EOFError, zlib.error):
        return raw
    return raw
