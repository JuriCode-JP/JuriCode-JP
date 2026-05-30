"""qlog Pydantic models, constants, and pure helpers (Phase A).

Why: SQLite 永続化レイヤのデータ型を 1 箇所に集約する. 型を厳格 (extra=forbid +
frozen) にし, log レコードが生成後に不変であることを保証する. 時刻正準化と dwell
キャップは純粋関数として切り出し, DB I/O なしで単体テスト可能にする.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DWELL_SECONDS_CAP: Final[float] = 300.0
SQLITE_CONNECT_TIMEOUT: Final[float] = 10.0


def normalize_utc_iso(v: str) -> str:
    """Normalize an ISO 8601 timestamp to canonical UTC microsecond form.

    Why: tz の揺れ (+09:00 / naive) と Python 3.10 の 'Z' 非対応を吸収し, 固定長
    '...+00:00' (microseconds) に統一する. これにより WHERE asked_at=? の文字列一致
    ミスマッチと, 辞書順ソートの崩れ (micros 省略による可変長) を防ぐ. SQLite の
    datetime() も +00:00 を解釈できることを確認済.
    """
    s = v[:-1] + "+00:00" if v.endswith("Z") else v
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="microseconds")


def apply_dwell_cap(dwell_seconds: float | None) -> tuple[float | None, float | None]:
    """Return (capped, raw_or_none) for the V2-1 dwell cap.

    Why: cap 判定を DB I/O から分離し単体テスト可能にする. cap 内なら (value, None),
    cap 超過なら (DWELL_SECONDS_CAP, raw) を返す. None は (None, None).
    """
    if dwell_seconds is None:
        return None, None
    if dwell_seconds > DWELL_SECONDS_CAP:
        return DWELL_SECONDS_CAP, dwell_seconds
    return dwell_seconds, None


def _norm_uuid(v: str) -> str:
    """Normalize a UUID string to canonical lowercase form.

    Why: 大文字/ハイフン揺れを正準小文字にし WHERE id=? のミスマッチを防ぐ. str を
    維持して sqlite3 直接バインドを保つ (uuid.UUID 型は InterfaceError になる).
    """
    return str(uuid.UUID(v))


class QuestionLog(BaseModel):
    """質問 + 検索コンテキストの 1 レコード."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., description="UUID v4")
    session_id: str = Field(..., description="in-memory session UUID")
    asked_at: str = Field(..., description="ISO8601 UTC (canonical)")
    question_text: str | None = Field(None, description="raw 質問文. pii_detected=1 時は None")
    question_text_anonymized: str | None = Field(None, description="匿名化済 (Phase D)")
    pii_detected: int = Field(..., ge=0, le=1, description="0 or 1")
    pii_pattern_matched: str | None = Field(None, description="matched pattern labels (csv)")
    k: int = Field(..., ge=1, description="top-k")
    embedder: str = Field(..., description="tfidf / gemini / openai")
    corpus_version: str = Field(..., description="v0.2 等")

    @field_validator("id")
    @classmethod
    def _norm_id(cls, v: str) -> str:
        return _norm_uuid(v)

    @field_validator("asked_at")
    @classmethod
    def _norm_asked_at(cls, v: str) -> str:
        return normalize_utc_iso(v)


class ResultEntry(BaseModel):
    """検索結果 1 件 (rank + article).

    Why (v5): question_id は持たない. 親の question_id は record_results の呼び出し時
    引数を正本とする (モデルに持たせると引数と二重管理になり無言で乖離するため).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    rank: int = Field(..., ge=1, description="1-based rank")
    article_id: str = Field(..., description="keihou-art-36 等")
    score: float = Field(..., description="cosine 類似度")


class FeedbackEntry(BaseModel):
    """feedback 1 件 (good / bad)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., description="UUID v4")
    question_id: str = Field(..., description="親 question の id")
    given_at: str = Field(..., description="ISO8601 UTC (canonical)")
    signal: Literal["good", "bad"] = Field(..., description="good or bad")
    comment: str | None = Field(None, description="自由記述 (任意)")
    comment_anonymized: str | None = Field(None, description="匿名化済 (Phase D)")

    @field_validator("id", "question_id")
    @classmethod
    def _norm_ids(cls, v: str) -> str:
        return _norm_uuid(v)

    @field_validator("given_at")
    @classmethod
    def _norm_given_at(cls, v: str) -> str:
        return normalize_utc_iso(v)


class ClickEntry(BaseModel):
    """click 1 件 (どの条文を読んだか + 滞在時間)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., description="UUID v4")
    question_id: str = Field(..., description="親 question の id")
    clicked_at: str = Field(..., description="ISO8601 UTC (canonical)")
    rank: int = Field(..., ge=1, description="クリックした結果の順位")
    article_id: str = Field(..., description="クリックした条文 id")
    dwell_seconds: float | None = Field(None, ge=0, description="滞在秒 (cap 済)")
    dwell_seconds_raw: float | None = Field(None, ge=0, description="cap 前生値 (cap 内は None)")

    @model_validator(mode="before")
    @classmethod
    def _cap_dwell(cls, data: Any) -> Any:
        """Apply the V2-1 dwell cap at construction time.

        Why: cap をモデル生成時に適用し memory==DB を保証する (store で書き換えると
        frozen モデルと DB が乖離する). round-trip ガード: dwell_seconds_raw が既に
        入力にあれば DB 再構築とみなし再cap しない (raw 消失バグ防止). caller の dict を
        破壊しないようコピーする. sqlite3.Row は Mapping ではないため store 側で
        dict(row) に変換してから渡す規約.
        """
        if not isinstance(data, Mapping):
            return data
        d = dict(data)
        if d.get("dwell_seconds_raw") is not None:
            return d
        capped, raw = apply_dwell_cap(d.get("dwell_seconds"))
        d["dwell_seconds"] = capped
        d["dwell_seconds_raw"] = raw
        return d

    @field_validator("id", "question_id")
    @classmethod
    def _norm_ids(cls, v: str) -> str:
        return _norm_uuid(v)

    @field_validator("clicked_at")
    @classmethod
    def _norm_clicked_at(cls, v: str) -> str:
        return normalize_utc_iso(v)
