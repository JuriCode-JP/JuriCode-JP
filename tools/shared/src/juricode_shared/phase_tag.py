"""phase_tag — v0.2 corpus の frontmatter `tags[0]` を path-derived phase に揃える純関数群.

責務 (バイブコーディング 3 原則 #1):
  本 module は I/O を一切持たない純関数だけを提供:
    - resolve_phase_from_path(md_path, data_root) -> str
    - rewrite_tags0_in_text(text, new_phase) -> tuple[str, bool]

  ファイル走査 / 書き込み / 統計集計は driver (`tools/scripts/fix-phase-tags.py`)
  の責務. ここでは「ファイル絶対パスから phase 名を導出する」「frontmatter
  文字列の tags[0] を書き換える」だけを行う.

Why この module が必要か (FU-415):
  FU-401 (2026-05-25 完了) で `parse-egov.py` の `--phase-tag` が必須化された
  が、それ以前に ingest された 7,468 ファイルの `tags[0]` は依然として
  ハードコード値 `"phase1-police"` のまま固着している. これを corpus の
  path-derived phase (例: phase2-commercial) に揃える sweep の中核ロジック.

Why frontmatter デリミタで text を 3 分割してから regex 適用するか:
  re.MULTILINE で `^tags:` を全文検索すると、将来 contributor が `notes: |`
  ブロック等を frontmatter または body に追加した場合、本文内の引用文字列
  (例: 注記内に過去メタデータの引用) を誤って書き換える潜伏 bug が残る.
  frontmatter 内部のみで regex を走らせれば構造的に巻き込み事故ゼロ.

Why in-memory text が LF (\\n) 正規化されている前提に依存するか:
  Python の `Path.read_text(encoding='utf-8')` のデフォルト引数 `newline=None`
  は universal newlines モードを有効化し、disk 上の \\r\\n / \\r / \\n を
  すべて \\n に変換する. 本前提に依存することで regex を `\\n` のみに保ち、
  `\\r?\\n` 等の OR 分岐を避けられる. `safe_write_text` の往復で disk 上の
  元改行コードは保存される (Windows の CRLF は CRLF のまま残る).

Why BOM を厳格に拒否するか (option b、2026-05-26 決定):
  本 sweep のスコープを「phase tag 書き換え」だけに純粋に保つため、UTF-8 BOM
  への透過対応は FU-317 (P2) で別途行い、本 module では BOM 検知 → ValueError
  で停止する. 現状 corpus に BOM ファイルは parse-egov.py + safe_write_text
  経由で生成されたものなので存在しないはずだが、混入時は重大事故の前兆として
  即停止し手動レビューに回す.

参照:
  - business/fu-415-phase-tag-sweep-plan-2026-05-26.md §1.5.1 / §2.1 / §2.3
  - tools/fetch-egov/bulk-ingest.py:46-104 (PHASE_MAP、phase dir の規約源)
  - tools/parse/parse-egov.py:347-349 (tags の出力契約)
  - tools/shared/src/juricode_shared/safe_write.py (FU-302、本 module は呼ばないが
    driver で必須使用)
"""

from __future__ import annotations

import re
from pathlib import Path

PHASE_DIR_RE: re.Pattern[str] = re.compile(r"^phase[1-9](?:-[a-z]+)+$")
"""phase ディレクトリ命名規約 pattern.

`phase1-police`, `phase2-commercial`, `phase1-administrative` 等にマッチ.

Why ハードコードを許容するか:
  bulk-ingest.py PHASE_MAP の値と完全一致する規約で、過去 1 年間ブレていない.
  新規 phase 追加時には PHASE_MAP と本 regex を同時に更新する手続が
  事実上 lock-step. 本 regex は invariant check 用途で、過剰一般化すると
  誤入力 (`phase01-Police` 等) を見逃す.
"""

DEPRECATED_PHASE_TAG: str = "phase1-police"
"""FU-401 以前の parse-egov.py がハードコードしていた legacy 値.

phase1-police 配下のファイルでは正規値であり書き換え対象外. それ以外の
phase ディレクトリ配下で tags[0] にこの値があれば sweep 対象となる.
"""

_BOM_CHAR: str = "﻿"
"""UTF-8 BOM. Path.read_text() は BOM を strip しないため明示検知が必要."""

# frontmatter デリミタ. Markdown YAML frontmatter 標準の `---` を改行付きで保持.
_FM_OPEN: str = "---\n"
_FM_CLOSE: str = "\n---\n"

# tags[0] が phase1-police の場合に matching する正規表現.
# Why MULTILINE + literal `\n`: §1.5.1 の不変条件 (LF 正規化済) に依存し、
# frontmatter 範囲内で「行頭 tags: → 次行が `- phase1-police` で始まる」を
# pin point に検出する.
_TAGS_BLOCK_LEGACY_RE: re.Pattern[str] = re.compile(
    rf"^tags:\n- {re.escape(DEPRECATED_PHASE_TAG)}\n",
    re.MULTILINE,
)

