#!/usr/bin/env python3
"""layer1_build_corpora.py -- RAG 忠実性 Layer1 pilot の 4 corpus を構築する.

構造化 (A) vs 生 e-Gov テキスト (B0) を、条粒度・項粒度の 2 軸で比較するための
4 つの text corpus を、**既存パーサを tap** して生成する (新規パーサ禁止)。

4 corpus:
    A-para  (A-項) : 構造化・項粒度 = メタprefix + canonicalize(項 生本文)
    A-art   (A-条) : 構造化・条粒度 = メタprefix + canonicalize(条 生本文の項連結)
    B0-para (B0-項): 生・項粒度     = 項 生本文 (canonicalize 前・メタ無し)
    B0-art  (B0-条): 生・条粒度     = 条 生本文の項連結 (canonicalize 前・メタ無し)

Why (設計の要点):
  - **B0 tap**: parse-egov `parse_egov_xml` が返す `paragraphs[].text` は
    `extract_all_text` による生抽出テキストで **canonicalize 前**。これをそのまま
    B0 に使うことで「新規パーサを書かず既存抽出を tap」する規律を守る。
  - **項境界の共有 (§A-3)**: A-項/B0-項 はともに XML `<Paragraph>` ノード
    (項番号 Num を持つ) を項単位とする。parse-egov の MD 生成 (article_to_markdown)
    は 1 <Paragraph> = 1 見出し `### 第N条第M項` を出力し、segment_parser の
    `PARAGRAPH_HEADING_PATTERN` はその見出しで分割するため、**XML Paragraph ノード
    ≡ segment_parser の項 segment**。よって XML ノードを両者の項単位にすれば境界一致は
    構成上自明 (marker 再分割より強い保証)。
  - **条連結仕様の一致 (§A-4)**: A-条/B0-条 はともに項本文を `"\n\n".join(...)` で連結
    (parse-egov `extract_canonical_text` と同一 join)。A のみ canonicalize + メタを足す。
    連結規則が同一ゆえ A/B の差は「正規化 + メタ」だけに帰属する。
  - **token 超過の対称除外 (§A-2・佐藤裁定 Option 2)**: gemini-embedding-001 の
    ~2048 token 上限を超える条は A-条/B0-条 の **両方から対称除外** する (切り詰めゼロ・
    partial-content 交絡を持ち込まない)。除外集合は A/B 共通 = 公平。項粒度は個別項が
    短いため通常非影響だが、万一超過する項も対称除外する。閾値判定は tiktoken
    cl100k_base を保守的 oracle として使う (日本語では cl100k は Gemini SentencePiece
    より多めに数える傾向 = 過小除外しない安全側)。

使い方:
    PYTHONUTF8=1 python tools/embed/layer1_build_corpora.py \
        --out-dir build/layer1-rawtext \
        --guard-log build/layer1-rawtext/_build-guard.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO = _THIS.parent.parent.parent
_SHARED_SRC = _REPO / "tools" / "shared" / "src"
_PARSE_DIR = _REPO / "tools" / "parse"
for _p in (str(_SHARED_SRC), str(_PARSE_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _canonicalize import canonicalize  # noqa: E402  (tools/parse on path)
from juricode_shared import safe_write_text  # noqa: E402


def _load_parse_egov():
    """Import the hyphenated parse-egov.py module by path (can't `import parse-egov`).

    Why: reuse the production XML extractor + canonicalize (新規パーサ禁止). We only
    borrow `parse_egov_xml` (raw paragraph text tap) and `canonicalize`.
    """
    path = _REPO / "tools" / "parse" / "parse-egov.py"
    spec = importlib.util.spec_from_file_location("parse_egov_mod", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# gemini-embedding-001 input cap. 超過条は条-level から対称除外 (§A-2 Option 2).
TOKEN_LIMIT = 2048

# 対象法令: (law_id, law_abbrev). abbrev は corpus/gold の article_id prefix と一致必須.
LAW_TARGETS: tuple[tuple[str, str], ...] = (
    # 主 eval (lawqa-jp)
    ("323AC0000000025", "kinsho-hou"),  # 金融商品取引法
    ("335AC0000000145", "yakkihou"),  # 医薬品医療機器等法 (薬機法)
    ("403AC0000000090", "shakuchi-shakka-hou"),  # 借地借家法
    # 税務サブセット (別掲)
    ("340AC0000000033", "shotoku-zei-hou"),  # 所得税法
    ("325AC0000000226", "chihou-zei-hou"),  # 地方税法
    ("337AC0000000066", "kokuzei-tsuusoku-hou"),  # 国税通則法
)

_PARA_JOIN = "\n\n"  # 項連結の delimiter (parse-egov extract_canonical_text と同一)


@dataclass(frozen=True)
class ArticleUnit:
    """1 条の 4 表現テキスト (frozen = 構築後不変)."""

    article_id: str
    law_id: str
    law_name_ja: str
    article_number: str
    paragraphs: tuple[tuple[int, str], ...]  # (para_number, raw_text)


def _iter_articles(mod, law_id: str, abbrev: str, cache_dir: Path):
    """Parse cached XML and yield ArticleUnit per article (range articles pre-filtered)."""
    xml = (cache_dir / f"{law_id}.xml").read_text(encoding="utf-8")
    parsed = mod.parse_egov_xml(xml)
    law_name = parsed["law_name_ja"]
    for art in parsed["articles"]:
        num = str(art["number"])
        paras = tuple((int(p["number"]), p["text"]) for p in art["paragraphs"])
        yield ArticleUnit(
            article_id=f"{abbrev}-art-{num}",
            law_id=law_id,
            law_name_ja=law_name,
            article_number=num,
            paragraphs=paras,
        )


def _meta_prefix(law_name: str, art_num: str, para_num: int | None) -> str:
    """構造化 (A) の本文に付すメタ prefix = 法令名/条/項 (佐藤裁定: caption 無し)."""
    base = f"{law_name} 第{art_num}条"
    if para_num is not None:
        base += f" 第{para_num}項"
    return base


def article_texts(law_name: str, art_num: str, paragraphs: tuple[tuple[int, str], ...]) -> dict:
    """1 条の 4 表現テキスト + 項単位テキストを純関数で構築 (hermetic test 可).

    Returns dict:
        b0_art / a_art : 条-level (生 / 構造化)
        b0_para / a_para: list[(para_num, text)] 項-level (生 / 構造化)

    不変条件:
        - B0 = 生 (canonicalize 前・メタ無し)
        - A  = メタprefix + canonicalize(生本文)
        - 条-level = 項本文を `\\n\\n` で連結 (A/B0 同一 join = §A-4)
    """
    raw_join = _PARA_JOIN.join(t for _, t in paragraphs)
    b0_art = raw_join
    a_art = _meta_prefix(law_name, art_num, None) + "\n" + canonicalize(raw_join)
    b0_para = [(pn, pt) for pn, pt in paragraphs]
    a_para = [
        (pn, _meta_prefix(law_name, art_num, pn) + "\n" + canonicalize(pt)) for pn, pt in paragraphs
    ]
    return {"b0_art": b0_art, "a_art": a_art, "b0_para": b0_para, "a_para": a_para}


def build(cache_dir: Path, out_dir: Path, guard_log: Path) -> int:
    mod = _load_parse_egov()

    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")

    def ntok(text: str) -> int:
        return len(enc.encode(text))

    a_para, a_art, b_para, b_art = [], [], [], []
    excluded_art: list[dict] = []
    excluded_para: list[dict] = []
    per_law: dict[str, dict] = {}
    boundary_mismatch: list[str] = []

    for law_id, abbrev in LAW_TARGETS:
        n_art = n_para = n_excl_art = n_excl_para = 0
        for unit in _iter_articles(mod, law_id, abbrev, cache_dir):
            n_art += 1
            texts = article_texts(unit.law_name_ja, unit.article_number, unit.paragraphs)
            # ---- 条-level texts (項本文を同一 join で連結) ----
            b0_art_text = texts["b0_art"]
            a_art_text = texts["a_art"]
            # §A-2 対称除外: A-条/B0-条 のどちらかが上限超過なら両方から除外
            art_tok = max(ntok(a_art_text), ntok(b0_art_text))
            art_over = art_tok > TOKEN_LIMIT
            if art_over:
                n_excl_art += 1
                excluded_art.append(
                    {"article_id": unit.article_id, "tokens": art_tok, "limit": TOKEN_LIMIT}
                )
            else:
                common = {
                    "article_id": unit.article_id,
                    "chunk_id": unit.article_id,
                    "law_id": unit.law_id,
                    "law_name_ja": unit.law_name_ja,
                    "article_number": unit.article_number,
                    "paragraph_number": None,
                }
                a_art.append({**common, "text": a_art_text})
                b_art.append({**common, "text": b0_art_text})

            # ---- 項-level texts (XML Paragraph ノード = 共有項単位, §A-3) ----
            a_units_this, b_units_this = [], []
            a_para_map = dict(texts["a_para"])
            for pnum, ptext in unit.paragraphs:
                n_para += 1
                b0_para_text = ptext
                a_para_text = a_para_map[pnum]
                para_tok = max(ntok(a_para_text), ntok(b0_para_text))
                if para_tok > TOKEN_LIMIT:
                    n_excl_para += 1
                    excluded_para.append(
                        {
                            "article_id": unit.article_id,
                            "paragraph_number": pnum,
                            "tokens": para_tok,
                        }
                    )
                    continue
                cid = f"{unit.article_id}#p{pnum}"
                common = {
                    "article_id": unit.article_id,
                    "chunk_id": cid,
                    "law_id": unit.law_id,
                    "law_name_ja": unit.law_name_ja,
                    "article_number": unit.article_number,
                    "paragraph_number": pnum,
                }
                a_units_this.append({**common, "text": a_para_text})
                b_units_this.append({**common, "text": b0_para_text})
            # §A-3 境界一致 (自明だが明示 assert): A-項 と B0-項 の項集合が一致
            if [r["chunk_id"] for r in a_units_this] != [r["chunk_id"] for r in b_units_this]:
                boundary_mismatch.append(unit.article_id)
            a_para.extend(a_units_this)
            b_para.extend(b_units_this)

        per_law[abbrev] = {
            "law_id": law_id,
            "articles": n_art,
            "paragraphs": n_para,
            "excluded_art_over_token": n_excl_art,
            "excluded_para_over_token": n_excl_para,
        }

    # ---- §A-1 set-diff=0 (A vs B0, 各粒度) ----
    def aidset(rows):
        return {r["article_id"] for r in rows}

    def cidset(rows):
        return {r["chunk_id"] for r in rows}

    setdiff_art = aidset(a_art) ^ aidset(b_art)
    setdiff_para = cidset(a_para) ^ cidset(b_para)

    out_dir.mkdir(parents=True, exist_ok=True)

    def write_jsonl(rows, name):
        body = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
        safe_write_text(out_dir / name, body)

    write_jsonl(a_para, "layer1-A-para.jsonl")
    write_jsonl(a_art, "layer1-A-art.jsonl")
    write_jsonl(b_para, "layer1-B0-para.jsonl")
    write_jsonl(b_art, "layer1-B0-art.jsonl")

    guard = {
        "token_limit": TOKEN_LIMIT,
        "token_oracle": "tiktoken-cl100k_base (conservative vs Gemini SentencePiece)",
        "corpora": {
            "A-para": len(a_para),
            "A-art": len(a_art),
            "B0-para": len(b_para),
            "B0-art": len(b_art),
        },
        "guard_A1_setdiff_article_level": sorted(setdiff_art),
        "guard_A1_setdiff_paragraph_level": sorted(setdiff_para),
        "guard_A3_boundary_mismatch_articles": boundary_mismatch,
        "guard_A2_excluded_articles_over_token": excluded_art,
        "guard_A2_excluded_paragraphs_over_token": excluded_para,
        "per_law": per_law,
    }
    safe_write_text(guard_log, json.dumps(guard, ensure_ascii=False, indent=2) + "\n")

    # fail-loud: §A-1 set-diff must be 0, §A-3 boundary must match
    ok = True
    if setdiff_art or setdiff_para:
        print(f"FAIL §A-1 set-diff != 0: art={setdiff_art} para={setdiff_para}", file=sys.stderr)
        ok = False
    if boundary_mismatch:
        print(f"FAIL §A-3 boundary mismatch: {boundary_mismatch}", file=sys.stderr)
        ok = False

    print("=== layer1 corpus build summary ===", file=sys.stderr)
    for k, v in guard["corpora"].items():
        print(f"  {k:8s}: {v}", file=sys.stderr)
    print(
        f"  excluded 条 (>2048 tok): {len(excluded_art)}  項: {len(excluded_para)}",
        file=sys.stderr,
    )
    for ab, s in per_law.items():
        print(
            f"  {ab:22s} art={s['articles']} para={s['paragraphs']} "
            f"excl_art={s['excluded_art_over_token']}",
            file=sys.stderr,
        )
    print(f"  guard log -> {guard_log}", file=sys.stderr)
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--cache-dir", type=Path, default=_REPO / "cache" / "laws")
    ap.add_argument("--out-dir", type=Path, default=_REPO / "build" / "layer1-rawtext")
    ap.add_argument(
        "--guard-log",
        type=Path,
        default=_REPO / "build" / "layer1-rawtext" / "_build-guard.json",
    )
    args = ap.parse_args()
    return build(args.cache_dir, args.out_dir, args.guard_log)


if __name__ == "__main__":
    sys.exit(main())
