"""fetch-egov の基本テスト.

ライブ API は叩かない. すべて httpx の ASGI トランスポート or respx でモック化.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import httpx
import pytest

from fetch_egov.cache import FileCache
from fetch_egov.client import EGovClient
from fetch_egov.law_id_map import LAW_ID_MAP, resolve_law_id

# ---- law_id_map のテスト ----


def test_resolve_law_id_by_abbreviation() -> None:
    """略称から法令IDへの解決."""
    assert resolve_law_id("keihou") == "140AC0000000045"
    assert resolve_law_id("Penal-Code") == "140AC0000000045"  # 大文字小文字を吸収
    assert resolve_law_id("keiji-soshou-hou") == "323AC0000000131"


def test_resolve_law_id_passthrough_for_law_id() -> None:
    """法令IDが渡されたら、そのまま返す."""
    assert resolve_law_id("140AC0000000045") == "140AC0000000045"


def test_resolve_law_id_raises_for_unknown() -> None:
    """未知の略称は KeyError."""
    with pytest.raises(KeyError, match="Unknown law name or ID"):
        resolve_law_id("nonexistent-law-name")


def test_law_id_map_contains_phase1_laws() -> None:
    """Phase 1 で扱う 4 法令が全部登録されているか."""
    phase1_abbrevs = [
        "keihou",
        "keiji-soshou-hou",
        "keisatsu-hou",
        "keisatsukan-shokumu-shikkou-hou",
    ]
    for abbrev in phase1_abbrevs:
        assert abbrev in LAW_ID_MAP, f"{abbrev} not in LAW_ID_MAP"


# ---- FileCache のテスト ----


def test_filecache_save_and_load(tmp_path: Path) -> None:
    """FileCache の保存と読み出し."""
    cache = FileCache(tmp_path)
    cache.save_law("140AC0000000045", "<Law>test</Law>")
    assert cache.has_law("140AC0000000045") is True
    assert cache.load_law("140AC0000000045") == "<Law>test</Law>"


def test_filecache_with_as_of(tmp_path: Path) -> None:
    """特定時点のキャッシュは別の場所に保存される."""
    cache = FileCache(tmp_path)
    cache.save_law("140AC0000000045", "<Law>latest</Law>")
    cache.save_law("140AC0000000045", "<Law>2020</Law>", as_of=date(2020, 1, 1))

    assert cache.load_law("140AC0000000045") == "<Law>latest</Law>"
    assert cache.load_law("140AC0000000045", as_of=date(2020, 1, 1)) == "<Law>2020</Law>"


def test_filecache_load_missing_raises(tmp_path: Path) -> None:
    """キャッシュにない法令を読もうとすると FileNotFoundError."""
    cache = FileCache(tmp_path)
    with pytest.raises(FileNotFoundError):
        cache.load_law("nonexistent-id")


def test_filecache_list_cached(tmp_path: Path) -> None:
    """list_cached_laws はキャッシュにある法令IDの一覧を返す."""
    cache = FileCache(tmp_path)
    cache.save_law("law-a", "<Law>a</Law>")
    cache.save_law("law-b", "<Law>b</Law>")
    assert cache.list_cached_laws() == ["law-a", "law-b"]


def test_filecache_clear(tmp_path: Path) -> None:
    """clear で全削除."""
    cache = FileCache(tmp_path)
    cache.save_law("law-a", "<Law>a</Law>")
    cache.save_law("law-b", "<Law>b</Law>", as_of=date(2020, 1, 1))
    assert cache.clear() == 2
    assert cache.list_cached_laws() == []


# ---- EGovClient のテスト(モック化) ----


@pytest.fixture
def mock_transport() -> httpx.MockTransport:
    """e-Gov API のレスポンスをモックする httpx トランスポート."""

    def handler(request: httpx.Request) -> httpx.Response:
        # /lawdata/{law_id} 系の XML レスポンス
        if "/law_data/" in request.url.path:
            law_id = request.url.path.split("/")[-1]
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<Law Era="Meiji" Lang="ja" LawType="Act" Num="45" Year="40">'
                f"<LawNum>{law_id}</LawNum>"
                "<LawBody>"
                "<LawTitle>テスト法令</LawTitle>"
                "<MainProvision>"
                '<Article Delete="false" Hide="false" Num="1">'
                "<ArticleTitle>第一条</ArticleTitle>"
                "<Paragraph>テスト本文</Paragraph>"
                "</Article>"
                "</MainProvision>"
                "</LawBody>"
                "</Law>"
            )
            return httpx.Response(200, text=xml, headers={"Content-Type": "application/xml"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_client_fetches_law_and_caches(
    tmp_path: Path,
    mock_transport: httpx.MockTransport,
) -> None:
    """クライアントが API を呼び、キャッシュに保存する一連の動作."""
    cache = FileCache(tmp_path)
    http_client = httpx.Client(
        base_url=EGovClient.DEFAULT_BASE_URL,
        transport=mock_transport,
    )
    client = EGovClient(
        cache=cache,
        http_client=http_client,
        rate_limit_seconds=0,  # テスト時は無効化
    )
    try:
        xml = client.get_law("keihou")
        assert "<LawTitle>テスト法令</LawTitle>" in xml
        assert cache.has_law("140AC0000000045")
        # 2 回目はキャッシュから(API を叩かない)
        xml2 = client.get_law("keihou")
        assert xml == xml2
    finally:
        client.close()


def test_client_force_refresh_bypasses_cache(
    tmp_path: Path,
    mock_transport: httpx.MockTransport,
) -> None:
    """force_refresh=True ならキャッシュを無視."""
    cache = FileCache(tmp_path)
    cache.save_law("140AC0000000045", "<OldXml/>")
    http_client = httpx.Client(
        base_url=EGovClient.DEFAULT_BASE_URL,
        transport=mock_transport,
    )
    client = EGovClient(cache=cache, http_client=http_client, rate_limit_seconds=0)
    try:
        xml = client.get_law("keihou", force_refresh=True)
        assert "<LawTitle>テスト法令</LawTitle>" in xml
        assert "<OldXml/>" not in xml
    finally:
        client.close()


def test_get_law_data_returns_model(
    tmp_path: Path,
    mock_transport: httpx.MockTransport,
) -> None:
    """get_law_data は LawData モデルを返す."""
    cache = FileCache(tmp_path)
    http_client = httpx.Client(
        base_url=EGovClient.DEFAULT_BASE_URL,
        transport=mock_transport,
    )
    client = EGovClient(cache=cache, http_client=http_client, rate_limit_seconds=0)
    try:
        data = client.get_law_data("keihou")
        assert data.law_id == "140AC0000000045"
        assert data.law_name == "テスト法令"
        assert data.article_count_estimate() == 1
    finally:
        client.close()