# tags[0] が任意の phase の場合に matching する pattern (idempotent 判定用).
_TAGS_BLOCK_ANY_RE: re.Pattern[str] = re.compile(
    r"^tags:\n- (?P<tag0>[^\n]+)\n- (?P<tag1>[^\n]+)\n",
    re.MULTILINE,
)


def resolve_phase_from_path(md_path: Path, data_root: Path) -> str:
    """v0.2 corpus 配下の .md ファイルパスから path-derived phase を抽出.

    Args:
        md_path: data_root/{phase}/{abbrev}/{file}.md の絶対 or 相対パス.
        data_root: corpus ルート (e.g. data/v0.2).

    Returns:
        phase ディレクトリ名 (例: 'phase1-administrative').

    Raises:
        ValueError: md_path が data_root 配下でない場合 (path traversal 防御).
        ValueError: phase ディレクトリ名が PHASE_DIR_RE に一致しない場合
                    (新規 phase 追加時の typo 早期検知).

    Why path-derived を正とするか:
        bulk-ingest.py の PHASE_MAP は法令略称 → phase の写像で、最終的に
        ファイルを置くディレクトリを決定する. corpus のディレクトリ構造は
        その「最終結果」であり、tags[0] はそれに従うべき (drift しない設計).

    Example:
        >>> resolve_phase_from_path(
        ...     Path("/repo/data/v0.2/phase2-commercial/shouhou/shouhou-article-1.md"),
        ...     Path("/repo/data/v0.2"),
        ... )
        'phase2-commercial'
    """
    md_resolved = md_path.resolve() if md_path.is_absolute() else md_path.resolve()
    data_resolved = data_root.resolve()

    try:
        rel = md_resolved.relative_to(data_resolved)
    except ValueError as e:
        raise ValueError(
            f"md_path {md_resolved!s} is not under data_root {data_resolved!s} "
            f"(path traversal防御): {e}"
        ) from e

    parts = rel.parts
    if len(parts) < 3:
        raise ValueError(
            f"md_path {md_resolved!s} relative to data_root has only {len(parts)} "
            f"parts (expected at least 3: phase/abbrev/file.md). parts={parts!r}"
        )

    phase = parts[0]
    if not PHASE_DIR_RE.fullmatch(phase):
        raise ValueError(
            f"phase directory name {phase!r} does not match PHASE_DIR_RE "
            f"(pattern: {PHASE_DIR_RE.pattern}). md_path={md_resolved!s}"
        )

    return phase


