"""Artefact loading for dense retrieval.

Single source of truth for `_load_artefacts`, moved verbatim from
tools/embed/retrieve.py so retrieve.py can re-import the identical object.
numpy is imported lazily inside the function (it is not needed to import this
module), matching the original.
"""

from __future__ import annotations

import json
import pickle


def _load_artefacts(prefix):
    import numpy as np  # lazy import (FU-506)

    # NOTE: with_suffix() は "v0.2-gemini-17967" のようなドット含み名で
    # ".2-gemini-17967" を suffix と解釈して壊す。文字列連結で回避。
    npy_path = prefix.parent / (prefix.name + ".npy")
    meta_path = prefix.parent / (prefix.name + ".meta.jsonl")
    vec_json_path = prefix.parent / (prefix.name + ".vec.json")
    vec_pkl_path = prefix.parent / (prefix.name + ".vec.pkl")
    # .vec.json (portable {provider, model}, no unpickling) wins; .vec.pkl is
    # the fallback so existing local builds keep working. A distributed snapshot
    # ships only .vec.json. At least one of the two must exist.
    missing = [str(p) for p in (npy_path, meta_path) if not p.exists()]
    if not vec_json_path.exists() and not vec_pkl_path.exists():
        missing.append(f"{vec_json_path} or {vec_pkl_path}")
    if missing:
        raise FileNotFoundError(f"Missing artefact(s): {missing}")

    matrix = np.load(npy_path)
    records = []
    with meta_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    if vec_json_path.exists():
        state = json.loads(vec_json_path.read_text(encoding="utf-8"))
    else:
        with vec_pkl_path.open("rb") as fh:
            state = pickle.load(fh)
    return matrix, records, state
