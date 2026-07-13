"""Server-side quote snapping: locate an LLM-provided anchor and cut the quote from the source.

Design rule: never let the LLM emit the quote itself. The LLM only names an anchor
(a short verbatim marker of the passage it wants to cite); this module locates the
anchor in the source body and returns the ORIGINAL bytes at that position as the
quote. The quote is therefore verbatim by construction.

不変条件 (破ったら失格・呼び出し側が fail-loud で検査):
    返す quote は必ず body の逐語部分文字列 (quote in body が常に真)。
    正規化は「位置特定のため」だけに使う。正規化済み文字列は返さない。

位置特定できなければ None を返す (= 言い換え・幻覚・別ソースからの引用)。呼び出し側は
None を「anchor not locatable」として扱い、その citation を落とす/再生成する。
"""

from __future__ import annotations

#: 引用の既定の最大文字数 (anchor 開始位置からの原文スライス上限)。
DEFAULT_MAX_LEN = 200

#: 文末・段落の境界。句点で終端 (句点を含める)、改行で終端 (改行は含めない)。
_SENTENCE_END = "。"
_PARAGRAPH_END = "\n"


def _normalize(s: str) -> tuple[str, list[int]]:
    """空白 (半角/全角/タブ/改行) を除去した正規化文字列と、正規化 index -> 原文 index の対応を返す.

    Why: ソース本文には XML 由来の空白・改行パディングがある。anchor と原文を空白を畳んだ
    上で照合することで、LLM が空白を一字一句再現できなくても位置特定できる。対応表 (idx_map) を
    持つことで、正規化上で見つけた位置を「原文のバイト位置」に必ず戻せる (返す引用は原文のまま)。
    """
    out: list[str] = []
    idx_map: list[int] = []
    for i, ch in enumerate(s):
        if ch.isspace():  # 半角/全角空白・タブ・改行・CR を含む
            continue
        out.append(ch)
        idx_map.append(i)
    return "".join(out), idx_map


def snap_quote(anchor: str, body: str, max_len: int = DEFAULT_MAX_LEN) -> str | None:
    """anchor を body 中に位置特定し、その位置の原文スライス (逐語) を返す。特定不能なら None.

    手順:
      1. anchor と body を空白正規化 (位置特定のためだけ)。
      2. 正規化 body 中で正規化 anchor を検索。無ければ None。
      3. 原文の anchor 開始位置から、文末 (句点を含む) / 段落境界 (改行の手前) / 上限文字数の
         いずれか最初に達する所までを原文からスライスして返す (anchor 全体は必ず含む)。

    返り値は常に body の逐語部分文字列 (不変条件)。
    """
    na, _ = _normalize(anchor)
    if not na:
        return None
    nb, idx_map = _normalize(body)
    pos = nb.find(na)
    if pos < 0:
        return None

    start = idx_map[pos]  # 原文における anchor 開始位置
    anchor_end = idx_map[pos + len(na) - 1] + 1  # 原文における anchor 終了位置 (排他)
    hard_limit = start + max_len

    # anchor の後ろから、文末/段落境界/上限のいずれかまで延長する (anchor 全体は必ず含む)。
    end = anchor_end
    j = anchor_end
    while j < len(body) and j < hard_limit:
        ch = body[j]
        if ch == _SENTENCE_END:
            end = j + 1  # 句点を含めて終端
            break
        if ch == _PARAGRAPH_END:
            end = j  # 改行の手前で終端 (改行は含めない)
            break
        j += 1
        end = j
    else:
        # 境界に達しなかった: 上限か本文末で終端 (最低でも anchor 全体は含む)
        end = max(anchor_end, min(len(body), hard_limit))

    return body[start:end]
