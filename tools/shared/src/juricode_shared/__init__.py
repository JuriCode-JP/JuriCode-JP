"""juricode_shared — JuriCode-JP 共通モデル.

Pydantic IR(JuriCodeArticle 等)、ID 規約、ファイル配置ルール、frontmatter ヘルパ.
"""

from juricode_shared.ir import (
    JuriCodeArticle,
    Paragraph,
    Item,
    ParentSection,
    TranslationStatus,
    EnglishTranslation,
    EnglishParagraph,
    EnglishItem,
    CaseReference,
    Relevance,
    Amendment,
)
from juricode_shared.ids import make_article_id, make_case_id, validate_article_id
from juricode_shared.paths import article_path, ARCHIVE_SUBDIR
from juricode_shared.safe_write import (
    safe_write_text,
    safe_write_jsonl,
    safe_append_jsonl_records,
)

__version__ = "0.1.0"

__all__ = [
    "JuriCodeArticle",
    "Paragraph",
    "Item",
    "ParentSection",
    "TranslationStatus",
    "EnglishTranslation",
    "EnglishParagraph",
    "EnglishItem",
    "CaseReference",
    "Relevance",
    "Amendment",
    "make_article_id",
    "make_case_id",
    "validate_article_id",
    "article_path",
    "ARCHIVE_SUBDIR",
    "safe_write_text",
    "safe_write_jsonl",
    "safe_append_jsonl_records",
    "__version__",
]
