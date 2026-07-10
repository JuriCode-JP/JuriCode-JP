# Layer1 pilot — structured vs raw retrieval fidelity / 構造化 vs 生テキスト retrieval 忠実性

**EN** — Does JuriCode-JP's *structured* corpus (canonicalized text + metadata) retrieve better
than *raw* e-Gov paragraph text, at the same granularity? This is a **measurement pilot** (V0.4
retrieval-quality track): it adds **no corpus data** — it embeds four controlled representations of
the *same* articles and compares retrieval.

**JA** — JuriCode-JP の**構造化**コーパス（正規化本文＋メタ）が、同一粒度の**生** e-Gov 項テキスト
より retrieval で優れるかを測る**測定パイロット**（V0.4 retrieval 品質トラック）。corpus データは
一切増やさず、**同一条文の 4 表現**を埋め込み比較する。

## Design / 設計

4 conditions × 2 query modes × 4 ablation settings.

| Condition | Granularity | Representation |
|---|---|---|
| **A-para** | 項 (paragraph) | structured = `法令名 第N条 第M項\n` + `canonicalize(生本文)` |
| **A-art** | 条 (article) | structured = `法令名 第N条\n` + `canonicalize(項連結)` |
| **B0-para** | 項 | raw = 生本文 (canonicalize 前・メタ無し) |
| **B0-art** | 条 | raw = 項連結 (canonicalize 前・メタ無し) |

- **Query modes**: `raw` / `canon` (query に `canonicalize` 適用 = §3.1 感度軸)
- **Ablation**: `baseline` / `normalize` (法令略称展開) / `reranker` / `both`
- **Retrieval order (§5)**: dense wide-fetch M=200 → [chunk rerank on wide] → `dedup_by_article` → cut-K → Recall@K. All conditions identical.
- **Corpora tapped from production parser** (新規パーサ禁止): B0 = `parse_egov_xml` の `paragraphs[].text` (canonicalize 前の生抽出)。A = same + `canonicalize` + meta. 項境界は XML `<Paragraph>` ノード = segment_parser の項 segment と等価 (§A-3 boundary 一致は構成上自明)。

## Eval / 評価セット (案5)

- **Main** = `data/eval-set/lawqa-jp/*.jsonl` (Digital Agency lawqa_jp, PDL 1.0, 本則条 gold): 金商法 / 薬機法 / 借地借家法.
- **Tax subset** = `tax-honbun-local/g1-local.jsonl` (10) + `tax.jsonl` (2): 所得税法 / 地方税法 / 国税通則法.
- **§A-0 corpus-gold filter**: gold が corpus 実在する問のみ採用。**採用 N = 136** (para-level) / **112** (art-level, ≤2048 条サブセット)。lawqa 5 問は gold が施行令/府令で本則 corpus 非在ゆえ非採用。

## §A pre-flight guards (= this pilot's "lock") / 事前ガード

`build-guard.json` に実測ログ。数値 expected は無い（測定実験）。ロックはメソドロジー:

| Guard | 結果 |
|---|---|
| §A-0 corpus-gold filter | 採用 N=136 (para) / 112 (art) |
| §A-1 set-diff (A vs B0) | **0** (article + paragraph level) |
| §A-2 token 超過 | **佐藤裁定 Option 2** = >2048 token 条を A-条/B0-条 両方から**対称除外** (切り詰めゼロ)。除外 123 条 (金商28/薬機13/借地借家0/所得13/地方税64/国通5) + 6 項。 |
| §A-3 項境界一致 (A-項 vs B0-項) | mismatch **0** |
| §5 M≫K | M=200, K=10 (M≈K 禁止) |

## Results / 結果 (baseline, raw query)

| Condition | N | R@1 | R@3 | R@10 | MRR |
|---|---|---|---|---|---|
| **A-para** | 136 | 64.7% | 73.5% | **80.9%** | 0.699 |
| **B0-para** | 136 | 44.9% | 63.2% | 69.9% | 0.541 |
| A-art | 112 | 63.4% | 74.1% | 78.6% | 0.688 |
| B0-art | 112 | 50.0% | 62.5% | 71.4% | 0.572 |

**Primary — structured effect at paragraph granularity (A-para vs B0-para, paired, N=136):**

- ΔRecall@10 = **+0.110** (95% bootstrap CI **0.059–0.169**, excludes 0)
- ΔMRR = **+0.158**, McNemar exact **p < 0.001**, Wilcoxon (hit-pair conditional) p = 0.0017.

構造化は生本文より項粒度で Recall/MRR を有意に改善。query-canon 軸は完全中立（優劣は反転しない）。
`normalize`（略称展開）の効果は ±1pp と小。**N=136 のパイロットゆえ効果量を主報告し p 値単独で
断定しない**（§E）。粒度比較 (A-para vs A-art 等) は ≤2048 条サブセット (adopted-in-both) で
`stats.json` に記録。

## ⚠️ Reranker settings blocked / reranker 未実行 (環境要因)

`+reranker` / `+both` (16/32 runs) は本環境で **未実行**。`torch` が Windows で DLL ロード失敗
(`ImportError: DLL load failed while importing _C`, VC++ ランタイム欠落と推定) のため
`sentence-transformers` の cross-encoder (`bge-reranker-v2-m3`) が起動不能。**設計選択でなく環境ブロック**。
コードは reranker 対応済 (`layer1_run_pilot.py --ablations reranker both`)。torch が動く環境
(または GPU 機) で同コマンドを実行すれば残り 16 runs が埋まる。

## Files / 成果物

- `aggregate.json` — 条件×mode×ablation ごとの Recall@1/3/10・MRR・法令別内訳 (16 runs)
- `raw/{condition}__{qmode}__{ablation}.jsonl` — per-query raw ログ (dedup 前後・engine 認識 article_id 併記・gold 併記)。**共犯バグ封じの独立監査ソース (§F)**
- `stats.json` — McNemar + bootstrap CI + Wilcoxon + 法令別 (4 comparison × 8 setting)
- `build-guard.json` — §A ガード実測ログ (採用N・set-diff・token 除外・境界一致)

## Reproduce / 再現

```bash
PYTHONUTF8=1 python tools/embed/layer1_build_corpora.py            # 4 corpus + §A guards
for c in A-para A-art B0-para B0-art; do \
  python tools/embed/embed.py --input build/layer1-rawtext/layer1-$c.jsonl \
    --output build/layer1-rawtext/layer1-$c-embedded --provider gemini \
    --gemini-model gemini-embedding-001; done                       # 埋め込み (GEMINI_API_KEY 要)
python tools/embed/layer1_run_pilot.py --ablations baseline normalize  # retrieval + raw ログ
python tools/embed/layer1_stats.py                                  # paired 統計
```

Embeddings (`build/layer1-rawtext/*.npy`) are gitignored (§C 隔離出力)。結果 json / raw ログのみ commit。
