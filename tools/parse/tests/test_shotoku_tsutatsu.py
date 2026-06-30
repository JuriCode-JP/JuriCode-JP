"""test_shotoku_tsutatsu.py -- 所得税法基本通達 (2 レベル) 取込のゲート (FU-523).

Why this test exists:
    所得税基本通達は法人税/消費税と違い番号が **2 レベル** (条-番号 = "204-1") で、markup は
    split-strong (<strong>2</strong>－1 本文 ... strong は条番号のみ)。さらに:
      - 条範囲の通達 (74・75-1) は番号先頭に中点「・」(U+30FB) を含み "_" へ正規化する。
      - 同一通達が隣接セクション両ページに本文一致で重複掲載される (62-1 が第60条/第62条)。
    本テストは合成 cp932 fixture (ネットワーク不要・CI-safe) で 2 レベル parse・「・」正規化・
    本文一致 dedup・形式ゲートの不変条件を pin する。**落ちたら直すのはパーサであって期待値ではない**。
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_THIS = Path(__file__).resolve()
_REPO_ROOT = _THIS.parents[3]
_PARSER = _REPO_ROOT / "tools" / "parse" / "parse-nta-tsutatsu.py"


def _import_parser():
    spec = importlib.util.spec_from_file_location("parse_nta_tsutatsu", _PARSER)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


# 所得税の markup: 条番号だけが <strong>、続く "－{番号}" 以降は平文 (split-strong = CASE B)。
_PAGE_TMPL = (
    '<html><head><meta charset="shift_jis"></head><body>\n'
    '<div id="bodyArea">\n<h1>{h1}</h1>\n{items}\n</div></body></html>'
)
# strong=先頭レベル、"－"(U+FF0D)+残り、全角空白、本文。
_ITEM_TMPL = "<h2>{title}</h2>\n<p><strong>{first}</strong>－{rest}　{body}</p>"


def _page(h1: str, *items: tuple[str, str, str, str]) -> bytes:
    """items: (first, rest, title, body) -> cp932 NTA-like HTML。

    番号 "204-1" は first="204", rest="1"。条範囲 "74・75-1" は first="74・75", rest="1"。
    """
    body = "\n".join(_ITEM_TMPL.format(first=f, rest=r, title=t, body=b) for f, r, t, b in items)
    return _PAGE_TMPL.format(h1=h1, items=body).encode("cp932")


def _write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _run(mod, cache_root: Path, out_dir: Path) -> tuple[int, list[dict]]:
    rc = mod.main(
        ["--circular", "shotoku", "--cache-root", str(cache_root), "--output-dir", str(out_dir)]
    )
    out = out_dir / "shotoku-kihon-tsutatsu.tsutatsu.chunks.jsonl"
    recs = []
    if out.exists():
        recs = [
            json.loads(line)
            for line in out.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    return rc, recs


# ===========================================================
# pure-function units
# ===========================================================


def test_directive_id_ok_two_level() -> None:
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["shotoku"]
    ok = mod._directive_id_ok
    assert ok("shotoku-kihon-tsutatsu-204-1", cfg)
    assert ok("shotoku-kihon-tsutatsu-2-4の2", cfg)  # 番号レベルの「の」枝番
    assert ok("shotoku-kihon-tsutatsu-74_75-1", cfg)  # 条範囲 (正規化後)
    assert not ok("shotoku-kihon-tsutatsu-204-1-1", cfg)  # 3 レベルは NG
    assert not ok("shotoku-kihon-tsutatsu-204", cfg)  # 番号欠落
    assert not ok("hojin-kihon-tsutatsu-204-1", cfg)  # 通達 prefix 不一致


def test_hojin_format_gate_unchanged_under_num_levels() -> None:
    """num_levels 駆動化後も 3 レベル通達の形式ゲートは不変 (回帰)."""
    mod = _import_parser()
    cfg = mod.CIRCULAR_CONFIGS["hojin"]
    ok = mod._directive_id_ok
    assert ok("hojin-kihon-tsutatsu-9-2-9", cfg)
    assert ok("hojin-kihon-tsutatsu-12の2-1-1", cfg)
    assert not ok("hojin-kihon-tsutatsu-9-2", cfg)  # 2 レベルは 3 レベル通達では NG


# ===========================================================
# parse (synthetic cp932 cache)
# ===========================================================


def test_two_level_split_strong_parse(tmp_path: Path) -> None:
    """split-strong の 2 レベル番号 (204-1) を CASE B で拾い directive_id 化する."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(
        root / "36" / "01.htm",
        _page(
            "〔共通関係〕",
            ("204", "1", "（適用）", "報酬料金の支払を受ける者の本文。"),
            ("204", "2", "（性質）", "報酬料金の性質を有するものの本文。"),
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0, "2 レベル番号が parse 失敗"
    assert [r["directive_number"] for r in recs] == ["204-1", "204-2"]
    assert recs[0]["directive_id"] == "shotoku-kihon-tsutatsu-204-1"
    assert recs[0]["title"] == "（適用）"
    assert recs[0]["text"].startswith("報酬料金の支払を受ける")


def test_middle_dot_range_normalized_to_underscore(tmp_path: Path) -> None:
    """条範囲 74・75-1 の中点「・」(U+30FB) を番号内だけ "_" へ正規化する."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(
        root / "16" / "02.htm",
        _page(
            "法第74条及び第75条関係",
            ("74・75", "1", "（その年に支払った社会保険料）", "支払った金額の本文。"),
            ("74・75", "2", "（前納した社会保険料等）", "前納の本文。"),
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["74_75-1", "74_75-2"]
    assert recs[0]["directive_id"] == "shotoku-kihon-tsutatsu-74_75-1"
    # 本文中の「・」は変えない (番号だけ正規化) — 本文に中点を入れて確認。
    assert "・" not in recs[0]["directive_number"]


def test_range_sort_keeps_physical_order(tmp_path: Path) -> None:
    """74_75 群が 73 群より前へ誤配置されない (先頭条番号 74 で安定ソート)."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(root / "16" / "01.htm", _page("法第73条関係", ("73", "10", "（甲）", "本文。")))
    _write(
        root / "16" / "02.htm",
        _page("法第74条及び第75条関係", ("74・75", "1", "（乙）", "本文。")),
    )
    _write(root / "16" / "03.htm", _page("法第76条関係", ("76", "1", "（丙）", "本文。")))
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    # 物理順: 73-10 < 74_75-1 < 76-1 (74_75 が先頭(0)へ潰れず 74 として並ぶ)。
    assert [r["directive_number"] for r in recs] == ["73-10", "74_75-1", "76-1"]


def test_identical_body_duplicate_deduped(tmp_path: Path) -> None:
    """同番号・本文一致の重複 (62-1 が第60条/第62条 両ページ) は 1 件に dedup."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    same_body = "法第62条第1項の規定により譲渡所得の金額の計算上控除すべき損失の本文。"
    _write(
        root / "12" / "03.htm",
        _page(
            "法第60条関係",
            ("60", "1", "（取得費）", "贈与等により取得した資産の本文。"),
            ("62", "1", "（災害損失の控除の順序）", same_body),
        ),
    )
    _write(
        root / "12" / "04.htm",
        _page("法第62条関係", ("62", "1", "（災害損失の控除の順序）", same_body)),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0, "本文一致の重複は fail-loud でなく dedup されるべき"
    nums = [r["directive_number"] for r in recs]
    assert nums == ["60-1", "62-1"], f"dedup 後の集合が不正: {nums}"
    assert nums.count("62-1") == 1


def test_same_id_different_body_fail_loud(tmp_path: Path) -> None:
    """同番号でも本文が **異なる** 重複は従来どおり fail-loud (rc=1)."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(root / "12" / "03.htm", _page("法第60条関係", ("62", "1", "（甲）", "本文甲。")))
    _write(root / "12" / "04.htm", _page("法第62条関係", ("62", "1", "（乙）", "本文乙は別物。")))
    rc, _ = _run(mod, root, tmp_path / "out")
    assert rc == 1, "本文相違の同番号重複は fail-loud (rc=1) であるべき"


def test_branch_number_two_level(tmp_path: Path) -> None:
    """番号レベルの「の」枝番 (2-4の2) を 2 レベルで拾う."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(
        root / "01" / "01.htm",
        _page(
            "〔居住者関係〕",
            ("2", "4", "（起算日）", "居住期間の計算の起算日の本文。"),
            ("2", "4の2", "（過去10年以内）", "過去10年以内の計算の本文。"),
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["2-4", "2-4の2"]
    assert recs[1]["directive_id"] == "shotoku-kihon-tsutatsu-2-4の2"


def test_amendment_marker_kansou_extracted(tmp_path: Path) -> None:
    """官房総務課系「官総」の末尾改正注記を amendment_note に分離する (FU-523 追加記号)."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(
        root / "01" / "01.htm",
        _page(
            "〔居住者関係〕", ("2", "1", "（住所）", "住所の意義の本文。（平30官総1-2により改正）")
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert recs[0]["amendment_note"] == "（平30官総1-2により改正）"
    assert recs[0]["text"] == "住所の意義の本文。"


def test_kyotsu_suffix_directive(tmp_path: Path) -> None:
    """共通通達 (36・37共-1 など) を拾い、中点を "_" 正規化して共を保持する."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(
        root / "05" / "11.htm",
        _page(
            "〔販売代金共通〕",
            ("36・37共", "1", "（収入金額共通）", "事業を営む者の本文。"),
            ("36・37共", "1の2", "（質屋営業）", "質屋営業の本文。"),
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert [r["directive_number"] for r in recs] == ["36_37共-1", "36_37共-1の2"]
    assert recs[0]["directive_id"] == "shotoku-kihon-tsutatsu-36_37共-1"


def test_wave_dash_range_normalized_not_to_hyphen(tmp_path: Path) -> None:
    """波ダッシュ条範囲 (23～35共-1) は "_" 正規化 (誤って "-" 化しレベルが崩れない)."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(
        root / "04" / "10.htm",
        _page(
            "〔各種所得共通〕",
            ("23～35共", "1", "（発明等の報償）", "業務上有益な発明の本文。"),
        ),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    # 波ダッシュは "_" へ (誤って "-" になると "23-35共-1" の 3 レベル化で形式ゲート違反)。
    assert recs[0]["directive_number"] == "23_35共-1"
    assert recs[0]["directive_id"] == "shotoku-kihon-tsutatsu-23_35共-1"


def test_wave_dash_in_body_text_preserved(tmp_path: Path) -> None:
    """本文中の波ダッシュ「1～3」は範囲表現として保持し "-" 化しない (本文非改変)."""
    mod = _import_parser()
    root = tmp_path / "shotoku"
    _write(
        root / "01" / "01.htm",
        _page("〔居住者関係〕", ("2", "1", "（住所）", "第1号～第3号に掲げる本文。")),
    )
    rc, recs = _run(mod, root, tmp_path / "out")
    assert rc == 0
    assert "～" in recs[0]["text"], "本文の波ダッシュが失われた (グローバル正規化の誤適用)"
