# JuriCode-JP — 外部再現ランブック / External Reproduction Runbook

このドキュメントは、JuriCode-JP の**忠実性ゲート**を第三者が自分のマシンで再現し、
その pass/fail を自分の目で確認するための手順書です。主張を信じる必要はありません —
ゲートを回して、出力を読んでください。

This runbook lets a third party reproduce JuriCode-JP's **fidelity gates** on their own
machine and read the pass/fail themselves. You do not have to trust the claim; you run the
gate and read the output.

すべての入力（正本 Markdown・原典 XML・評価セット）はリポジトリに commit 済みです。
**clone するだけで再現でき、ネットワーク取得の手順はありません。**
Every input (canonical Markdown, source XML, evaluation set) is committed to the
repository. **A clone is enough to reproduce; there is no fetch step.**

---

## 0. 実行前提 / Before you run

- **すべてのコマンドはリポジトリのルートで実行します。`cd` でサブディレクトリへ移動しないでください。
  必ずフルパス（`python tools/...`）で叩きます。**
  All commands run from the repository root. Do not `cd` into a subdirectory. Always invoke
  with a full path (`python tools/...`).
- 理由 / Why: build スクリプトは相対パスで `build/` に派生物を書きます。カレントディレクトリを
  動かすと後続の G0 ゲートが `g0b_all_chunks_missing` で誤爆します。
  The build scripts write derivatives to `build/` via relative paths, so moving the working
  directory makes the later G0 gate misfire as `g0b_all_chunks_missing`.
- 必要環境 / Prerequisites: Python 3.11 または 3.12。build 段階は PyYAML を要します
  （`pip install pyyaml`）。verify スクリプト群は標準ライブラリのみで動きます。
  Python 3.11 or 3.12. The build step needs PyYAML (`pip install pyyaml`); the verify
  scripts are standard-library only.
- **`build/chunks/` を丸ごと削除しないでください（`rm -rf build/chunks` 禁止）。** このディレクトリには
  法令 corpus とは別系統の**再生成できないストア**（通達・タックスアンサー・裁決）が同居しています。
  build を再実行すると法令ストアだけを上書きするので、消さずにそのまま再実行すれば十分です。
  **Do not delete `build/chunks/` wholesale.** It also holds non-regenerable stores
  (circulars, tax answers, tribunal rulings) that are separate from the statute corpus.
  Re-running the build overwrites only the statute store, so just re-run without deleting.

---

## 1. これは何か / What this is

JuriCode-JP は「正本本文が e-Gov 原典と一致し、retrieval chunk がその正本の総和である」という
忠実性を主張します。本書はその主張を、あなた自身がゲートを回して検証するための導線です。

JuriCode-JP claims fidelity: the canonical text matches the e-Gov source, and the retrieval
chunks are exactly the sum of that canonical text. This runbook is how you verify that claim
by running the gates yourself, rather than taking it on faith. It exists to make
verifiability real for an outside party.

---

## 2. 入手（provenance）/ Getting the inputs

- リポジトリを clone すれば、再現に要る入力はすべて揃っています:
  正本 Markdown は `data/v0.2/`、原典法令 XML は `cache/laws/`、評価セットは `data/eval-set/`（MIT）。
  Cloning the repository gives you every input the reproduction needs: the canonical
  Markdown under `data/v0.2/`, the source law XML under `cache/laws/`, and the evaluation
  set under `data/eval-set/` (MIT).
