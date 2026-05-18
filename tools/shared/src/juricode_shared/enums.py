"""列挙型 (StrEnum)."""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from enum import StrEnum
else:
    # Python 3.10 fallback
    from enum import Enum

    class StrEnum(str, Enum):
        """Python 3.11 の StrEnum を 3.10 で代替."""

        def __str__(self) -> str:
            return self.value


class TranslationStatus(StrEnum):
    """英訳の出所."""

    OFFICIAL = "official"  # 法務省 JLT-DB の公定訳
    COMMUNITY = "community"  # コミュニティ訳 (CC BY 4.0 推奨)
    DRAFT = "draft"  # 機械翻訳・ドラフト
    NONE = "none"  # 英訳なし


class Relevance(StrEnum):
    """判例と条文の関連度."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
