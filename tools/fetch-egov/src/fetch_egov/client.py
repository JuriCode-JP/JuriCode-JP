"""e-Gov 法令API v2 HTTP クライアント (v2 OpenAPI 仕様準拠).

公式 API: https://laws.e-gov.go.jp/api/2/
OpenAPI: https://laws.e-gov.go.jp/api/2/redoc/

5 エンドポイント:
  1. GET /laws                                    - 法令一覧・検索
  2. GET /law_revisions/{law_id_or_num}           - 改正履歴一覧
  3. GET /law_data/{law_id_or_num_or_revision_id} - 法令本文取得
  4. GET /attachment/{law_revision_id}            - 添付ファイル取得
  5. GET /keyword                                 - キーワード検索
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any, Literal

import httpx

from fetch_egov.cache import FileCache
from fetch_egov.law_id_map import resolve_law_id
from fetch_egov.models import LawData, LawMetadata

logger = logging.getLogger(__name__)

FileType = Literal["xml", "pdf", "rtf", "docx"]


class EGovClient:
    """e-Gov 法令API v2 クライアント."""

    DEFAULT_BASE_URL = "https://laws.e-gov.go.jp/api/2"
    DEFAULT_TIMEOUT = 30.0
    DEFAULT_USER_AGENT = (
        "fetch-egov/0.1.0 (JuriCode-JP; +https://github.com/JuriCode-JP/JuriCode-JP)"
    )
    DEFAULT_RATE_LIMIT_SECONDS = 1.0

    def __init__(
        self,
        cache: FileCache | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        user_agent: str = DEFAULT_USER_AGENT,
        rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.cache = cache
        self.base_url = base_url.rstrip("/")
        self.rate_limit_seconds = rate_limit_seconds
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        )
        self._last_request_at: float = 0.0

    def __enter__(self) -> EGovClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # 1. 法令本文取得 ============================================

    def get_law(
        self,
        name_or_id: str,
        asof: date | None = None,
        *,
        force_refresh: bool = False,
        omit_amendment_suppl_provision: bool = False,
    ) -> str:
        law_id = resolve_law_id(name_or_id)
        if self.cache is not None and not force_refresh and self.cache.has_law(law_id, asof):
            logger.info("Cache hit: %s (asof=%s)", law_id, asof)
            return self.cache.load_law(law_id, asof)
        xml_content = self._fetch_law_xml(
            law_id,
            asof=asof,
            omit_amendment_suppl_provision=omit_amendment_suppl_provision,
        )
        if self.cache is not None:
            self.cache.save_law(law_id, xml_content, asof)
        return xml_content

    def get_law_data(
        self,
        name_or_id: str,
        asof: date | None = None,
        *,
        force_refresh: bool = False,
    ) -> LawData:
        law_id = resolve_law_id(name_or_id)
        xml = self.get_law(name_or_id, asof=asof, force_refresh=force_refresh)
        law_name = self._extract_law_name(xml) or law_id
        return LawData(
            law_id=law_id,
            law_name=law_name,
            xml_content=xml,
            as_of_date=asof,
        )

    def _fetch_law_xml(
        self,
        law_id_or_num_or_revision_id: str,
        asof: date | None = None,
        *,
        omit_amendment_suppl_provision: bool = False,
    ) -> str:
        self._respect_rate_limit()
        endpoint = f"/law_data/{law_id_or_num_or_revision_id}"
        params: dict[str, str] = {
            "response_format": "xml",
            "law_full_text_format": "xml",
        }
        if asof is not None:
            params["asof"] = asof.isoformat()
        if omit_amendment_suppl_provision:
            params["omit_amendment_suppl_provision"] = "true"
        logger.info("GET %s%s (asof=%s)", self.base_url, endpoint, asof)
        response = self._client.get(endpoint, params=params)
        response.raise_for_status()
        self._last_request_at = time.monotonic()
        return response.text

    # 2. 法令一覧 ================================================

    def list_laws(
        self,
        *,
        law_title: str | None = None,
        law_type: str | None = None,
        law_id: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[LawMetadata]:
        params: dict[str, str] = {"response_format": "json"}
        if law_title:
            params["law_title"] = law_title
        if law_type:
            params["law_type"] = law_type
        if law_id:
            params["law_id"] = law_id
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        data = self._get_json("/laws", params)
        laws_list = data.get("laws", data.get("law_info", []))
        return [self._coerce_law_metadata(item) for item in laws_list]

    # 3. 改正履歴 ================================================

    def get_revisions(
        self,
        name_or_id: str,
        *,
        amendment_date_from: date | None = None,
        amendment_date_to: date | None = None,
    ) -> list[dict[str, Any]]:
        law_id = resolve_law_id(name_or_id)
        params: dict[str, str] = {"response_format": "json"}
        if amendment_date_from:
            params["amendment_date_from"] = amendment_date_from.isoformat()
        if amendment_date_to:
            params["amendment_date_to"] = amendment_date_to.isoformat()
        data = self._get_json(f"/law_revisions/{law_id}", params)
        return data.get("law_revisions", data.get("revisions", []))

    # 4. キーワード検索 ==========================================

    def search_keyword(
        self,
        keyword: str,
        *,
        law_type: str | None = None,
        asof: date | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {"keyword": keyword, "response_format": "json"}
        if law_type:
            params["law_type"] = law_type
        if asof:
            params["asof"] = asof.isoformat()
        if limit is not None:
            params["limit"] = str(limit)
        data = self._get_json("/keyword", params)
        return data.get("hits", data.get("results", data.get("laws", [])))

    # 5. 添付ファイル取得 ========================================

    def get_attachment(
        self,
        law_revision_id: str,
        src: str | None = None,
    ) -> bytes:
        self._respect_rate_limit()
        endpoint = f"/attachment/{law_revision_id}"
        params = {"src": src} if src else None
        response = self._client.get(endpoint, params=params)
        response.raise_for_status()
        self._last_request_at = time.monotonic()
        return response.content

    # 内部メソッド ===============================================

    def _get_json(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        self._respect_rate_limit()
        p = dict(params or {})
        p.setdefault("response_format", "json")
        logger.info("GET %s%s params=%s", self.base_url, endpoint, p)
        response = self._client.get(
            endpoint,
            params=p,
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        self._last_request_at = time.monotonic()
        return response.json()

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.rate_limit_seconds:
            time.sleep(self.rate_limit_seconds - elapsed)

    @staticmethod
    def _extract_law_name(xml: str) -> str | None:
        start = xml.find("<LawTitle>")
        end = xml.find("</LawTitle>")
        if start == -1 or end == -1:
            return None
        return xml[start + len("<LawTitle>") : end].strip()

    @staticmethod
    def _coerce_law_metadata(item: dict[str, Any]) -> LawMetadata:
        return LawMetadata(
            law_id=item.get("law_id", ""),
            law_num=item.get("law_num"),
            law_name=item.get("law_title", item.get("law_name", "")),
            law_name_kana=item.get("law_title_kana"),
            law_type=item.get("law_type"),
            promulgation_date=item.get("promulgation_date"),
            enforcement_date=item.get("enforcement_date"),
            abolish_date=item.get("abolish_date"),
        )
