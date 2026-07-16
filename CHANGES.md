# CHANGES

Distribution log. Each entry records what was published, where, and the sha256 of every
file. **These hashes are the anchor**: they let anyone confirm that a file downloaded from
the distribution host is the file that was published, and that it has not been replaced
since.

---

## 2026-07 — index `v0.2-aug-v9-gemini` / `registry-2026-07`

The corpus was rebuilt to full fidelity against the source XML. Item-level (号) and
sub-item (細別) text is now first-class, and branch-numbered articles (e.g. 132-2) are
present; both were absent from the previous corpus. Every chunk's text is now a
contiguous byte span of its parent article, so a quotation drawn from a chunk can be
matched byte-for-byte against the canonical text.

Fidelity gates pass with zero violations:

| Gate | What it checks | Result |
|---|---|---|
| G0-a | e-Gov source XML vs canonical markdown | 16,332 exact / 0 mismatched |
| G0-b | canonical markdown vs retrieval chunks | 16,332 exact / 0 mismatched |
| G0-c | chunk text is a contiguous byte span of its parent (no whitespace collapsing) | 0 violations |
| G0-d | ruby readings not written into the statutory text | 0 |
| G0-e | no residue anywhere in the canonical file, including outside the body section | 0 |

Index: `gemini-embedding-001`, 3072 dimensions, 143,749 chunks.
Registry `pipeline_version`: `w6-registry/2026-07`.

Do not diff registries across `pipeline_version` values: a pipeline change alters how text
is chunked and hashed, so a row-by-row diff would measure the pipeline, not the law.

### Distribution

- Hugging Face — self-contained snapshot `2026-07/` (rev.4: `snapshot.json` manifest + index + corpus + registry): https://huggingface.co/datasets/JuriCode-JP/juricode-index/tree/main/2026-07
- Hugging Face — dataset root (previous layout, retained for compatibility): https://huggingface.co/datasets/JuriCode-JP/juricode-index
- GitHub Release — immutable audit anchor (`snapshot.json` + the three registry files): https://github.com/JuriCode-JP/JuriCode-JP/releases/tag/snapshot-2026-07

The self-contained snapshot's `snapshot.json` (sha256 `8beafc6883e72ff4493c551828f02d97ad38539a0b9bbea4d0ef08c3fb64bdd6`) records the sha256 of all seven distributed files (index, corpus, registry). The GitHub Release freezes that manifest and the three registry files, so the distribution stays verifiable against an anchor that cannot be silently replaced.

### SHA256

```
2c9eb223e6b5c117681e2022e043c0f408c0613e821e00c2e8d7c167f05f454b  index/v0.2-aug-v9-gemini.npy
aecdec7a790bb22667f3534b4fc4fe4f0c9f344588b9cc638cfc72dd289061fa  index/v0.2-aug-v9-gemini.meta.jsonl
178369c158082d8e67b1d5b29dfe16197a84b07d7f4547556550a1feb0c30432  registry/registry-2026-07/documents.jsonl
f948bfc942254d29b91c353bf49d181a944ddc6b2496d424c3dbb640f4acfedc  registry/registry-2026-07/chunks.jsonl
97fefc4749ad92231570e1b41867ad17f8bac1c853569b72fde25de07b6ad9b2  registry/registry-2026-07/_manifest.json
```

Each file was re-downloaded from the distribution host after upload and re-hashed; all
five matched the local originals.

### What is not distributed

The `.vec.pkl` form of the index is **not** published. It holds the same vectors as the
`.npy`, and unpickling executes arbitrary code in the reader's process. A project whose
value proposition is verifiability should not ship a format that asks the consumer to
trust it.

### Reproduce

```bash
python tools/dist/scan_artifacts.py <files>          # pre-publication scan of the artifacts
python tools/dist/publish_to_hf.py --index ... --registry-dir ... --snapshot ...
```

`publish_to_hf.py` re-downloads every file after upload and compares hashes; it exits
non-zero if any file differs.
