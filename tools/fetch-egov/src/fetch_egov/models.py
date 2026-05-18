"""e-Gov 法令API v2 のレスポンス型(Pydantic モデル).

注: e-Gov API v2 の OpenAPI 仕様は https://laws.e-gov.go.jp/api/2/redoc/ で
公開されている. ここでは最小限のメタデータのみを Pydantic 化し、本体の
XML は raw bytes として扱う(後段の `tools/parse/` で ja-law-parser に
渡してパースする).
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class LawMetadata(BaseModel):
    """法令メタデータ. e-Gov API の `/lawlists/` 系エンドポイントが返す情報."""

    model_config = ConfigDict(extra="allow")  # API 仕様変更に備えて未知フィールドを許容

    law_id: str = Field(..., description="e-Gov 法令ID(例: 140AC0000000045)")
    law_num: str | None = Field(None, description="法令番号(例: 明治四十年法律第四十五号)")
    law_name: str = Field(..., description="法令名(日本語、例: 刑法)")
    law_name_kana: str | None = Field(None, description="法令名のフリガナ")
    law_type: str | None = Field(None, description="法令種別(例: Act, Constitution)")
    promulgation_date: date | None = Field(None, description="公布日")
    enforcement_date: date | None = Field(None, description="施行日")
    abolish_date: date | None = Field(None, description="廃止日(廃止された場合)")


class LawData(BaseModel):
    """法令データ. 法令本文 XML を含む."""

    model_config = ConfigDict(extra="allow")

    law_id: str = Field(..., description="e-Gov 法令ID")
    law_name: str = Field(..., description="法令名(日本語)")
    xml_content: str = Field(..., description="法令本文 XML(標準法 XML スキーマ v3 準拠)")
    fetched_at: date | None = Field(None, description="API から取得した日付")
    as_of_date: date | None = Field(
        None,
        description="この XML が表す時点(特定時点取得時、e-Gov API v2 の at-date 機能)",
    )

    def article_count_estimate(self) -> int:
        """XML 本文中の `<Article` タグの数を簡易カウント(近似値).

        厳密なパースは `tools/parse/` に任せる. ここは sanity check 用.
        """
        return self.xml_content.count("<Article ")