- 出典 / Source provenance: 原典 XML は e-Gov 法令API v2（https://laws.e-gov.go.jp/api/2/）由来で、
  ライセンスは PDL1.0 です。e-Gov から取り直したい場合のクライアントは `tools/fetch-egov/` にありますが、
  これは**出典証明（provenance）としての案内**です。e-Gov は moving target のため、本書は commit 済みの
  固定 XML/Markdown による再現に特化し、再取得や差分検証の手順は扱いません。
  The source XML comes from e-Gov 法令API v2 (https://laws.e-gov.go.jp/api/2/) under PDL1.0.
  A client for refreshing from e-Gov lives in `tools/fetch-egov/`, but that is **provenance
  only**. e-Gov is a moving target, so this runbook pins the committed XML/Markdown and does
  not cover re-fetching or diffing.

---

## 3. build（派生 chunks の再生成）/ Rebuild the derived chunks

リポジトリのルートから:

```bash
pip install pyyaml
python tools/parse/v0.2/build_chunks_from_md.py
python tools/parse/v0.2/extract_table_from_xml.py
```

1 本目は正本 Markdown から retrieval chunk を一方向に導出し、2 本目は原典 XML から表 chunk を
加えます。どちらも `build/chunks/` の下に書き込みます。

The first derives retrieval chunks one-way from the canonical Markdown; the second adds table
chunks from the source XML. Both write under `build/chunks/`.

---

## 4. 忠実性ゲートを回す / Run the fidelity gates

```bash
python tools/parse/v0.2/g0_fidelity_gate.py
python tools/parse/v0.2/verify_table_parity.py
python tools/scripts/verify-eval-set-checksum.py
```

- `g0_fidelity_gate.py` — 三者一致（正本 Markdown == 原典 XML == 派生 chunk）を照合し、`violation total`
  を出力します。総数が zero なら exit 0、そうでなければ exit 1。緑（violation なし）＝忠実性が保たれている、
  という意味です。末尾の `判定 (verdict)` を自分の目で読んでください。
  Checks the three-way fidelity (canonical Markdown == source XML == derived chunks) and
  prints a `violation total`. It exits 0 when the total is zero, and 1 otherwise, so a green
  run means fidelity holds. Read the `判定 (verdict)` block yourself.
- `verify_table_parity.py` — 表 chunk を原典 XML と突き合わせます。
  Checks the table chunks against the source XML.
- `verify-eval-set-checksum.py` — 評価セットの整合を照合します（digest ロック型ゲートの
  ACTIVE/INACTIVE 挙動は §5 と同じ）。
  Checks the integrity of the evaluation set (its digest-locked active/inactive behaviour is
  the same as §5).

---

## 5. 合格線ロックを ACTIVE で再現（ネガティブ・コントロール必須）/ Reproduce the pass-line lock, actively

合格線（pass lines）は `gates/` にあり、リポジトリの**外**で保持される digest で anchor されています。
公開 digest は本リポジトリの **GitHub Release note** に掲示されます（メンテナが置きます）。
その値は**本書には意図的に書きません**。

The pass lines live in `gates/` and are anchored by a digest held **outside** the repository.
The public digest is published in the repository's **GitHub Release note** (the maintainer
places it there); it is deliberately **not** written in this document.

ゲートが本当に噛むことを自分で確かめるため、**赤→緑の対**を回してください:

To convince yourself the gate actually bites, run the **red→green pair**:

**(1) 未設定 → INACTIVE（何も検証していない）/ Unset → INACTIVE (verifies nothing)**

```bash
python tools/scripts/verify-gates-lock.py
```

現在の digest を印字し、「gate INACTIVE」の警告を出して exit 0 で終わります。
**これを「合格」と誤解しないでください** — 何も検証していません。
It prints the current digest, warns that the gate is inactive, and exits 0. **Do not mistake
this for a pass** — nothing was verified.

**(2) デタラメな値 → 赤（exit 1）/ Wrong value → red (exit 1)**

```bash
GATES_LOCK_SHA256=deadbeef python tools/scripts/verify-gates-lock.py
```

注入した値がディスク上のファイルと一致しないため exit 1 で落ちます。
Exits 1 because the injected value does not match the files on disk.

**(3) 正しい値 → 緑（exit 0）/ Correct value → green (exit 0)**

```bash
GATES_LOCK_SHA256=<GitHub Release note の値 / value from the Release note> python tools/scripts/verify-gates-lock.py
```

Release note の値を注入すると `OK` 行を出して exit 0。この赤→緑の対が「ロックは本物だ」という
あなた自身の証明です — もし `gates/` が改ざんされていれば (3) も落ちます。
Injecting the value from the Release note prints an `OK` line and exits 0. The red→green pair
is your own proof that the lock is real: if `gates/` were tampered with, step (3) would fail too.

> **Windows PowerShell**: `VAR=... command` のインライン形は使えません。先に
> `$env:GATES_LOCK_SHA256="..."` で変数を設定してからコマンドを叩いてください
> （解除は `Remove-Item Env:GATES_LOCK_SHA256`）。
> The inline `VAR=... command` form does not work; set `$env:GATES_LOCK_SHA256="..."` first,
> then run the command (clear it with `Remove-Item Env:GATES_LOCK_SHA256`).

---

## 6. 数値はどこ / Where the figures are

本書は意図的に**数値を持ちません**。retrieval 品質の定量的な指標とその定義は、公開されている
`benchmarks/` にあります — 指標の定義は `benchmarks/methodology.md`（Recall@K などを、固定の数字ではなく
K で定義）を、実測された各ランは `benchmarks/results/` を参照してください。定量的な主張はそちらにあり、
本書はゲートの回し方だけを示します。

This runbook is deliberately **figure-free**. The quantitative retrieval-quality metrics and
their definitions live in the open `benchmarks/` directory: see `benchmarks/methodology.md`
for the metric definitions (Recall@K and friends, stated in terms of K rather than a fixed
number) and `benchmarks/results/` for the measured runs. Any quantitative claim lives there;
this document only shows you how to run the gates.
