"""Citation verification (domain-independent): existence (G1) and verbatim quotes (G2).

出典つき回答を prompt 任せにしない (LLM に規律を約束させても守られない) ため、LLM 出力の
citation を規則で機械的に検査し、違反を構造化して返す。違反時の再生成/フォールバックは
呼び出し側が担い、本モジュールは純関数の検査のみ (1 責務・副作用なし)。

検査対象の citation は dict で受ける (キー: chunk_id / quote / anchor)。特定のスキーマ
ライブラリに依存しないため、どの呼び出し側からも使える。
"""

from __future__ import annotations

from .violation import Violation


def check_citations_exist(citations: list[dict], allowed_chunk_ids: set[str]) -> list[Violation]:
    """G1: 各 citation.chunk_id が「渡した hits の chunk_id 集合」に含まれることを検査.

    Why: LLM が渡していない出典を捏造する事故を機械的に塞ぐ。allowed は本文を渡した
    chunk_id の集合 (= LLM が引用してよい唯一の集合)。
    """
    out: list[Violation] = []
    for c in citations:
        cid = c.get("chunk_id")
        if cid not in allowed_chunk_ids:
            out.append(Violation("G1", f"citation chunk_id not in provided hits: {cid!r}"))
    return out


def check_quotes_verbatim(citations: list[dict], chunk_texts: dict[str, str]) -> list[Violation]:
    """G2: サーバーが切り出した citation.quote が原文の逐語部分文字列 (byte 一致) か検査.

    Why: quote は LLM に打たせず、サーバーが anchor を原文に位置特定して原文のバイト列を
    切り出す (snap.snap_quote)。ゆえに quote は構造上必ず原文の部分文字列になる。
    検査は不変条件の確認であり、破れ方で内訳を分けて計上する:
      - body 無し           -> "no body" (chunk_id が渡した hits に無い。G1 と二重に落ちる)
      - quote 無し (None/空) -> "anchor not locatable" (anchor が言い換え・幻覚・別チャンク由来)
      - quote が原文に無い   -> "snapped_quote_mismatch" (= 実装バグ。構造上 0 のはず・fail-loud)
    """
    out: list[Violation] = []
    for c in citations:
        cid = c.get("chunk_id")
        quote = c.get("quote")
        anchor = c.get("anchor") or ""
        body = chunk_texts.get(cid)
        if body is None:
            out.append(Violation("G2", f"cannot verify quote; no body for chunk_id {cid!r}"))
        elif not quote:
            out.append(Violation("G2", f"anchor not locatable in {cid!r}: {anchor[:40]!r}"))
        elif quote not in body:
            out.append(Violation("G2", f"snapped_quote_mismatch in {cid!r} (implementation bug)"))
    return out


def valid_citations_only(
    citations: list[dict], allowed_chunk_ids: set[str], chunk_texts: dict[str, str]
) -> list[dict]:
    """G1+G2 を通る citation だけを残す (フォールバック応答に安全な出典のみ残すため)."""
    kept: list[dict] = []
    for c in citations:
        cid = c.get("chunk_id")
        quote = c.get("quote") or ""
        body = chunk_texts.get(cid)
        if cid in allowed_chunk_ids and body is not None and quote and quote in body:
            kept.append(c)
    return kept
