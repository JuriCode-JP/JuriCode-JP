# tools/registry — Citation Registry Builder (W6 MVP)

Deterministic (LLM-free, zero-API) builder for the **citation registry**: the
single ledger that maps every retrieval chunk to its canonical source document
with source metadata and a content hash. MCP `get_article` and the BQ exporter
consume this ledger only — they must not re-implement their own joins.

引用レジストリのビルダーです。**決定論・LLM 不使用・API 呼び出し 0**。
chunk → 正本文書 → 出典メタ＋ハッシュの台帳 2 ファイルを生成します。
MCP `get_article` と BQ exporter は**この台帳だけ**を引きます。

## Outputs (`build/registry/`, gitignored)

| File | Unit | Contents |
|---|---|---|
| `documents.jsonl` | one row per **document** (never per chunk) | `juri_id`, `layer`, `law_id`, `law_num`, `law_name_ja`, `article_number`, `version_date`, `decision_date`, `source_url`, `text_sha256`, `hash_basis`, `license`, `last_verified` |
| `chunks.jsonl` | one row per corpus chunk (child → parent) | `chunk_id`, `juri_id`, `layer`, `segment_type` |

Both files are sorted by `juri_id` (chunks tie-break on `chunk_id`); the CLI
builds twice and asserts byte identity before writing.

## `hash_basis` — what is verified vs. self-declared

**Do not read every `text_sha256` as "verified against the publisher".**
The basis is recorded per row and means exactly this:

| `hash_basis` | Layers | Meaning |
|---|---|---|
| `egov-xml-canonical` | statute / enforcement 本則条文 | Manifest `ja_text_sha256` copied **verbatim** (never recomputed here). Produced by the deterministic e-Gov XML round-trip pipeline and **CI-verified against the e-Gov source** (`tools/parse/verify.py`). |
| `egov-xml-derived` | 附則 (supplementary provisions) | Text comes from the same deterministic e-Gov XML parse, but 附則 have **no per-article manifest anchor yet** (FU-558), so the hash is computed here over the stored parse output. |
| `juricode-stored-text` | tsutatsu / taxanswer / ruling | sha256 of the text **we ingested** — a self-declared fingerprint. **NOT a comparison against the publisher's original** (NTA / KFS HTML). Upgrading this to a fetch-time source hash is FU-557. |

> 通達・タックスアンサー・裁決の `text_sha256` は `juricode-stored-text`＝
> 我々が取り込んだテキストの指紋であり、**発行元の原典と突合したものではない**。

## Per-layer document definition

The locked invariant: **`text_sha256` is the sha256 of exactly the text
`get_article` must return** for that `juri_id` (byte-identical). The builder
re-derives the text from the source and compares hashes for N samples per
layer on every run (`--sample-verify`, via `juricode_verifier.verify_text_hash`).

| Layer | `juri_id` | Document text (= hash target) | version_date | license |
|---|---|---|---|---|
| statute / enforcement | manifest `article_id` (corpus `_` branch ids normalized to `-`) | canonical ja text anchored by manifest hash | frontmatter (article-level) | e-Gov利用規約 (`docs/licensing.md` §1) |
| 附則 (suppl) | 条 unit: chunk_id minus 項-and-below suffixes (`-pN`/`-subN`/`-tblN`/`-wN`/`-rollup`) | `-rollup` chunk's `text_raw` if present, else `"\n"`-join of chunk `text_raw` in corpus order | **null** (附則 originate from amendment acts; not fabricated) | e-Gov利用規約 |
| tsutatsu | store `directive_id` | store row `text` | **null** (store has none) | store `license` |
| taxanswer | store `id` (= chunk_id minus `-subN`) | store row `text` | store `version_date` | store `license` |
| ruling | store `case_id` | `case_name_ja + "\n" + summary_ja` (K-1 lock) | **null** (`decision_date` is its own field, not a version) | store `source_license` (pdl-1.0) |

Missing metadata stays **null and is counted in the build report — never
fabricated**.

## Inputs (explicit allow-list, no rglob)

- `data/v0.2/**/_source-manifest.json` + article md frontmatter
- `cache/laws/{law_id}.xml` (`<LawNum>`, defusedxml)
- Layer stores under `build/chunks/` — enumerated by the allow-list constants
  in `build_registry.py`. A store-shaped entry outside the allow-list aborts
  the build (stale caches such as `build-chunks-backup` are known-ignored).
- `build/corpus-v9.jsonl` (chunk universe) / `build/corpus-v9-embed.jsonl`
  (row-aligned embed corpus). Two coverage gates run over the pair:
  - **forward** (`embed ⊆ chunks`): every embedded chunk must resolve in
    `chunks.jsonl`.
  - **reverse** (`chunks − embed`): every corpus chunk absent from the index
    must be a `-rollup` aggregation (`embed_skip=True` by design) or empty-text
    (nothing to embed). A body chunk in the gap — e.g. one stamped
    `embed_skip=True` by a future parser change — is a STOP (closes the
    G0-e-class hole the forward gate alone misses). The exclusion breakdown
    (`rollup_family` / `empty_text` / `total_gap`) is printed in the report.
    Skipped when `--index-coverage measure` (stale index).

## Run

```bash
python tools/registry/build_registry.py            # defaults; prints report
python tools/validate/check-source-url-anchors.py  # REQUIRED next step (see below)
python tools/registry/build_registry.py --sample-verify 50
pytest tools/registry/tests/test_build_registry.py  # hermetic (CI-safe)
```

### Article anchor gate — runs here, not in CI

`build_registry.py` gives every statute-layer article an e-Gov deep-link
anchor (`…/law/<law_id>#Mp-…-At_<N>`; see `egov_anchor_index.py`). The
whole-corpus check on those URLs is
`tools/validate/check-source-url-anchors.py`, and it must be run **immediately
after `build_registry.py`, on the `documents.jsonl` that run produced** — it
reads the ledger, so it can only run where the ledger exists.

That is the release/build process, not CI: CI never invokes
`build_registry.py` (the ledger lives under gitignored `build/`, and CI only
rebuilds the derived chunks). Wiring the whole-corpus gate into `ci.yml` would
mean adding a registry build to CI; until that exists, a release that skips
this step ships unverified links.

What each half proves:

| | where | proves |
|---|---|---|
| `check-source-url-anchors.py` | release, after every build | all 16,332 rows well-formed; every law has tracked XML (58/58) |
| `tests/test_egov_anchor_index.py`, `tests/test_build_registry.py` | CI, every PR | each anchor SHAPE stays correct (branch/nesting/flat/fallback) |
| `tools/probe/probe-egov-anchors.py` | manual, needs network | anchors resolve to the intended article in a real browser |

The gate fails on a malformed URL or a missing XML, and always prints
anchored / fallback / malformed counts — a fallback that is not reported is a
silent truncation, and a green gate here does **not** mean "every link
resolves" (only the probe can say that).

Hard stops (never downgraded to warnings): duplicate `juri_id`, orphan chunks,
statute sha mismatch, document-count drift vs. locked expectations,
embed-index coverage holes (forward AND reverse), unexpected store entries,
nondeterministic output.
`law_num` duplicate **values** across laws are WARN-only here (the BQ
exporter, where `law_num` is a key, owns the fatal check).
