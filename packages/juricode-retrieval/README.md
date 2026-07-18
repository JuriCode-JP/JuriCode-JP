# juricode-retrieval

Dense-retrieval core for JuriCode-JP, packaged (MIT) as the single source of
truth for the parity-critical primitives.

## What it provides

| primitive | purpose |
|---|---|
| `_load_artefacts` | Load the embedding matrix (`.npy`), records (`.meta.jsonl`), and provider state (`.vec.json`, `.vec.pkl` fallback). Missing artefacts fail loudly. |
| `_encode_queries` | Embed query strings via the artefact's provider (gemini / openai / tfidf). The openai and gemini clients are imported lazily. |
| `_cosine_topk` | Cosine-similarity top-k of a query matrix against the corpus matrix. |
| `dedup_by_article` | Collapse duplicate segments of the same article to the top-ranked one. |

## Why a package

`tools/embed/retrieve.py` re-imports these four objects, so every eval and
service caller runs the *identical* function objects rather than a copy. The
retrieval math is therefore unchanged by construction, and a test asserts the
object identity (`retrieve._load_artefacts is juricode_retrieval._load_artefacts`).

## Dependencies

`numpy` is required (imported lazily inside each primitive, so importing the
package itself needs no numpy). `google-genai` is the production embedding
provider; the `openai` and `tfidf` branches are optional and imported only when
selected.
