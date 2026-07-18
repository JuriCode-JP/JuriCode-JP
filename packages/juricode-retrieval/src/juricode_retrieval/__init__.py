"""juricode-retrieval: dense-retrieval core for JuriCode-JP.

Single source of truth for the parity-critical dense primitives that
tools/embed/retrieve.py re-imports, so every eval caller runs the identical
function objects (byte-invariance by construction, not by output comparison):

    _load_artefacts  : load the embedding matrix, records, and provider state
    _encode_queries  : embed query strings via the artefact's provider
    _cosine_topk     : cosine-similarity top-k over the corpus matrix
    dedup_by_article : collapse duplicate segments of one article to its top rank

numpy is imported lazily inside each primitive (never at module import), so this
package imports cleanly where numpy is absent; a caller that invokes a primitive
needs numpy (and, for the gemini/openai providers, that client) installed.
"""

from __future__ import annotations

from .artefacts import _load_artefacts
from .cosine import _cosine_topk
from .dedup import dedup_by_article
from .encode import _encode_queries

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "_cosine_topk",
    "_encode_queries",
    "_load_artefacts",
    "dedup_by_article",
]