def rewrite_tags0_in_text(text: str, new_phase: str) -> tuple[str, bool]:
    """frontmatter 文字列の tags[0] を new_phase に書き換える純関数.

    Args:
        text: .md ファイル全文 (frontmatter + body).
              呼び出し元は `Path.read_text(encoding='utf-8')` の戻り値を
              そのまま渡すこと. 本関数は改行が LF (\\n) 正規化済 + BOM 無し
              であることを前提とする.
        new_phase: 新 phase 値 (PHASE_DIR_RE にマッチすること).

    Returns:
        (new_text, changed) のタプル.
        - changed=False: 既に tags[0] == new_phase の場合 (idempotent).
        - changed=True: phase1-police → new_phase の置換が発生した場合.

    Raises:
        ValueError("[BOM_DETECTED] ..."):
            入力に UTF-8 BOM が含まれる. 本 sweep スコープ外、FU-317 (P2) で
            別途対応.
        ValueError("[FM_MISSING] ..."):
            frontmatter デリミタ '---\\n' が開始または終端で見つからない.
        ValueError("[TAGS_TOO_SHORT] ..."):
            tags 配列が 2 要素未満.
        ValueError("[TAG0_UNEXPECTED] ..."):
            tags[0] が DEPRECATED_PHASE_TAG でも new_phase でもない想定外の値.
        ValueError("[TAG1_NOT_AUTOGEN] ..."):
            tags[1] が "auto-generated" でない (parse-egov.py 出力契約違反).
        ValueError("[INVALID_NEW_PHASE] ..."):
            new_phase が PHASE_DIR_RE にマッチしない.

    Why frontmatter 範囲を明示的に切り出してから regex 適用するか:
        re.MULTILINE で `^tags:` を全文検索すると body の `notes: |` ブロック
        内引用を巻き込む潜伏 bug が残る. frontmatter 内側のみで regex を
        走らせれば構造的に巻き込み事故ゼロ.

    Why ValueError を厳しく投げるか:
        sweep は「均質な mismatch を一括書き換える」目的に絞った tool で、
        想定外の tag 構造があれば手動レビューに回すべき. silent skip すると
        未発見のドリフトが残る (既知事故 d 系の再発).

    Example:
        >>> text = (
        ...     "---\\n"
        ...     "law_id: 132AC0000000048\\n"
        ...     "tags:\\n- phase1-police\\n- auto-generated\\n"
        ...     "---\\n"
        ...     "\\n# 商法\\n"
        ... )
        >>> new_text, changed = rewrite_tags0_in_text(text, "phase2-commercial")
        >>> changed
        True
        >>> "- phase2-commercial\\n- auto-generated" in new_text
        True
    """
    # Guard 0: new_phase の形式チェック (driver の伝播ミス検知).
    if not PHASE_DIR_RE.fullmatch(new_phase):
        raise ValueError(
            f"[INVALID_NEW_PHASE] new_phase={new_phase!r} does not match "
            f"PHASE_DIR_RE (pattern: {PHASE_DIR_RE.pattern})"
        )

    # Guard 1: BOM 検知 (FU-317 とスコープ分離、option b).
    if text.startswith(_BOM_CHAR):
        raise ValueError(
            f"[BOM_DETECTED] file starts with UTF-8 BOM (U+FEFF). "
            f"本 sweep スコープ外、FU-317 (P2) で別途対応. "
            f"first 20 chars after BOM: {text[1:21]!r}"
        )

    # Guard 2: frontmatter 開始デリミタ.
    if not text.startswith(_FM_OPEN):
        raise ValueError(
            f"[FM_MISSING] file does not start with {_FM_OPEN!r} "
            f"(frontmatter opening delimiter). first 30 chars: {text[:30]!r}"
        )

    # Guard 3: frontmatter 終了デリミタ + 3 分割.
    closing_idx = text.find(_FM_CLOSE, len(_FM_OPEN))
    if closing_idx < 0:
        raise ValueError(
            f"[FM_MISSING] no closing {_FM_CLOSE!r} delimiter found after "
            f"opening. text length: {len(text)}"
        )
    # Why closing_idx + 1: _FM_CLOSE = "\n---\n" は先頭の \n が「最終フロントマター
    # 行の終端改行」、続く `---\n` が「閉じデリミタ本体」. fm_block は最終
    # frontmatter 行の改行までを含むべき (regex が `\n` で行終端を anchor するため).
    # body_block は `---\n` (デリミタ本体) から始まる.
    fm_block = text[len(_FM_OPEN) : closing_idx + 1]
    body_block = text[closing_idx + 1 :]  # 先頭は `---\n`、本文側はノータッチ.

    # Step 4: frontmatter 内で tags ブロックを検査.
    m_any = _TAGS_BLOCK_ANY_RE.search(fm_block)
    if m_any is None:
        raise ValueError(
            f"[TAGS_TOO_SHORT] frontmatter has no matching "
            f"`tags:\\n- <tag0>\\n- <tag1>\\n` block "
            f"(tags 配列が 2 要素未満、または非標準フォーマット). "
            f"fm_block first 200 chars: {fm_block[:200]!r}"
        )

    tag0 = m_any.group("tag0")
    tag1 = m_any.group("tag1")

    # Guard 5: tag1 不変条件 (parse-egov.py 出力契約).
    if tag1 != "auto-generated":
        raise ValueError(
            f"[TAG1_NOT_AUTOGEN] tags[1]={tag1!r} (expected 'auto-generated', "
            f"parse-egov.py 出力契約違反). tags[0]={tag0!r}"
        )

    # Step 6: tag0 による 3 分岐.
    if tag0 == new_phase:
        # 冪等: 既に正しい. text は完全不変.
        return text, False

    if tag0 != DEPRECATED_PHASE_TAG:
        # 想定外の tag0. silent skip せず ValueError.
        raise ValueError(
            f"[TAG0_UNEXPECTED] tags[0]={tag0!r} is neither DEPRECATED "
            f"({DEPRECATED_PHASE_TAG!r}) nor expected new_phase ({new_phase!r}). "
            f"Manual review required."
        )

    # Step 7: 置換実行.
    # _TAGS_BLOCK_LEGACY_RE で「tags:\n- phase1-police\n」の 2 行を pin point
    # に検出し、その範囲だけ書き換える. tag1 は inplace で残す.
    m_legacy = _TAGS_BLOCK_LEGACY_RE.search(fm_block)
    if m_legacy is None:
        # _TAGS_BLOCK_ANY_RE が tag0=phase1-police でマッチしたのに legacy
        # regex がマッチしない場合、入力が想定外フォーマット (たとえば
        # tags 直前に空白行などの差異がある).
        raise ValueError(
            f"[TAG0_UNEXPECTED] tag0={tag0!r} but legacy regex did not match. "
            f"非標準 YAML フォーマットの可能性. fm_block first 200 chars: "
            f"{fm_block[:200]!r}"
        )

    new_fm = fm_block[: m_legacy.start()] + f"tags:\n- {new_phase}\n" + fm_block[m_legacy.end() :]
    return _FM_OPEN + new_fm + body_block, True
