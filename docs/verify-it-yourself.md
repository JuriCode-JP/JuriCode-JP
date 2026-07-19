# Verify it yourself / 自分で再現する

The reason to trust JuriCode-JP is not our word — it is that you can re-run the
check. This page walks a third party from a fresh clone to watching the G0
fidelity gate report **0 violations** against the e-Gov XML that ships in the
repository. Nothing here is a claim you have to take on faith; every command
below was run in the repository before it was written down.

JuriCode-JP を信じる根拠は「信頼」ではなく「再実行」です。このページは、第三者が
fresh clone から忠実性ゲートを自分で走らせ、リポジトリ同梱の e-Gov XML に対して
**違反 0 件**を自分の目で確認するまでを辿ります。以下のコマンドはすべて、記載前に
このリポジトリで実際に実行しています。

## What this proves / これが示すこと

The gate machine-checks the chain *source XML → canonical Markdown → derived
chunks*, in separated stages (the stages are never summed):

- **G0-a** — the article body in the canonical Markdown equals the e-Gov XML
  article body, exact after whitespace collapsing [G0-a]. XML と正本 md の一致。
- **G0-b** — the canonical Markdown equals its derived retrieval chunks, exact
  after whitespace collapsing [G0-b]. 正本 md と派生チャンクの一致。
- **G0-c** — every chunk body is a substring of its parent article body, and
  the strict variant checks that substring byte-for-byte [G0-c]. チャンクが親
  条文本文の部分列であること（strict はバイト単位）。

### What this does NOT prove / これが示さないもの

- Translation quality and which statutes were selected are **out of scope** —
  the gate is about text fidelity, not editorial judgement. 訳の質・法令の選定は
  対象外です。
- Fields labelled `egov-xml-derived` or `juricode-stored-text` carry a **weaker
  guarantee than the main-provision body**: only the main-provision body text is
  under the G0 gate above. `egov-xml-derived`・`juricode-stored-text` は本則本文
  より弱い保証です。

## Prerequisites / 前提

- Python 3.11 or 3.12 (matches the CI matrix and the README badge).
- `git` and a fresh clone:

  ```
  git clone https://github.com/JuriCode-JP/JuriCode-JP.git
  cd JuriCode-JP
  ```

- Install the package with its dev extras (this is what CI installs):

  ```
  python -m pip install --upgrade pip
  pip install -e ".[dev]"
  ```

## The ground truth ships with the repo / 正解データは同梱されています

The e-Gov source XML is **version-controlled** under `cache/laws/` (58 XML
files). Because the ground truth travels with the clone, you re-run against the
same input we did — the result is not sensitive to a network fetch or a moving
upstream. 正解データの e-Gov XML は `cache/laws/`（58 XML）に版管理されているため、
第三者が同じ入力で再現できます。

## Reproduce it / 再現する

There are two ways in, and both were run before this page was written.

### A. The whole pipeline, exactly as CI runs it / CI と同一の全体再現

```
python tools/scripts/run-ci.py
```

This reproduces every CI step locally, including the `fidelity-gate` job:
rebuild the derived chunks from the versioned Markdown and source XML, then run
the gate over them. Green here means green in CI.

### B. The fidelity check only, the shortest path / 忠実性だけを直接回す最短道

Build the derived chunks, then run the gate (the gate writes its report under
`build/fidelity-report/`, which is gitignored):

```
python tools/parse/v0.2/build_chunks_from_md.py
python tools/parse/v0.2/extract_table_from_xml.py
python tools/parse/v0.2/g0_fidelity_gate.py --out-dir build/fidelity-report
```

## Expected result / 期待される結果

The gate exits **0** when every stage matches with **0 violations**. If a single
line fails to match, the gate exits **1** — an alteration is caught mechanically.
The verdict follows the findings (`exit = 1 if any violation else 0`).

On this repository the gate reports (excerpt of the real output):

```
# G0 忠実性ゲート diff レポート (Phase 0)

- 対象法令: 58 (XML 不在で skip: 0)
- XML 本則条文: 16332 / md 条文: 16332

## G0-a: e-Gov XML <-> 正本 md (chunk と合算しない)
- 完全一致: 16332
- 不一致: 0

## G0-b: 正本 md <-> chunks
- 完全一致: 16332
- 不一致: 0

## G0-c: chunk ⊂ 親条文本文
- 違反 (親本文の部分列でない chunk): 0

## G0-d: ルビ (振り仮名) の読みが本文に混入していないか
- 混入している条: 0

## 判定 (verdict)
- violation total: 0
- exit: 0
```

Every match/violation count above is a count, not an accuracy figure — you
should see the same **0** violations and **exit 0** on your clone. 一致件数・
違反件数はそのまま再現され、違反 0・exit 0 になるはずです。

## Where the gate lives in CI / CI 上のゲートの場所

The same check runs on every pull request as the **`fidelity-gate`** job
("Build derived chunks and verify fidelity") in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml). Each PR rebuilds the
derived chunks from source and re-runs the gate, so reproducibility and fidelity
are verified together on every change. 毎 PR で同じことが走ります。

## How to report a mismatch / 不一致の報告方法

If your run reports a violation that ours does not, that is exactly the signal
this project wants. Open a
[Law Data Correction issue](https://github.com/JuriCode-JP/JuriCode-JP/issues/new?template=data-correction.yml)
and include the law, the article, and the gate output. 違反を見つけたら、上記の
修正報告 issue で法令・条・ゲート出力を添えて知らせてください。
