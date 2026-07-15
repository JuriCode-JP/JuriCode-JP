#!/usr/bin/env python3
"""scan_artifacts.py -- 配布物 (HF へ上げるファイル) を公開前に走査する.

Why これが要るのか:
    leak-gate は **公開リポのソース差分** にはかかっているが、**配布物の中身** には
    かかっていなかった。索引の meta.jsonl (48.7 MB) や registry の documents/chunks は
    「外向けに検査されたことが一度も無いファイル」である。
    そして HF への公開は取り消せない (消しても履歴とキャッシュに残る)。

    検査範囲の外にあるものは、永久に見えない。配布物を検査範囲に入れる。

出力の作法:
    「0 件」とだけ言わない。**何を何パターン走査して 0 件だったか** を出す。
    走査していないものは「検出しなかった」ではなく「見ていない」である。

なぜ「0 件」なのか (2026-07-15 の実測経緯・半年後の自分のために残す):
    索引 v9 + registry-2026-07 を HF に公開する前に、このスキャナの原型を走らせた。
    そのときの `internal-doc-number` パターンは `\\d{3}_` (3 桁 + アンダースコア) で、
    **ヒットが出た**。ヒットを消すためにパターンを緩めたのではなく、全件を実物で読み、
    「内部 doc 連番」と「法令の枝番条」という **別種のものが同じ形をしていた** ことを
    確認して、両者を分離した。分離後の再実測:

      - meta.jsonl に 43 行ヒット / 異なり 33 種。全 33 種を実 ID で列挙し、対応する
        法令・条番号を確認した (例: `chihou-zei-hou-art-294_2-tbl1` = 地方税法 294 条の 2、
        `keiji-soshou-hou-art-494_2-tbl1` = 刑事訴訟法 494 条の 2)。表 chunk の id は
        枝番を `_` で表すため、`294_2` は「数字 _ 数字」になる。
      - .npy を「テキストとして」走査すると 9 件ヒットした。中身は float32 のバイト列が
        偶然 ASCII に見えたもの (`'583_'` `'3@9.Zl'` 等)。これは漏洩ではないが、握り潰す
        のも誤り。**検査方法そのものが間違っていた** ので、.npy は文字列走査をやめ、
        サイズ整合で「テキストを置ける隙間が 1 バイトも無い」ことを証明する形にした
        (scan_npy 参照)。
      - 最終形 (現在のパターン) で 5 ファイル・13 パターン: 検出 0 件。

    注意 (訂正): 当時チャットで「56 件 (44 + 12)」と報告したが、上記の再実測では
    43 + 9 = 52 であり、**56 は再現できない**。再現できない数字は根拠にしない。
    根拠として使うのは、このスクリプトを走らせて出る値だけである。

    パターンを変えるときは、必ず tests/test_scan_artifacts.py の負のコントロール
    (本物の内部 doc 連番を今も検出すること) を通すこと。検出を消す方向の変更は、
    それだけで「検査が仕事をしなくなった」状態と区別がつかない。
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

#: (名前, 説明, 正規表現)。行単位で走査する。
PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    (
        "windows-abs-path",
        "Windows のローカル絶対パス (C:\\Users\\... 等)",
        re.compile(r"[A-Za-z]:\\+(?:Users|Documents|Temp)\\", re.IGNORECASE),
    ),
    (
        "posix-local-path",
        "POSIX のローカル絶対パス (/mnt/, /home/, /Users/, /sessions/, /tmp/)",
        re.compile(r"(?:^|[\s\"'(])/(?:mnt|home|Users|sessions|tmp)/"),
    ),
    (
        "os-username",
        "OS ユーザ名 (このマシンのアカウント名)",
        re.compile(r"sala\.sa", re.IGNORECASE),
    ),
    (
        "person-name",
        "実名 (ローマ字・漢字)",
        re.compile(r"(?:MasahiroSato|Masahiro\s+Sato|佐藤|平川)"),
    ),
    (
        "internal-doc-number",
        "内部 doc 連番 (147_ClaudeCode のような 3 桁 + _ + 英字/日本語)",
        # 「数字 3 桁 + _ + **英字または日本語**」だけを拾う。
        # Why 数字を除くか: 法令の枝番条は表 chunk の id で "294_2" (地方税法 294 条の 2)
        # のように **数字 _ 数字** で表される。294_2 / 314_6 / 144_3 など 33 種・43 行を
        # 実物で列挙して確認した (2026-07-15)。これらは配布物の正当な内容であり、
        # 内部 doc 連番ではない。数字で終わるものを除外して両者を分離する。
        # (パターンを緩めて検出を消したのではなく、別物を別物として区別した)
        # 負のコントロールは tests/test_scan_artifacts.py にある。
        re.compile(r"(?:^|[\s\"'(/\\])\d{3}_[A-Za-z぀-ヿ一-鿿]"),
    ),
    (
        "internal-tool-name",
        "内部ツール名・内部運用語",
        re.compile(
            r"(?:Cowork|司令塔|_SESSION_BRIEFING|planning-checklist|briefing)", re.IGNORECASE
        ),
    ),
    (
        "internal-path",
        "内部ディレクトリ由来のパス (business/ / awards/)",
        re.compile(r"(?:^|[\s\"'(/\\])(?:business|awards)/"),
    ),
    (
        "google-api-key",
        "Google API キー (AIza...)",
        re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    ),
    (
        "hf-token",
        "Hugging Face トークン (hf_...)",
        re.compile(r"\bhf_[0-9A-Za-z]{20,}"),
    ),
    (
        "openai-key",
        "OpenAI 形式のキー (sk-...)",
        re.compile(r"\bsk-[0-9A-Za-z]{20,}"),
    ),
    (
        "aws-key",
        "AWS アクセスキー ID",
        re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    ),
    (
        "generic-secret-assign",
        "秘密情報らしき代入 (token=... / api_key=... / password=...)",
        re.compile(
            r"(?i)\b(?:token|api[_-]?key|secret|password)\b\s*[:=]\s*[\"']?[0-9A-Za-z_\-]{16,}"
        ),
    ),
    (
        "private-email",
        "メールアドレス",
        re.compile(r"[0-9A-Za-z._%+\-]+@[0-9A-Za-z.\-]+\.[A-Za-z]{2,}"),
    ),
]


def scan_file(path: Path) -> tuple[int, list[tuple[str, int, str]]]:
    """(走査した行数, [(パターン名, 行番号, 抜粋)]) を返す."""
    hits: list[tuple[str, int, str]] = []
    n_lines = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f, 1):
            n_lines += 1
            for name, _desc, rx in PATTERNS:
                m = rx.search(line)
                if m:
                    hits.append((name, i, m.group(0)[:60]))
    return n_lines, hits


def scan_npy(path: Path) -> tuple[int, list[tuple[str, int, str]]]:
    """.npy は「テキスト領域が存在しないこと」をサイズ整合で証明する.

    Why 文字列走査ではだめか:
        float32 のバイト列は、6 バイト以上にわたって偶然 ASCII 可読になることがある
        (実測: 143,749 x 3,072 の索引で 3,886,546 個の "ASCII 文字列" が現れ、その中に
        '369_t' や '3@9.Zl' のようにパターンへ当たるものが 4 件あった)。これを
        「漏洩の疑い」と報告するのは誤りだし、逆に手で握り潰すのも誤り。

    正しい検査:
        .npy は [magic 6B][ver 2B][hlen 2B][header][payload] という構造で、
        payload は dtype x shape で **バイト数が決まる**。
            実ファイルサイズ - ヘッダ長 == rows x cols x itemsize
        が成り立てば、**テキストを置ける隙間が 1 バイトも無い**ことが言える。
        成り立たなければ余分なバイトがあるので、そこを走査する。
    """
    data = path.read_bytes()
    if data[:6] != b"\x93NUMPY":
        raise ValueError(f"not a .npy file: {path}")
    hlen = int.from_bytes(data[8:10], "little")
    header = data[10 : 10 + hlen].decode("ascii")
    off = 10 + hlen

    m = re.search(r"'shape':\s*\((\d+),\s*(\d+)\)", header)
    d = re.search(r"'descr':\s*'([^']+)'", header)
    if not m or not d:
        raise ValueError(f"cannot parse .npy header: {header!r}")
    rows, cols = int(m.group(1)), int(m.group(2))
    itemsize = int(d.group(1)[-1])  # '<f4' -> 4
    expect = rows * cols * itemsize
    actual = len(data) - off

    hits: list[tuple[str, int, str]] = []
    if actual != expect:
        hits.append(
            (
                "npy-extra-bytes",
                0,
                f"payload {actual:,} B != {rows}x{cols}x{itemsize} = {expect:,} B "
                f"(差 {actual - expect:+,} B) -- 余分な領域がある",
            )
        )
    return rows, hits


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--max-report", type=int, default=10)
    args = ap.parse_args()

    print(f"=== 走査パターン: {len(PATTERNS)} 種 ===")
    for name, desc, _rx in PATTERNS:
        print(f"  - {name:24s} {desc}")

    print("\n=== 走査対象 ===")
    total_hits = 0
    for p in args.files:
        if not p.exists():
            print(f"  MISSING {p}", file=sys.stderr)
            return 1
        binary = p.suffix == ".npy"
        n_units, hits = (scan_npy if binary else scan_file)(p)
        unit = "行 (ベクトル)" if binary else "行"
        size = p.stat().st_size
        print(f"\n  {p.name}  ({size:,} B / {n_units:,} {unit})")
        if hits:
            total_hits += len(hits)
            for name, i, excerpt in hits[: args.max_report]:
                print(f"    HIT [{name}] {unit} {i}: {excerpt}", file=sys.stderr)
            if len(hits) > args.max_report:
                print(f"    ... 他 {len(hits) - args.max_report} 件", file=sys.stderr)
        elif binary:
            print("    テキスト領域 0 バイト (ヘッダ + float payload のサイズが完全一致)")
        else:
            print(f"    検出 0 件 ({len(PATTERNS)} パターンすべてを適用)")

    print(f"\n=== 合計: {total_hits} 件検出 ===")
    if total_hits:
        print("STOP: 配布物に漏洩の疑いがある文字列がある。公開は取り消せない。", file=sys.stderr)
        return 1
    print("公開可 (走査した範囲では検出 0)。走査していない観点は上のパターン一覧の外にある。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
