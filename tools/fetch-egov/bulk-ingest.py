#!/usr/bin/env python3
"""bulk-ingest.py — 複数法令を一括で fetch + parse + validate.

使い方:
    cd JuriCode-JP
    python tools/fetch-egov/bulk-ingest.py \
        --laws kenpou douro-koutsuu-hou shouhou kaisha-hou souzoku-zei-hou chihou-zei-hou \
        --cache-dir cache/laws \
        --data-root data

各法令について:
    1. e-Gov 法令API v2 から XML を取得 (cache-dir に保存)
    2. tools/parse/parse-egov.py を呼んで Markdown に変換 (data-root/<phase-dir>/<abbrev>/)
    3. tools/validate/validate-all.py で全データ検証

phase-dir は法令略称から推論:
    kenpou                       → phase1-foundational
    douro-koutsuu-hou            → phase1-police
    keihanzai-hou, stalker-*     → phase1-police
    shouhou, kaisha-hou          → phase2-commercial
    souzoku-zei-hou, chihou-zei-hou → phase1-tax
    (それ以外) → --default-phase 指定値、未指定なら phase1-misc
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# このスクリプトの場所から相対的に解決
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
sys.path.insert(0, str(SCRIPT_DIR / "src"))

try:
    from fetch_egov.law_id_map import LAW_ID_MAP, resolve_law_id
except ImportError as e:
    sys.exit(f"ERROR: cannot import law_id_map: {e}")

# 法令略称 → Phase ディレクトリ
PHASE_MAP: dict[str, str] = {
    # 憲法
    "kenpou": "phase1-foundational",
    # 警察関連
    "keihou": "phase1-police",
    "keiji-soshou-hou": "phase1-police",
    "keisatsu-hou": "phase1-police",
    "keisatsukan-shokumu-shikkou-hou": "phase1-police",
    "keihanzai-hou": "phase1-police",
    "stalker-kisei-hou": "phase1-police",
    "douro-koutsuu-hou": "phase1-police",
    # 民事 (実務家柱)
    "minpou": "phase1-practitioner",
    # 商事 (Phase 2 先取り)
    "shouhou": "phase2-commercial",
    "kaisha-hou": "phase2-commercial",
    # 税法
    "kokuzei-tsuusoku-hou": "phase1-tax",
    "houjin-zei-hou": "phase1-tax",
    "shotoku-zei-hou": "phase1-tax",
    "shouhi-zei-hou": "phase1-tax",
    "souzoku-zei-hou": "phase1-tax",
    "chihou-zei-hou": "phase1-tax",
    # 行政
    "chihou-jichi-hou": "phase1-administrative",
    "gyousei-tetsuzuki-hou": "phase1-administrative",
    "gyousei-fufuku-shinsa-hou": "phase1-administrative",
}

EGOV_API_BASE = "https://laws.e-gov.go.jp/api/2/law_data/"
USER_AGENT = "JuriCode-JP/0.2 (+https://github.com/JuriCode-JP) bulk-ingest"


def phase_dir_for(abbrev: str, default_phase: str) -> str:
    """法令略称から Phase ディレクトリを推論."""
    return PHASE_MAP.get(abbrev, default_phase)


def fetch_law_xml(law_id: str, cache_dir: Path, force: bool = False) -> Path:
    """e-Gov v2 API から XML を取得 (キャッシュあれば再利用)."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / f"{law_id}.xml"
    if out_path.exists() and not force:
        size = out_path.stat().st_size
        print(f"  [cache hit] {out_path} ({size:,} bytes)")
        return out_path

    url = f"{EGOV_API_BASE}{law_id}"
    print(f"  [fetch] {url}")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/xml, text/xml, */*"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code} for {url}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error for {url}: {e.reason}") from e

    # e-Gov v2 may return JSON wrapper or raw XML. Detect.
    text = data.decode("utf-8", errors="replace")
    if text.lstrip().startswith("{"):
        # JSON envelope. Extract law_full_text or similar.
        import json as _json

        env = _json.loads(text)
        # v2 envelope has "law_full_text" containing the XML root <Law>
        xml = env.get("law_full_text") or env.get("LawFullText") or env.get("data")
        if isinstance(xml, dict):
            # nested
            xml = xml.get("law_full_text") or xml.get("LawFullText")
        if not xml:
            raise RuntimeError(
                f"JSON envelope unexpected for {law_id}: keys={list(env.keys())}"
            )
        out_path.write_text(xml, encoding="utf-8")
    else:
        out_path.write_text(text, encoding="utf-8")

    size = out_path.stat().st_size
    print(f"  [saved] {out_path} ({size:,} bytes)")
    return out_path


def parse_one(
    xml_path: Path,
    abbrev: str,
    law_id: str,
    data_root: Path,
    phase: str,
) -> tuple[int, Path]:
    """parse-egov.py を呼び出して Markdown を生成. 生成条文数を返す."""
    out_dir = data_root / phase / abbrev
    parse_script = REPO_ROOT / "tools" / "parse" / "parse-egov.py"
    cmd = [
        sys.executable,
        str(parse_script),
        "--input",
        str(xml_path),
        "--output",
        str(out_dir),
        "--abbrev",
        abbrev,
        "--law-id",
        law_id,
        "--force",
    ]
    print(f"  [parse] -> {out_dir}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise RuntimeError(f"parse-egov failed for {abbrev}: exit {proc.returncode}")
    # 条文数カウント
    n = len(list(out_dir.glob(f"{abbrev}-article-*.md")))
    print(f"  [parsed] {n} articles")
    return n, out_dir


def run_validate(data_root: Path) -> bool:
    """tools/validate/validate-all.py を実行."""
    validate_script = REPO_ROOT / "tools" / "validate" / "validate-all.py"
    if not validate_script.exists():
        # try alternate name
        cands = list((REPO_ROOT / "tools" / "validate").glob("validate-all*.py"))
        if cands:
            validate_script = cands[0]
        else:
            print(f"  [warn] validate-all script not found, skipping")
            return True
    print(f"\n=== running {validate_script.name} ===")
    proc = subprocess.run(
        [sys.executable, str(validate_script), "--data-root", str(data_root)],
        capture_output=False,
    )
    return proc.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument(
        "--laws",
        nargs="+",
        required=True,
        help="略称リスト (例: kenpou douro-koutsuu-hou shouhou)",
    )
    ap.add_argument(
        "--cache-dir",
        type=Path,
        default=REPO_ROOT / "cache" / "laws",
        help="XML キャッシュ先 (default: cache/laws/)",
    )
    ap.add_argument(
        "--data-root",
        type=Path,
        default=REPO_ROOT / "data",
        help="Markdown 出力 root (default: data/)",
    )
    ap.add_argument(
        "--default-phase",
        type=str,
        default="phase1-misc",
        help="PHASE_MAP に無い略称のフォールバック Phase",
    )
    ap.add_argument("--force-fetch", action="store_true", help="キャッシュ無視で再取得")
    ap.add_argument("--skip-validate", action="store_true", help="最後の validate-all をスキップ")
    ap.add_argument("--sleep-between", type=float, default=2.0, help="法令間の待機秒数 (default 2.0)")
    args = ap.parse_args()

    print(f"REPO_ROOT     = {REPO_ROOT}")
    print(f"cache-dir     = {args.cache_dir}")
    print(f"data-root     = {args.data_root}")
    print(f"laws          = {args.laws}")
    print()

    summary: list[tuple[str, str, int, str]] = []  # (abbrev, law_id, n_articles, status)
    failures = 0

    for i, abbrev in enumerate(args.laws, 1):
        print(f"\n=== [{i}/{len(args.laws)}] {abbrev} ===")
        try:
            law_id = resolve_law_id(abbrev)
        except KeyError as e:
            print(f"  [skip] {e}")
            summary.append((abbrev, "?", 0, "unknown-abbrev"))
            failures += 1
            continue

        phase = phase_dir_for(abbrev, args.default_phase)
        print(f"  law_id = {law_id}")
        print(f"  phase  = {phase}")
        try:
            xml_path = fetch_law_xml(law_id, args.cache_dir, force=args.force_fetch)
            n, out_dir = parse_one(xml_path, abbrev, law_id, args.data_root, phase)
            summary.append((abbrev, law_id, n, "ok"))
        except Exception as e:
            print(f"  [FAIL] {e}", file=sys.stderr)
            summary.append((abbrev, law_id, 0, f"fail: {e}"))
            failures += 1

        if i < len(args.laws) and args.sleep_between > 0:
            time.sleep(args.sleep_between)

    print("\n" + "=" * 70)
    print("INGESTION SUMMARY")
    print("=" * 70)
    total = 0
    for abbrev, law_id, n, status in summary:
        flag = "OK" if status == "ok" else "FAIL"
        print(f"  [{flag:4}] {abbrev:40} {law_id:20} {n:>5} articles  {status}")
        if status == "ok":
            total += n
    print(f"\n  TOTAL: {total:,} articles (failures: {failures})")

    if failures > 0:
        print("\nWARNING: some laws failed. See output above.")

    if not args.skip_validate and failures == 0:
        ok = run_validate(args.data_root)
        if not ok:
            print("\nWARNING: validate-all reported failures.")
            sys.exit(1)

    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
