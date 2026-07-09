"""ローカルキャッシュ管理.

e-Gov API への過剰なリクエストを避けるため、取得した法令 XML を
ローカルに保存し、再取得時はキャッシュから返す.

キャッシュ構造:
    cache/
    ├── laws/                       # 最新版の法令本体
    │   └── {law_id}.xml
    ├── snapshots/                  # 特定時点の法令(at-date 取得)
    │   └── {law_id}__{date}.xml
    └── revisions/                  # 改正版単位の法令本体(law_revision_id 取得)
        └── {law_revision_id}.xml
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

# law_revision_id は英数 + アンダースコア (例 363AC0000000108_20260401_508AC0000000012)。
# path traversal 防御: この形以外は cache パスに使わせない。
_REVISION_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")


class FileCache:
    """ファイルベースのシンプルなキャッシュ.

    Examples:
        >>> cache = FileCache(Path("cache/"))
        >>> cache.save_law("140AC0000000045", "<Law>...</Law>")
        >>> xml = cache.load_law("140AC0000000045")
    """

    def __init__(self, root: Path | str) -> None:
        """初期化.

        Args:
            root: キャッシュルートディレクトリ. 存在しない場合は作成される.
        """
        self.root = Path(root)
        self.laws_dir = self.root / "laws"
        self.snapshots_dir = self.root / "snapshots"
        self.revisions_dir = self.root / "revisions"
        self.laws_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self.revisions_dir.mkdir(parents=True, exist_ok=True)

    def _law_path(self, law_id: str, as_of: date | None = None) -> Path:
        """法令ID + (任意の時点)から、キャッシュファイルパスを生成."""
        if as_of is None:
            return self.laws_dir / f"{law_id}.xml"
        return self.snapshots_dir / f"{law_id}__{as_of.isoformat()}.xml"

    def has_law(self, law_id: str, as_of: date | None = None) -> bool:
        """キャッシュに法令があるか確認."""
        return self._law_path(law_id, as_of).exists()

    def load_law(self, law_id: str, as_of: date | None = None) -> str:
        """キャッシュから法令 XML を読み込む.

        Raises:
            FileNotFoundError: キャッシュに存在しない場合.
        """
        path = self._law_path(law_id, as_of)
        if not path.exists():
            raise FileNotFoundError(
                f"Law {law_id} not in cache "
                f"(as_of={as_of.isoformat() if as_of else 'latest'}). "
                f"Fetch it first."
            )
        return path.read_text(encoding="utf-8")

    def save_law(
        self,
        law_id: str,
        xml_content: str,
        as_of: date | None = None,
    ) -> Path:
        """法令 XML をキャッシュに保存."""
        path = self._law_path(law_id, as_of)
        path.write_text(xml_content, encoding="utf-8")
        return path

    # 改正版単位 (law_revision_id) のキャッシュ ==================
    #
    # Why: get_revisions が返す各版の全文は law_revision_id で取得する
    # (同一施行日に複数改正が乗る日は asof=日付 では per-law 分離できず畳み込まれる
    # ため、改正履歴 populate では revision_id 取得が必須)。law_id__asof キーの
    # laws/snapshots 経路とは名前空間を分ける。

    def _revision_path(self, law_revision_id: str) -> Path:
        if not _REVISION_ID_RE.match(law_revision_id):
            raise ValueError(f"unsafe law_revision_id for cache path: {law_revision_id!r}")
        return self.revisions_dir / f"{law_revision_id}.xml"

    def has_revision(self, law_revision_id: str) -> bool:
        """改正版がキャッシュにあるか確認."""
        return self._revision_path(law_revision_id).exists()

    def load_revision(self, law_revision_id: str) -> str:
        """キャッシュから改正版 XML を読み込む.

        Raises:
            FileNotFoundError: キャッシュに存在しない場合.
        """
        path = self._revision_path(law_revision_id)
        if not path.exists():
            raise FileNotFoundError(f"Revision {law_revision_id} not in cache. Fetch it first.")
        return path.read_text(encoding="utf-8")

    def save_revision(self, law_revision_id: str, xml_content: str) -> Path:
        """改正版 XML をキャッシュに保存."""
        path = self._revision_path(law_revision_id)
        path.write_text(xml_content, encoding="utf-8")
        return path

    def list_cached_laws(self) -> list[str]:
        """キャッシュ済みの法令 ID 一覧(最新版のみ、snapshots は含まず)."""
        return sorted([p.stem for p in self.laws_dir.glob("*.xml")])

    def clear(self) -> int:
        """キャッシュ全削除. 削除したファイル数を返す."""
        count = 0
        for p in self.laws_dir.glob("*.xml"):
            p.unlink()
            count += 1
        for p in self.snapshots_dir.glob("*.xml"):
            p.unlink()
            count += 1
        return count
