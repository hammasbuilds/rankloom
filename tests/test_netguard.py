import socket

import pytest

from rankloom import netguard
from rankloom.netguard import FetchRefused, check_url, is_public_address, resolve_public


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/",
        "http://localhost/",
        "http://admin.localhost/",
        "http://printer.local/",
        "http://example.com:22/",
        "http://user:pw@example.com/",
        "http://",
    ],
)
def test_refused_before_any_lookup(url):
    with pytest.raises(FetchRefused):
        check_url(url)


@pytest.mark.parametrize(
    ("addr", "public"),
    [
        ("8.8.8.8", True),
        ("127.0.0.1", False),
        ("10.1.2.3", False),
        ("192.168.0.10", False),
        ("172.16.5.5", False),
        ("169.254.169.254", False),  # cloud metadata
        ("100.64.0.1", False),  # carrier-grade NAT
        ("0.0.0.0", False),
        ("::1", False),
        ("fe80::1", False),
        ("::ffff:127.0.0.1", False),  # IPv4-mapped loopback
        ("2606:4700:4700::1111", True),
        ("224.0.0.1", False),
    ],
)
def test_public_address_classification(addr, public):
    assert is_public_address(addr) is public


def test_a_public_name_that_resolves_to_a_private_address_is_refused(monkeypatch):
    def fake(host, port, type=0):  # noqa: A002 - mirrors socket.getaddrinfo
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    with pytest.raises(FetchRefused):
        resolve_public("innocent.example.com", 443)


def test_any_private_address_among_several_is_refused(monkeypatch):
    def fake(host, port, type=0):  # noqa: A002
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)
    with pytest.raises(FetchRefused):
        resolve_public("mixed.example.com", 80)


def test_redirect_to_a_private_address_is_refused_at_the_hop(monkeypatch):
    """The first hop is public; the redirect it sends must be checked again, not followed."""
    looked_up = []

    def fake_resolve(host, port):
        looked_up.append(host)
        if host != "public.example.com":
            raise FetchRefused("private")
        return "93.184.216.34"

    monkeypatch.setattr(netguard, "resolve_public", fake_resolve)

    class FakeResp:
        status = 302

        def getheaders(self):
            return [("Location", "http://internal.example.com/admin")]

        def read(self, n=-1):
            return b""

    class FakeConn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            pass

        def getresponse(self):
            return FakeResp()

        def close(self):
            pass

    monkeypatch.setattr(netguard, "_PinnedHTTP", FakeConn)
    with pytest.raises(FetchRefused):
        netguard.safe_fetch("http://public.example.com/")
    assert looked_up == ["public.example.com", "internal.example.com"]
