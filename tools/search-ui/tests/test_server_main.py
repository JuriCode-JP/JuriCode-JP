"""Tests for server._check_host (Phase E, FU-414 / R5).

Why this test exists:
    The search-ui records query text, so binding to a non-loopback host without an
    explicit opt-in must be refused (fail-fast). Pins loopback allow-list incl. IPv6
    (::1 ok, :: blocked) and the --allow-external opt-in.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SEARCH_UI = Path(__file__).resolve().parents[1]
if str(_SEARCH_UI) not in sys.path:
    sys.path.insert(0, str(_SEARCH_UI))

import server  # noqa: E402


def test_loopback_ipv4_ok() -> None:
    assert server._check_host("127.0.0.1", False) is False


def test_localhost_ok() -> None:
    assert server._check_host("localhost", False) is False


def test_loopback_ipv6_ok() -> None:
    assert server._check_host("::1", False) is False


def test_zero_host_without_flag_raises() -> None:
    with pytest.raises(ValueError):
        server._check_host("0.0.0.0", False)


def test_lan_ip_without_flag_raises() -> None:
    with pytest.raises(ValueError):
        server._check_host("192.168.1.5", False)


def test_ipv6_all_without_flag_raises() -> None:
    with pytest.raises(ValueError):
        server._check_host("::", False)


def test_zero_host_with_flag_is_external() -> None:
    assert server._check_host("0.0.0.0", True) is True


def test_loopback_with_flag_not_external() -> None:
    assert server._check_host("127.0.0.1", True) is False
