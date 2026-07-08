#!/usr/bin/env python3
"""build-hojin-precedents.py -- 法人税裁決 store から判例 store を機械導出する.

Why: 国税不服審判所の裁決 store (data/v0.2/case-law/hojin/rulings.jsonl) の cited_refs には
《参考判決・裁決》として裁判所判例が引用されている。この引用エッジから裁判所判例 (precedent)
を機械抽出し、判例 store (precedents.jsonl) に永続化する。MVP は完全機械的で web fetch を一切
せず、judgment メタ (裁判所/年月日/掲載誌) と被引用エッジ (cited_by) だけを構造化する。要約
(summary_ja) と courts.go.jp permalink 取得は後段 FU (L3 / 要 fetch) に委ねる。

rulings.jsonl は非改変。引用エッジは precedent 側 cited_by に逆向きで持たせる。

Usage:
    python tools/parse/build-hojin-precedents.py
    python tools/parse/build-hojin-precedents.py --check-only   # 差分があれば非0で終了
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path

_THIS_FILE = Path(__file__).resolve()
_REPO_ROOT = _THIS_FILE.parent.parent.parent
_SHARED_SRC = _REPO_ROOT / "tools" / "shared" / "src"
if str(_SHARED_SRC) not in sys.path:
    sys.path.insert(0, str(_SHARED_SRC))

from juricode_shared import (  # noqa: E402
    PrecedentStoreEntry,
    normalize_fullwidth_digits,
    safe_write_jsonl,
)

_RULINGS_PATH = _REPO_ROOT / "data" / "v0.2" / "case-law" / "hojin" / "rulings.jsonl"
_PRECEDENTS_PATH = _REPO_ROOT / "data" / "v0.2" / "case-law" / "hojin" / "precedents.jsonl"
_KFS_PARSER_PATH = _REPO_ROOT / "tools" / "parse" / "parse-kfs-saiketsu.py"


def _load_wareki_to_iso():
    """ハイフン名モジュール parse-kfs-saiketsu.py から wareki_to_iso を importlib で読む.

    Why: 和暦->西暦変換は既に KFS パーサで実証済 (parse-kfs-saiketsu.py:110)。judgment 日付も
    同じ元号ゆえロジックを重複させず流用する。ファイル名がハイフンで通常 import 不可のため
    spec_from_file_location を使う (test_kfs_saiketsu.py と同じ確立パターン)。
    """
    spec = importlib.util.spec_from_file_location("parse_kfs_saiketsu", _KFS_PARSER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.wareki_to_iso


_wareki_to_iso = _load_wareki_to_iso()

# 元号の略記 (掲載誌略記で頻出。例「平29年」) を正式名へ正規化してから wareki_to_iso に渡す.
_ERA_ABBR = {"平": "平成", "昭": "昭和", "令": "令和"}

# judgment 参照とみなす court トークン (裁決 cited_refs のうち裁判所判例のみを対象化).
_JUDGMENT_MARKERS = ("判決", "高裁", "最高裁", "地裁")

# 掲載誌 -> case_id slug.
_CITE_SLUG = {
    "民集": "minshu",
    "集民": "shumin",
    "訟月": "shomu",
    "税資": "zeishi",
    "刑集": "keishu",
    "行集": "gyoshu",
    "判時": "hanji",
    "判タ": "hanta",
}

# 市区 (裁判所名の接頭) -> 英名. 未登録の市区は fail-loud で後段 FU に surface する.
_CITY_EN = {
    "東京": "Tokyo",
    "大阪": "Osaka",
    "名古屋": "Nagoya",
    "広島": "Hiroshima",
    "福岡": "Fukuoka",
    "仙台": "Sendai",
    "札幌": "Sapporo",
    "高松": "Takamatsu",
    "神戸": "Kobe",
    "宇都宮": "Utsunomiya",
    "大分": "Oita",
    "横浜": "Yokohama",
    "京都": "Kyoto",
    "さいたま": "Saitama",
    "千葉": "Chiba",
    "静岡": "Shizuoka",
    "新潟": "Niigata",
    "金沢": "Kanazawa",
    "長野": "Nagano",
    "熊本": "Kumamoto",
}

# 審級 (裁判所種別) -> (case_id prefix, 正式名 suffix, 英名 suffix).
_LEVEL = {
    "高裁": ("hcj", "高等裁判所", "High Court"),
    "地裁": ("dcj", "地方裁判所", "District Court"),
    "家裁": ("fcj", "家庭裁判所", "Family Court"),
    "簡裁": ("smc", "簡易裁判所", "Summary Court"),
}

_DATE_RE = re.compile(r"(昭和|平成|令和|昭|平|令)(元|\d+)年(\d+)月(\d+)日")
_CITE_PAREN_RE = re.compile(r"（([^）]+)）")
# 市区 (接頭) を非貪欲に取り、最初の裁判所種別キーワードで区切る (.match で先頭アンカー).
# unicode 範囲リテラルを避け cp932-safe に保つ (U+9FFF 等が cp932 非対応のため範囲は使わない).
_COURT_RE = re.compile(r"(.+?)(高裁|地裁|家裁|簡裁)")


def parse_precedent_decision_date(raw: str) -> str:
    """judgment 参照文字列から判決日を ISO (YYYY-MM-DD) へ変換する (fail-loud).

    Why: 全角数字 (「平成５年」) と元号略記 (「平29年」) の双方が実データに出るため、全角正規化を
    前置し、略記元号を正式名へ正規化してから既存 wareki_to_iso へ渡す。抽出失敗は握りつぶさず
    ValueError を投げる (silent drop 防止)。
    """
    n = normalize_fullwidth_digits(raw)
    m = _DATE_RE.search(n)
    if not m:
        raise ValueError(f"judgment 日付抽出失敗 (fail-loud): {n}")
    era = _ERA_ABBR.get(m.group(1), m.group(1))
    return _wareki_to_iso(era, m.group(2), int(m.group(3)), int(m.group(4)))


def parse_court(raw: str) -> tuple[str, str, str]:
    """judgment 参照文字列から (裁判所正式名, 裁判所英名, case_id prefix) を返す (fail-loud).

    Why: case_id の審級 prefix (scj/hcj/dcj/fcj/smc) と court/court_en を単一の解析点で確定し、
    prefix と裁判所種別の不整合を構造的に排除する。未登録の市区は fail-loud で後段 FU に surface。
    """
    n = normalize_fullwidth_digits(raw)
    if n.startswith("最高裁"):
        return "最高裁判所", "Supreme Court of Japan", "scj"
    m = _COURT_RE.match(n)
    if not m:
        raise ValueError(f"裁判所抽出失敗 (fail-loud): {n}")
    city, level = m.group(1), m.group(2)
    if city not in _CITY_EN:
        raise ValueError(f"未登録の市区 (fail-loud, _CITY_EN に追記が必要): {city} <- {n}")
    prefix, ja_suffix, en_suffix = _LEVEL[level]
    court_ja = f"{city}{ja_suffix}"
    court_en = f"{_CITY_EN[city]} {en_suffix}"
    return court_ja, court_en, prefix


def parse_citation(raw: str) -> str:
    """judgment 参照文字列から掲載誌 citation (例「民集47巻9号5278頁」) を返す.

    Why: case_id の巻号頁部分は掲載誌 citation のみから抽出し、日付 (元号年/月/日) の数字混入を
    構造的に排除する。括弧内を優先、無ければ「判決」以降を citation とみなす。
    """
    n = normalize_fullwidth_digits(raw)
    mp = _CITE_PAREN_RE.search(n)
    if mp:
        return mp.group(1)
    return n.split("判決", 1)[-1].strip()


def generate_precedent_case_id(prefix: str, iso_date: str, citation: str) -> str:
    """(prefix, ISO 日付, citation) から判例 case_id を合成する.

    Why: 巻号頁は日付を含まない citation のみから抽出するため、日付数字の巻号混入を排除できる。
    非適合文字を除去し連続ハイフンを単一化して CASE_ID_PATTERN / precedent prefix 検証に適合させる。
    形式: {prefix}-{YYYY-MM-DD}-{掲載誌slug}-{巻号頁を - 連結}。
    """
    n = normalize_fullwidth_digits(citation)
    slug = next((s for j, s in _CITE_SLUG.items() if j in n), "unknown")
    nums = re.findall(r"\d+", n)
    num_suffix = "-".join(nums) if nums else "0"
    cid = f"{prefix}-{iso_date}-{slug}-{num_suffix}".lower()
    cid = re.sub(r"[^a-z0-9-]", "", cid)
    cid = re.sub(r"-+", "-", cid)
    return cid


def collect_judgment_refs(rulings_path: Path) -> dict[str, list[str]]:
    """rulings.jsonl の cited_refs から judgment 参照を集約し raw -> cited_by(裁決 case_id) を返す.

    Why: 同一 judgment を複数裁決が引用する場合 (被引用>1)、その全裁決 case_id を cited_by に忠実
    保持する。dedup は raw 文字列で行い、cited_by は決定論のためソートする。
    """
    edges: dict[str, list[str]] = {}
    with rulings_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            citing = rec["case_id"]
            for ref in rec.get("cited_refs", []):
                if any(marker in ref for marker in _JUDGMENT_MARKERS):
                    edges.setdefault(ref, [])
                    if citing not in edges[ref]:
                        edges[ref].append(citing)
    return {raw: sorted(cb) for raw, cb in edges.items()}


def build_entries(edges: dict[str, list[str]]) -> list[PrecedentStoreEntry]:
    """judgment 参照 -> PrecedentStoreEntry のリスト (case_id ソート済・決定論).

    Why: MVP は要約なし・permalink なしの構造レコードに徹する。source_license=public-domain
    (判決本文=著13条 PD)、summary_source=none、relevance=medium (deferred)、url 省略。
    """
    entries: list[PrecedentStoreEntry] = []
    for raw, cited_by in edges.items():
        iso_date = parse_precedent_decision_date(raw)
        court_ja, court_en, prefix = parse_court(raw)
        citation = parse_citation(raw)
        case_id = generate_precedent_case_id(prefix, iso_date, citation)
        entries.append(
            PrecedentStoreEntry(
                case_id=case_id,
                case_type="precedent",
                court=court_ja,
                court_en=court_en,
                citation=citation,
                decision_date=iso_date,
                relevance="medium",
                source_license="public-domain",
                summary_source="none",
                cited_by=cited_by,
            )
        )
    entries.sort(key=lambda e: e.case_id)
    return entries


def _serialize(entries: list[PrecedentStoreEntry]) -> list[dict]:
    return [e.model_dump(mode="json") for e in entries]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-only",
        action="store_true",
        help="生成結果が既存 precedents.jsonl と一致するか確認のみ (差分あれば非0)",
    )
    args = parser.parse_args()

    edges = collect_judgment_refs(_RULINGS_PATH)
    entries = build_entries(edges)
    records = _serialize(entries)

    ids = [e.case_id for e in entries]
    if len(ids) != len(set(ids)):
        raise ValueError(f"case_id が重複しています: {len(ids)} 件中ユニーク {len(set(ids))} 件")

    new_content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records)

    if args.check_only:
        if not _PRECEDENTS_PATH.exists():
            print(f"NG: {_PRECEDENTS_PATH} が存在しません")
            return 1
        current = _PRECEDENTS_PATH.read_text(encoding="utf-8")
        if current != new_content:
            print("NG: 生成結果が既存 precedents.jsonl と一致しません (再生成が必要)")
            return 1
        print(f"OK: {len(entries)} 判例 (byte 一致)")
        return 0

    safe_write_jsonl(_PRECEDENTS_PATH, records)
    print(f"Wrote: {_PRECEDENTS_PATH.relative_to(_REPO_ROOT)} ({len(entries)} 判例)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
