"""ローカルキャッシュ管理.

e-Gov API への過剰なリクエストを避けるため、取得した法令 XML を
ローカルに保存し、再取得時はキャッシュから返す.

キャッシュ構造:
    cache/
    ├── laws/                       # 最新版の法令本体
    │   └── {law_id}.xml
    └── snapshots/                  # 特定時点の法令(at-date 取得)
        └── {law_id}__{date}.xml
"""

from __future__ import annotations

from datetime import date
from pathlib import Path


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
        self.laws_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)

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
