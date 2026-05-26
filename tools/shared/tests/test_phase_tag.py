"""test_phase_tag — juricode_shared.phase_tag の unit tests.

責務: phase_tag.py の純関数 2 つ (resolve_phase_from_path / rewrite_tags0_in_text)
について、計画書 §3.1 が要求する 6 観点を網羅:
  1. resolve_phase_from_path の正常/異常
  2. rewrite_tags0_in_text の基本動作 (置換 / 冪等 / 各種 ValueError)
  3. ★ frontmatter 範囲ガード (body 内の偽 tags ブロックを書き換えない)
  4. ★ BOM 検知 (option b、本 sweep スコープ外を明示)
  5. ★ 改行コード round-trip 不変性
  6. safe_write_text との往復

Why TDD 観点:
  実装 (phase_tag.py) よりこのテストを後に追加した形だが、テストケース自体は
  実装より前に設計書 §3.1 で確定済. 実装後にテストが通ることで設計と実装の
  乖離ゼロを担保.

参照:
  - business/fu-415-phase-tag-sweep-plan-2026-05-26.md §3.1
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from juricode_shared.phase_tag import (
    DEPRECATED_PHASE_TAG,
    PHASE_DIR_RE,
    resolve_phase_from_path,
    rewrite_tags0_in_text,
)
from juricode_shared.safe_write import safe_write_text


# -------------------------------------------------------------------------
# Fixture helpers
# -------------------------------------------------------------------------


def _make_v02_frontmatter(tag0: str, tag1: str = "auto-generated") -> str:
    """v0.2 corpus 標準フォーマットの最小限の .md テキストを返す."""
    return (
        "---\n"
        "law_id: 132AC0000000048\n"
        "law_name_ja: 商法\n"
        "law_name_en: Commercial Code\n"
        "article_number: '1'\n"
        "article_id: shouhou-art-1\n"
        f"tags:\n- {tag0}\n- {tag1}\n"
        "---\n"
        "\n"
        "# 商法 第1条\n"
        "\n"
        "## 原文 (日本語)\n"
        "\n"
        "### 第1条\n"
        "\n"
        "商人の営業、商行為その他商事については、他の法律に特別の定めがあるものを"
        "除くほか、この法律の定めるところによる。\n"
    )


# -------------------------------------------------------------------------
# 1. resolve_phase_from_path
# -------------------------------------------------------------------------


class TestResolvePhaseFromPath:
    """data/v0.2/<phase>/<abbrev>/<file>.md から phase を導出."""

    def test_normal_phase2_commercial(self, tmp_path: Path) -> None:
        data_root = tmp_path / "data" / "v0.2"
        md_path = data_root / "phase2-commercial" / "shouhou" / "shouhou-article-1.md"
        md_path.parent.mkdir(parents=True)
        md_path.touch()

        assert resolve_phase_from_path(md_path, data_root) == "phase2-commercial"

    def test_normal_phase1_administrative(self, tmp_path: Path) -> None:
        data_root = tmp_path / "data" / "v0.2"
        md_path = data_root / "phase1-administrative" / "chihou-jichi-hou" / "x.md"
        md_path.parent.mkdir(parents=True)
        md_path.touch()

        assert resolve_phase_from_path(md_path, data_root) == "phase1-administrative"

    def test_path_outside_data_root_raises(self, tmp_path: Path) -> None:
        data_root = tmp_path / "data" / "v0.2"
        data_root.mkdir(parents=True)
        # data_root の外のパス
        outside = tmp_path / "outside" / "phase1-foo" / "abbrev" / "x.md"
        outside.parent.mkdir(parents=True)
        outside.touch()

        with pytest.raises(ValueError, match="not under data_root"):
            resolve_phase_from_path(outside, data_root)

    def test_invalid_phase_name_raises(self, tmp_path: Path) -> None:
        data_root = tmp_path / "data" / "v0.2"
        # PHASE_DIR_RE に合わない (`phase01-Police` 大文字含む)
        bad = data_root / "phase01-Police" / "abbrev" / "x.md"
        bad.parent.mkdir(parents=True)
        bad.touch()

        with pytest.raises(ValueError, match="PHASE_DIR_RE"):
            resolve_phase_from_path(bad, data_root)

    def test_too_shallow_path_raises(self, tmp_path: Path) -> None:
        data_root = tmp_path / "data" / "v0.2"
        # 2 parts のみ (phase/file.md, abbrev dir 欠落)
        shallow = data_root / "phase1-police" / "x.md"
        shallow.parent.mkdir(parents=True)
        shallow.touch()

        with pytest.raises(ValueError, match="at least 3"):
            resolve_phase_from_path(shallow, data_root)


# -------------------------------------------------------------------------
# 2. rewrite_tags0_in_text 基本動作
# -------------------------------------------------------------------------


class TestRewriteTags0Basic:
    """置換 / 冪等 / 各種 ValueError."""

    def test_legacy_to_new_phase_succeeds(self) -> None:
        text = _make_v02_frontmatter(DEPRECATED_PHASE_TAG)
        new_text, changed = rewrite_tags0_in_text(text, "phase2-commercial")

        assert changed is True
        assert "tags:\n- phase2-commercial\n- auto-generated\n" in new_text
        # 旧 phase 文字列は frontmatter から完全除去されているべき (本文は元々無し).
        assert f"- {DEPRECATED_PHASE_TAG}\n" not in new_text
        # 本文 (body) は不変.
        assert "商人の営業、商行為その他商事については" in new_text

    def test_idempotent_when_already_correct(self) -> None:
        text = _make_v02_frontmatter("phase2-commercial")
        new_text, changed = rewrite_tags0_in_text(text, "phase2-commercial")

        assert changed is False
        # 完全に同一であること.
        assert new_text == text

    def test_phase1_police_path_self_idempotent(self) -> None:
        """phase1-police 配下のファイルは tag0=phase1-police で新値も phase1-police.

        この場合は changed=False の冪等動作になる.
        """
        text = _make_v02_frontmatter(DEPRECATED_PHASE_TAG)
        new_text, changed = rewrite_tags0_in_text(text, "phase1-police")

        assert changed is False
        assert new_text == text

    def test_unexpected_tag0_raises(self) -> None:
        text = _make_v02_frontmatter("weird-tag")
        with pytest.raises(ValueError, match=r"\[TAG0_UNEXPECTED\]"):
            rewrite_tags0_in_text(text, "phase2-commercial")

    def test_tag1_not_autogen_raises(self) -> None:
        text = _make_v02_frontmatter(DEPRECATED_PHASE_TAG, tag1="manual-tag")
        with pytest.raises(ValueError, match=r"\[TAG1_NOT_AUTOGEN\]"):
            rewrite_tags0_in_text(text, "phase2-commercial")

    def test_no_tags_block_raises(self) -> None:
        text = "---\nlaw_id: 132AC0000000048\n---\n\n# 本文\n"
        with pytest.raises(ValueError, match=r"\[TAGS_TOO_SHORT\]"):
            rewrite_tags0_in_text(text, "phase2-commercial")

    def test_single_tag_raises(self) -> None:
        text = "---\nlaw_id: 132AC0000000048\ntags:\n- phase1-police\n---\n\n# 本文\n"
        with pytest.raises(ValueError, match=r"\[TAGS_TOO_SHORT\]"):
            rewrite_tags0_in_text(text, "phase2-commercial")

    def test_invalid_new_phase_raises(self) -> None:
        text = _make_v02_frontmatter(DEPRECATED_PHASE_TAG)
        with pytest.raises(ValueError, match=r"\[INVALID_NEW_PHASE\]"):
            rewrite_tags0_in_text(text, "Phase2-Commercial")  # 大文字混入


# -------------------------------------------------------------------------
# 3. frontmatter 範囲ガード (★ v3 追加)
# -------------------------------------------------------------------------


class TestFrontmatterScopeGuard:
    """body の `notes: |` 等に `tags:\\n- phase1-police\\n` が含まれても誤書換しない."""

    def test_does_not_rewrite_phase_in_body_notes(self) -> None:
        """注記本文に過去メタデータの引用が含まれている場合の決定的反証ケース.

        frontmatter は既に正しい phase2-commercial で、body の `## 注記`
        セクションに過去 metadata の引用として `tags:\\n- phase1-police\\n`
        が含まれている. sweep は body 側を一切 touch してはならない.
        """
        text = (
            "---\n"
            "law_id: 132AC0000000048\n"
            "tags:\n- phase2-commercial\n- auto-generated\n"
            "---\n"
            "\n"
            "# 商法 第1条\n"
            "\n"
            "## 注記\n"
            "\n"
            "過去のメタデータ snapshot:\n"
            "\n"
            "```yaml\n"
            "tags:\n"
            "- phase1-police\n"
            "- auto-generated\n"
            "```\n"
        )
        new_text, changed = rewrite_tags0_in_text(text, "phase2-commercial")

        # 冪等動作: 既に正しい phase なので変更なし、text 完全不変.
        assert changed is False
        assert new_text == text
        # 念のため body 内の引用が完全に保たれていることを assert.
        assert "tags:\n- phase1-police\n- auto-generated\n```" in new_text

    def test_fm_missing_opening_raises(self) -> None:
        # `---\n` で始まらない
        text = "law_id: foo\ntags:\n- phase1-police\n- auto-generated\n"
        with pytest.raises(ValueError, match=r"\[FM_MISSING\]"):
            rewrite_tags0_in_text(text, "phase2-commercial")

    def test_fm_missing_closing_raises(self) -> None:
        # `\n---\n` 終端が無い
        text = "---\nlaw_id: foo\ntags:\n- phase1-police\n- auto-generated\n"
        with pytest.raises(ValueError, match=r"\[FM_MISSING\]"):
            rewrite_tags0_in_text(text, "phase2-commercial")


# -------------------------------------------------------------------------
# 4. BOM 検知 (★ v3 追加、option b)
# -------------------------------------------------------------------------


class TestBOMDetection:
    """UTF-8 BOM 検知時は ValueError、本 sweep スコープ外であることを明示."""

    def test_bom_detected_raises(self) -> None:
        text = "﻿" + _make_v02_frontmatter(DEPRECATED_PHASE_TAG)
        with pytest.raises(ValueError, match=r"\[BOM_DETECTED\]") as exc_info:
            rewrite_tags0_in_text(text, "phase2-commercial")

        # エラーメッセージに FU-317 への参照が含まれること (受け取り側に対処先を明示).
        assert "FU-317" in str(exc_info.value)


# -------------------------------------------------------------------------
# 5. 改行コード round-trip 不変性 (★ v3 追加)
# -------------------------------------------------------------------------


class TestNewlineRoundTrip:
    """CRLF on disk fixture → sweep → write — disk 上の改行コードが保存されることを assert.

    Why OS 分岐:
      Python の `os.fdopen(fd, "w", encoding=...)` の挙動は OS 依存:
        - Windows: `\\n` → `\\r\\n` への変換が発生 (CRLF を維持).
        - Linux:   変換無し、disk 上は LF のみになる.
      テストは両環境で正しい期待値を assert する.
    """

    def test_lf_only_round_trip(self, tmp_path: Path) -> None:
        """LF only fixture → sweep → LF のまま (Linux 環境前提、Windows でも CRLF 化のみが許容差分)."""
        text_lf = _make_v02_frontmatter(DEPRECATED_PHASE_TAG)
        md_path = tmp_path / "test.md"
        # disk に LF only で書き込み (newline="" で OS の改行翻訳を抑止).
        md_path.write_bytes(text_lf.encode("utf-8"))

        # 通常の read_text → rewrite → safe_write_text の往復.
        loaded = md_path.read_text(encoding="utf-8")
        new_text, changed = rewrite_tags0_in_text(loaded, "phase2-commercial")
        assert changed is True
        safe_write_text(md_path, new_text)

        # 書き戻し後の memory 表現は LF only であるべき (universal newlines).
        reloaded = md_path.read_text(encoding="utf-8")
        assert "\r" not in reloaded
        assert "tags:\n- phase2-commercial\n- auto-generated\n" in reloaded

    def test_crlf_on_disk_preserved_after_sweep(self, tmp_path: Path) -> None:
        """CRLF on disk fixture → sweep → disk 上の改行コードが OS 規約を維持.

        本テストの assert は disk 上の bytes に対して行う:
          - Linux:   safe_write_text が LF を書く → disk は LF
          - Windows: safe_write_text が `\\n` → `\\r\\n` 翻訳 → disk は CRLF
        どちらも「OS デフォルト改行コードへの収束」が保証される.
        """
        text_lf = _make_v02_frontmatter(DEPRECATED_PHASE_TAG)
        text_crlf = text_lf.replace("\n", "\r\n")
        md_path = tmp_path / "test_crlf.md"
        md_path.write_bytes(text_crlf.encode("utf-8"))

        # read_text → in-memory では LF 正規化されている.
        loaded = md_path.read_text(encoding="utf-8")
        assert "\r" not in loaded, "read_text should normalize CRLF to LF"

        new_text, changed = rewrite_tags0_in_text(loaded, "phase2-commercial")
        assert changed is True
        safe_write_text(md_path, new_text)

        # disk バイト列を読み直して OS デフォルトの改行コードを確認.
        disk_bytes = md_path.read_bytes()
        if os.linesep == "\r\n":
            # Windows: safe_write_text が CRLF に翻訳して書き込む.
            assert b"\r\n" in disk_bytes
        else:
            # Linux/macOS: LF のまま.
            assert b"\r\n" not in disk_bytes
            assert b"\n" in disk_bytes

        # 内容が正しく書き換わっていること (universal newlines で再読込).
        reloaded = md_path.read_text(encoding="utf-8")
        assert "tags:\n- phase2-commercial\n- auto-generated\n" in reloaded


# -------------------------------------------------------------------------
# 6. safe_write_text との往復
# -------------------------------------------------------------------------


class TestSafeWriteRoundTrip:
    """tmp に fixture を置く → 書き換え → 読み戻して期待値と一致."""

    def test_full_pipeline(self, tmp_path: Path) -> None:
        md_path = tmp_path / "fixture.md"
        original = _make_v02_frontmatter(DEPRECATED_PHASE_TAG)
        safe_write_text(md_path, original)

        loaded = md_path.read_text(encoding="utf-8")
        new_text, changed = rewrite_tags0_in_text(loaded, "phase3-pharma")
        assert changed is True
        safe_write_text(md_path, new_text)

        reloaded = md_path.read_text(encoding="utf-8")
        assert "tags:\n- phase3-pharma\n- auto-generated\n" in reloaded
        # body 不変.
        assert "商人の営業、商行為その他商事については" in reloaded

    def test_double_apply_is_idempotent(self, tmp_path: Path) -> None:
        md_path = tmp_path / "fixture.md"
        original = _make_v02_frontmatter(DEPRECATED_PHASE_TAG)
        safe_write_text(md_path, original)

        # 1 回目 apply
        loaded1 = md_path.read_text(encoding="utf-8")
        new_text1, changed1 = rewrite_tags0_in_text(loaded1, "phase3-pharma")
        assert changed1 is True
        safe_write_text(md_path, new_text1)

        # 2 回目 apply (冪等性)
        loaded2 = md_path.read_text(encoding="utf-8")
        new_text2, changed2 = rewrite_tags0_in_text(loaded2, "phase3-pharma")
        assert changed2 is False
        assert new_text2 == loaded2


# -------------------------------------------------------------------------
# 7. PHASE_DIR_RE の sanity check
# -------------------------------------------------------------------------


class TestPhaseDirRe:
    """PHASE_DIR_RE 自体の正規表現を直接テスト."""

    @pytest.mark.parametrize(
        "phase",
        [
            "phase1-police",
            "phase1-administrative",
            "phase1-foundational",
            "phase1-practitioner",
            "phase1-tax",
            "phase2-commercial",
            "phase3-labor",
            "phase3-pharma",
        ],
    )
    def test_accepts_valid_phases(self, phase: str) -> None:
        assert PHASE_DIR_RE.fullmatch(phase) is not None

    @pytest.mark.parametrize(
        "phase",
        [
            "phase",  # 番号なし
            "phase1",  # 区分なし
            "phase0-x",  # 0 始まり
            "phase10-x",  # 10 以降 (将来規約変更時に明示更新する想定)
            "Phase1-police",  # 大文字
            "phase1-Police",  # 大文字
            "phase1_police",  # アンダースコア
            "phase1-",  # 末尾ハイフン
        ],
    )
    def test_rejects_invalid_phases(self, phase: str) -> None:
        assert PHASE_DIR_RE.fullmatch(phase) is None
