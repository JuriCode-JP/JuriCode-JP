"""条 md の frontmatter `cases:` ブロックから裁決/判例エントリを byte 保存で除去する.

Why (FU-71):
    bulk-kfs-*.py の md 書込は append 専用 (`_splice_new_cases` / `_append_cases_to_md`) で、
    誤って付与したリンクを剥がす経路がリポジトリに存在しなかった。枝番脱落バグ (art-74-9 を
    art-74 に潰す) で 5 store に 30 件の偽リンクが commit 済みとなり、parser を直して再 parse
    しても md には誤リンクが残る (append 専用ゆえ二重リンクに悪化する)。本モジュールは
    `_splice_new_cases` の裏返しとして、既存バイトを保存したまま指定 case_id のエントリだけを
    行単位で切り出して削除する。

設計 (yaml 再ダンプしない理由):
    `yaml.safe_load` -> `safe_dump` で書き戻すと、block scalar の引用形式・改行・空行・キー順が
    正規化され、除去対象以外の条文/要旨のバイトまで変わる (「是正対象以外 byte 不変」ゲート違反)。
    ゆえに cases: ブロックを行スライスとして扱い、エントリ境界だけを解析する。
"""

from __future__ import annotations

import re

__all__ = ["remove_cases_from_md_text", "CasesBlockError"]

# `cases:` / `cases: []` の見出し行 (frontmatter トップレベル = インデントなし)。
_CASES_KEY_RE = re.compile(r"^cases:\s*(.*)$")
# エントリ先頭 (`  - case_id: ntt-...`)。bulk の splice が 2 空白 + '- ' で書く。
_ENTRY_START_RE = re.compile(r"^  - case_id:\s*(\S+)\s*$")
# frontmatter の次のトップレベルキー (インデントなし・`- ` でない)。
_TOP_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:")


class CasesBlockError(ValueError):
    """cases: ブロックの構造が想定と異なる (解析不能)。"""


def _find_cases_block(lines: list[str]) -> tuple[int, int, int]:
    """(cases: 行 index, ブロック本体 start, ブロック本体 end[exclusive]) を返す.

    Why: frontmatter は先頭 `---` と 2 つ目の `---` の間。cases: 以降、次のトップレベルキー
    (または frontmatter 終端) までが本体。block scalar 内の空行・インデント行は本体に含める。
    """
    fm_end = None
    for i, ln in enumerate(lines):
        if i > 0 and ln.rstrip() == "---":
            fm_end = i
            break
    if fm_end is None:
        raise CasesBlockError("frontmatter の終端 '---' が見つからない")

    key_idx = None
    for i in range(fm_end):
        if _CASES_KEY_RE.match(lines[i]):
            key_idx = i
            break
    if key_idx is None:
        raise CasesBlockError("frontmatter に cases: が無い")

    end = key_idx + 1
    while end < fm_end and not _TOP_KEY_RE.match(lines[end]):
        end += 1
    return key_idx, key_idx + 1, end


def _entry_bounds(lines: list[str], start: int, end: int) -> list[tuple[str, int, int]]:
    """cases: 本体を (case_id, start, end[exclusive]) のエントリ列に分解する.

    Why: summary_ja の block scalar は空行を含みうるので、空行では区切れない。次のエントリ先頭
    (`  - case_id:`) か本体末尾でのみ区切る。
    """
    starts = [i for i in range(start, end) if _ENTRY_START_RE.match(lines[i])]
    out: list[tuple[str, int, int]] = []
    for n, s in enumerate(starts):
        e = starts[n + 1] if n + 1 < len(starts) else end
        cid = _ENTRY_START_RE.match(lines[s]).group(1)
        out.append((cid, s, e))
    return out


def remove_cases_from_md_text(md_text: str, case_ids: set[str] | frozenset[str]) -> tuple[str, int]:
    """md 本文から指定 case_id の cases: エントリを除去し (新テキスト, 除去件数) を返す.

    Args:
        md_text: 条 md の全文。
        case_ids: 除去対象の case_id 集合。md に無い id は無視 (no-op 安全)。

    Returns:
        (new_text, removed): removed=0 のとき new_text は md_text と完全同一 (byte 不変)。

    Why:
        - 全エントリを除去した場合は `cases:` を `cases: []` に戻す (`_splice_new_cases` が
          `cases: []` を特別扱いして append する裏返し。空の `cases:` は YAML で null になり
          IR 検証が落ちる)。
        - べき等: 二回目の呼び出しは removed=0 で byte 不変。
    """
    if not case_ids:
        return md_text, 0

    lines = md_text.split("\n")
    key_idx, body_start, body_end = _find_cases_block(lines)

    # `cases: []` (インライン空リスト) は除去対象なし。
    m = _CASES_KEY_RE.match(lines[key_idx])
    if m.group(1).strip():
        return md_text, 0

    entries = _entry_bounds(lines, body_start, body_end)
    if not entries:
        return md_text, 0

    doomed = [e for e in entries if e[0] in case_ids]
    if not doomed:
        return md_text, 0

    # 後ろから削ると index がずれない。
    for _cid, s, e in sorted(doomed, key=lambda x: x[1], reverse=True):
        del lines[s:e]

    if len(doomed) == len(entries):
        # 全除去 -> `cases: []` へ退化 (key_idx は削除で動いていない: 本体は key の後ろのみ)。
        lines[key_idx] = "cases: []"

    new_text = "\n".join(lines)
    if not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, len(doomed)
