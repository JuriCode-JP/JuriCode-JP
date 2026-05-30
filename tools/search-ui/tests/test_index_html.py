"""Static smoke for index.html (Phase C).

Why this test exists:
    The UI JS cannot be unit-tested without a browser, so this minimal guard pins
    the contract that survives refactors: the endpoints it must POST to (root-relative,
    SLASH trap), the secure-context-safe session id, the visibility-aware dwell tracker,
    keepalive sends, and the PII notice banner. Catches accidental regressions cheaply.
"""

from __future__ import annotations

from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "index.html").read_text(encoding="utf-8")


def test_posts_to_log_endpoints() -> None:
    assert "/api/question" in HTML
    assert "/api/feedback" in HTML
    assert "/api/click" in HTML


def test_root_relative_paths_only() -> None:
    # SLASH trap: every endpoint must be root-relative ("/api/...") and never bare.
    for ep in ("question", "feedback", "click"):
        assert f"'/api/{ep}'" in HTML
        assert f"'api/{ep}'" not in HTML  # no leading slash would 404 in prod


def test_session_id_secure_context_fallback() -> None:
    assert "crypto.randomUUID" in HTML
    assert "genSid" in HTML  # fallback for non-secure contexts


def test_dwell_tracker_visibility_aware() -> None:
    assert "updateTimerState" in HTML
    assert "visibilitychange" in HTML
    assert "hasFocus" in HTML
    assert "300" in HTML  # JS-side cap Math.min(_, 300)


def test_keepalive_on_sends() -> None:
    assert "keepalive" in HTML


def test_pii_notice_banner() -> None:
    assert "個人情報は入力しないでください" in HTML


def test_feedback_is_per_question_not_per_card() -> None:
    # FeedbackEntry has no rank -> single per-question feedback bar.
    assert "この結果は役に立ちましたか" in HTML
