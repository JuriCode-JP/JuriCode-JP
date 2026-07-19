# juricode-verifier

Domain-independent source-citation verification for legal RAG systems.
法令 RAG のための、ドメイン非依存の「出典検証」ライブラリ。

Part of [JuriCode-JP](https://github.com/JuriCode-JP/JuriCode-JP). MIT licensed. Zero third-party dependencies (stdlib only, Python 3.11+).

## What it verifies / 何を検証するか

| API | Verifies |
|---|---|
| `snap_quote(anchor, body)` | Locates an LLM-provided anchor in the source body and cuts the quote from the **original bytes**. The LLM never emits the quote itself, so the quote is verbatim [G2] by construction. Returns `None` when the anchor is not locatable (paraphrase / hallucination). |
| `check_citations_exist(citations, allowed_chunk_ids)` | **G1**: every cited `chunk_id` is a member of the set of chunks actually provided to the LLM (no fabricated sources). |
| `check_quotes_verbatim(citations, chunk_texts)` | **G2**: every `quote` is a verbatim [G2] byte substring of its source body. With server-side snapping this is an invariant check; a mismatch is reported as an implementation bug (fail-loud). |
| `valid_citations_only(citations, allowed_chunk_ids, chunk_texts)` | Filters citations down to those passing G1+G2 (for safe fallback responses). |
| `verify_text_hash(canonical_text, expected_sha256)` | The sha256 of a canonical text matches the value locked in a source manifest (proof that the corpus text is unaltered from its primary source). Canonicalization itself is the caller's responsibility. |

All checks are pure functions returning structured `Violation(code, detail)` values. The caller decides what to do on violation (drop the citation, regenerate, fall back).

- `snap_quote` は LLM の anchor（引用したい箇所の目印）を原文中に位置特定し、**原文のバイト列**を引用として切り出します。引用文を LLM に打たせないため、引用は構造上必ず逐語一致 [G2] になります。
- `check_citations_exist`（G1）は「LLM に渡していない出典の捏造」を、`check_quotes_verbatim`（G2）は「引用の改変」を機械的に検出します。
- `verify_text_hash` は「corpus 本文が一次ソースから改変されていないこと」を manifest のロック値との照合で証明します（canonicalize は呼び出し側の責務）。

## What it does NOT verify / 検証しないもの

- **Answer correctness.** This package proves that citations are faithful to their sources; it does not prove the answer built on them is right.
- **Application policy.** Assertion bans, numeric-output bans, tense disclaimers, professional-practice notices and similar rules are application policy, not source verification. Keep them in your application layer.

（回答の正しさ・アプリ固有のポリシーは検証対象外です。本パッケージは「出典の忠実性」だけを検証します。）

## Install

Not on PyPI yet. Install from the monorepo subdirectory:

```bash
pip install "juricode-verifier @ git+https://github.com/JuriCode-JP/JuriCode-JP.git#subdirectory=packages/juricode-verifier"
```

## Usage

```python
from juricode_verifier import (
    Violation,
    check_citations_exist,
    check_quotes_verbatim,
    snap_quote,
    verify_text_hash,
)

# 1. Server-side quote snapping: LLM emits only {chunk_id, anchor}
quote = snap_quote(anchor="急迫不正の侵害に対して", body=chunk_body)  # verbatim or None

# 2. Verify citations (pure functions -> list[Violation])
violations = []
violations += check_citations_exist(citations, allowed_chunk_ids=set(chunk_texts))
violations += check_quotes_verbatim(citations, chunk_texts)

# 3. Prove the source text is unaltered from its manifest-locked hash
v = verify_text_hash(canonical_text, expected_sha256=manifest_entry["ja_text_sha256"])
if v is not None:
    violations.append(v)
```

## Versioning

Semver. `0.x` may change APIs between minor versions; pin the version (or commit) you depend on.
