#!/usr/bin/env python3
"""run-ci.py -- reproduce every CI check locally with one command.

Why:
    Reproducing CI before a push by hand misses steps (PR #14 shipped an em-dash
    that CI caught but a local ruff+pytest did not). This runner mirrors
    .github/workflows/ci.yml -- the SAME checks over the SAME target set -- so a
    green here means a green there. This includes the body-text table-parity check,
    which now runs every PR in ci.yml (fidelity-gate job) as well -- VA-2 stage 1 put
    the e-Gov XML under version control (cache/laws), so the check is no longer
    local-only; run-ci.py reproduces it with the same invocation.

    The pytest path list is duplicated from ci.yml on purpose: parsing YAML at
    runtime would add a dependency and let an indentation change break this tool for
    a reason unrelated to the code under test. A duplicate is only safe if something
    compares the copies -- tools/scripts/tests/test_run_ci_pytest_parity.py asserts
    this list and ci.yml's are equal, so they cannot drift silently (an un-compared
    duplicate is exactly how this runner drifted to a sixth of CI's coverage).

    Two gates (eval-set checksum, pass-line lock) exit 0 whether they verified
    anything or merely printed an INACTIVE warning -- the digest they check is
    injected by CI and is never set locally. Reporting those as PASS would be the
    very "green that means nothing" this work removes, so they are surfaced as
    INACTIVE, never PASS (see run()).

Usage:
    python tools/scripts/run-ci.py
    Exit 0 = nothing failed (INACTIVE gates are expected locally and do not fail the
    run); exit 1 = at least one step failed (see the SUMMARY). Cross-platform
    (works on Windows-native dev without make).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent  # tools/scripts/run-ci.py -> repo root
PY = sys.executable
# Mirror ci.yml's Pytest step env: juricode_shared + juricode-verifier on the path.
PYENV = {
    "PYTHONPATH": os.pathsep.join(
        [
            str(ROOT / "tools" / "shared" / "src"),
            str(ROOT / "packages" / "juricode-verifier" / "src"),
        ]
    )
}

# Duplicated verbatim from .github/workflows/ci.yml's "Pytest (all workspace
# packages)" step. Kept honest by tools/scripts/tests/test_run_ci_pytest_parity.py,
# which asserts this set equals the one parsed out of ci.yml. Add a path in BOTH
# places (and pyproject testpaths) -- a one-sided edit fails that parity test.
PYTEST_PATHS = [
    "packages/juricode-verifier/tests",
    "packages/juricode-retrieval/tests",
    "tools/shared/tests",
    "tools/validate/tests",
    "tools/parse/tests/test_tsutatsu_byte_regression.py",
    "tools/parse/tests/test_shouhi_tsutatsu.py",
    "tools/parse/tests/test_tsutatsu_multichapter.py",
    "tools/parse/tests/test_sochi_hojin_tsutatsu.py",
    "tools/parse/tests/test_sochi_joto_tsutatsu.py",
    "tools/parse/tests/test_sochi_shotoku_tsutatsu.py",
    "tools/parse/tests/test_sochi_sozoku_tsutatsu.py",
    "tools/parse/tests/test_sochi_kabushiki_tsutatsu.py",
    "tools/parse/tests/test_sochi_gensen_tsutatsu.py",
    "tools/parse/tests/test_sochi_40jou_tsutatsu.py",
    "tools/parse/tests/test_taxanswer_related.py",
    "tools/parse/tests/test_sochi_promotion_guards.py",
    "tools/parse/tests/test_kfs_saiketsu.py",
    "tools/parse/tests/test_kfs_eda_ban_regression.py",
    "tools/parse/tests/test_kfs_multi_article.py",
    "tools/parse/tests/test_kfs_appendix_amend_guard.py",
    "tools/parse/tests/test_hojin_rulings_store.py",
    "tools/parse/tests/test_hojin_precedents_store.py",
    "tools/parse/tests/test_keihou_precedents_store.py",
    "tools/parse/tests/test_sozoku_rulings_store.py",
    "tools/parse/tests/test_shohi_rulings_store.py",
    "tools/parse/tests/test_shotoku_rulings_store.py",
    "tools/parse/tests/test_kokutsu_rulings_store.py",
    "tools/parse/tests/test_caselaw_decision_date_nonnull.py",
    "tools/parse/tests/test_shotoku_corpus.py",
    "tools/parse/tests/test_souzoku_corpus.py",
    "tools/parse/tests/test_hyoka_corpus.py",
    "tools/parse/tests/test_hojin_taxanswer_corpus.py",
    "tools/parse/tests/test_sozoku_taxanswer_corpus.py",
    "tools/parse/tests/test_shohi_taxanswer_corpus.py",
    "tools/parse/tests/test_gensen_taxanswer_corpus.py",
    "tools/parse/tests/test_shotoku_taxanswer_corpus.py",
    "tools/parse/tests/test_joto_taxanswer_corpus.py",
    "tools/parse/tests/test_inshi_taxanswer_corpus.py",
    "tools/amendments/tests/test_shouhi_amendments.py",
    "tools/amendments/tests/test_souzoku_amendments.py",
    "tools/amendments/tests/test_houjin_amendments.py",
    "tools/amendments/tests/test_shotoku_amendments.py",
    "tools/amendments/tests/test_chain_hardening.py",
    "tools/amendments/tests/test_kokutsu_amendments.py",
    "tools/parse/v0.2/tests",
    "tools/parse/v0.2/manifest/tests",
    "tools/search-ui/tests",
    "tools/fetch-egov/tests/test_tsutatsu_fetcher.py",
    "tools/embed/tests/test_v8_prep_audit.py",
    "tools/embed/tests/test_build_v8_corpus.py",
    "tools/embed/tests/test_filter_v8_embed.py",
    "tools/embed/tests/test_retrieve_dedup.py",
    "tools/embed/tests/test_retrieve_reexports.py",
    "tools/embed/tests/test_vec_json.py",
    "tools/serve/tests/test_retrieval_server.py",
    "tools/serve/tests/test_retrieval_server_reexport.py",
    "tools/serve/tests/test_guards.py",
    "tools/serve/tests/test_chat_server.py",
    "tools/scripts/tests/test_check_no_leaks.py",
    "tools/scripts/tests/test_check_public_claims.py",
    "tools/scripts/tests/test_check_fidelity_claims.py",
    "tools/scripts/tests/test_check_public_claims_gate.py",
    "tools/registry/tests/test_build_registry.py",
    "tools/registry/tests/test_egov_anchor_index.py",
    "tools/dist/tests/test_scan_artifacts.py",
    "tools/dist/tests/test_build_snapshot.py",
    "tools/dist/tests/test_publish_to_hf.py",
    "tools/dist/tests/test_publish_to_github_release.py",
    "tools/scripts/tests/test_verify_gates_lock.py",
    "tools/serve/tests/test_reproduce_a3_verdict.py",
    "tools/scripts/tests/test_run_ci_pytest_parity.py",
]

# Schema files diffed after regeneration, in ci.yml's order. Duplicated verbatim
# from ci.yml's "Regenerate JSON Schema and check for drift" step and kept honest by
# the same parity test as PYTEST_PATHS. Add a schema in BOTH places.
SCHEMA_DRIFT_FILES = [
    "schema/juricode-article.schema.json",
    "schema/juricode-taxanswer.schema.json",
    "schema/juricode-directive.schema.json",
    "schema/ruling-store.schema.json",
]


def run(
    name: str,
    argv: list[str],
    env: dict[str, str] | None = None,
    inactive_marker: str | None = None,
) -> str:
    """Run one step; return its status: "PASS", "FAIL", or "INACTIVE".

    Why the inactive_marker path: a bridged gate exits 0 whether it verified
    anything or only printed an INACTIVE warning (the digest it needs is injected by
    CI and is unset locally). returncode alone would call that PASS. When a caller
    passes inactive_marker, capture both streams, re-emit each to its OWN stream
    (nothing is lost), and look for the marker in either -- the warning is on stderr,
    so scanning stdout alone would miss it and wrongly report PASS. Streams are NOT
    merged: re-emitting a merged stream would send the child's stderr to our stdout,
    making a warning stop looking like one. Every other caller keeps today's
    behaviour (output streams straight through -- capturing pytest would buffer a
    multi-minute run into silence).
    """
    print(f"\n=== [{name}] {' '.join(argv)} ===", flush=True)
    full_env = {**os.environ, **(env or {})}

    if inactive_marker is None:
        result = subprocess.run(argv, cwd=ROOT, env=full_env)
        status = "PASS" if result.returncode == 0 else "FAIL"
        print(f"--- [{name}] {status} (exit {result.returncode}) ---", flush=True)
        return status

    result = subprocess.run(argv, cwd=ROOT, env=full_env, capture_output=True, text=True)
    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    sys.stdout.flush()
    sys.stderr.flush()
    if result.returncode != 0:
        status = "FAIL"
    elif inactive_marker in (result.stdout or "") or inactive_marker in (result.stderr or ""):
        status = "INACTIVE"
    else:
        status = "PASS"
    print(f"--- [{name}] {status} (exit {result.returncode}) ---", flush=True)
    return status


def schema_drift() -> str:
    """Regenerate schema from IR and diff (CI step "Regenerate JSON Schema").

    Diffs the same SCHEMA_DRIFT_FILES as ci.yml (article, taxanswer, directive,
    ruling-store) so a drift CI would catch is caught here too. The parity test keeps
    the two lists equal.
    """
    print("\n=== [schema-drift] export-schema + git diff --exit-code ===", flush=True)
    gen = subprocess.run([PY, "tools/shared/scripts/export-schema.py"], cwd=ROOT)
    if gen.returncode != 0:
        print("--- [schema-drift] FAIL (export-schema error) ---", flush=True)
        return "FAIL"
    ok = True
    for schema in SCHEMA_DRIFT_FILES:
        diff = subprocess.run(["git", "diff", "--exit-code", schema], cwd=ROOT)
        if diff.returncode != 0:
            print(
                f"::error:: {schema} is out of sync with the Pydantic IR. "
                "Re-run export-schema.py and commit the result.",
                flush=True,
            )
            ok = False
    status = "PASS" if ok else "FAIL"
    print(f"--- [schema-drift] {status} ---", flush=True)
    return status


def main() -> int:
    results: list[tuple[str, str]] = []

    # 1-2. Lint + format (ci.yml: ruff check / format over tools/ AND packages/).
    results.append(
        ("ruff-check", run("ruff-check", [PY, "-m", "ruff", "check", "tools/", "packages/"]))
    )
    results.append(
        (
            "ruff-format",
            run("ruff-format", [PY, "-m", "ruff", "format", "--check", "tools/", "packages/"]),
        )
    )

    # 3. Pytest over the exact ci.yml target set (one command, not a per-path loop).
    results.append(("pytest", run("pytest", [PY, "-m", "pytest", *PYTEST_PATHS, "-q"], env=PYENV)))

    # 4-6. Data validation / manifest hashes / phase tags.
    results.append(
        ("validate-all", run("validate-all", [PY, "tools/validate/validate-all.py"], env=PYENV))
    )
    results.append(
        (
            "verify-manifest",
            run("verify-manifest", [PY, "tools/parse/verify.py", "--path", "data"], env=PYENV),
        )
    )
    results.append(
        (
            "phase-tags",
            run(
                "phase-tags",
                [PY, "tools/scripts/fix-phase-tags.py", "--path", "data/v0.2", "--check-only"],
                env=PYENV,
            ),
        )
    )

    # 7. Canonical md residue (G0-e) -- XML-free, so it runs in CI (and here).
    results.append(
        (
            "md-residue",
            run(
                "md-residue",
                [PY, "tools/scripts/check-md-residue.py", "--path", "data/v0.2"],
                env=PYENV,
            ),
        )
    )

    # 8. v0.2 corpus phase mapping.
    results.append(
        (
            "corpus-mapping",
            run(
                "corpus-mapping",
                [PY, "tools/embed/build-v0.2-corpus.py", "--validate-only"],
                env=PYENV,
            ),
        )
    )

    # 9. cp932-safe over tools AND packages (--path is single-valued -> call twice).
    results.append(
        (
            "cp932-safe (tools)",
            run("cp932-safe (tools)", [PY, "tools/scripts/check-cp932-safe.py", "--path", "tools"]),
        )
    )
    results.append(
        (
            "cp932-safe (packages)",
            run(
                "cp932-safe (packages)",
                [PY, "tools/scripts/check-cp932-safe.py", "--path", "packages"],
            ),
        )
    )

    # 9b. Public-claims gate: no retrieval accuracy figures on the outward README
    # (VA-5-data). Marketing surface only; open benchmarks/ figures are untouched.
    results.append(
        (
            "public-claims",
            run("public-claims", [PY, "tools/scripts/check-public-claims.py"]),
        )
    )

    # 9c. Public guarantee-claims gate (VA-5): every guarantee word on a board
    # carries an adjacent gate id naming the gate behind it; accuracy figures stay
    # in benchmarks/. Dictionary/scope/exclusion markers are owner-locked.
    results.append(
        (
            "public-claims-gate",
            run("public-claims-gate", [PY, "tools/scripts/check-public-claims-gate.py"]),
        )
    )

    # 10-11. Guard-the-guard checksum gates. Their variable is injected by CI and is
    # unset locally, so they exit 0 with an INACTIVE warning -- surface that as
    # INACTIVE, never PASS (see run()).
    results.append(
        (
            "eval-set-checksum",
            run(
                "eval-set-checksum",
                [PY, "tools/scripts/verify-eval-set-checksum.py"],
                inactive_marker="gate INACTIVE",
            ),
        )
    )
    results.append(
        (
            "pass-line-lock",
            run(
                "pass-line-lock",
                [PY, "tools/scripts/verify-gates-lock.py"],
                inactive_marker="gate INACTIVE",
            ),
        )
    )

    # 12. Schema drift.
    results.append(("schema-drift", schema_drift()))

    # 13-15. Fidelity pipeline (mirrors ci.yml's fidelity-gate job): rebuild the
    # derived chunks from the versioned Markdown and source XML, then run the gate
    # over them. build -> build -> gate, each build its own step so a build failure is
    # never read as a fidelity violation. This OVERWRITES build/chunks with a fresh
    # build on purpose -- the gate must check what the deterministic parser produces
    # now, not a stale local copy -- and it does not delete the non-regenerable store
    # files that also live there (the builders write per-file, they do not wipe the
    # tree). Order is pinned even though the two builds are order-independent today, so
    # a future change to that surfaces as a diff. Carrying the same pipeline here and
    # in ci.yml is what makes "green locally" and "green in CI" mean the same thing.
    results.append(
        (
            "build-segment-chunks",
            run(
                "build-segment-chunks",
                [PY, "tools/parse/v0.2/build_chunks_from_md.py"],
                env=PYENV,
            ),
        )
    )
    results.append(
        (
            "build-table-chunks",
            run(
                "build-table-chunks",
                [PY, "tools/parse/v0.2/extract_table_from_xml.py"],
                env=PYENV,
            ),
        )
    )
    results.append(
        (
            "fidelity-gate",
            run("fidelity-gate", [PY, "tools/parse/v0.2/g0_fidelity_gate.py"], env=PYENV),
        )
    )

    # 本則 table parity. Now runs every PR in ci.yml (fidelity-gate job) too, since
    # VA-2 stage 1 put the e-Gov XML cache under version control; this is the local
    # reproduction. A missing cache/laws is now a broken state and fails loudly.
    results.append(
        (
            "table-parity",
            run("table-parity", [PY, "tools/parse/v0.2/verify_table_parity.py"], env=PYENV),
        )
    )

    print("\n==================== SUMMARY ====================", flush=True)
    for name, status in results:
        print(f"  {status:9} {name}", flush=True)
    failed = [name for name, status in results if status == "FAIL"]
    inactive = [name for name, status in results if status == "INACTIVE"]
    if failed:
        print(f"\n{len(failed)} step(s) FAILED: {', '.join(failed)}", flush=True)
        return 1
    if inactive:
        # Expected locally: these gates need a CI-injected variable. They did not run
        # a real check here -- flag that instead of hiding them under ALL GREEN.
        print(
            f"\n{len(inactive)} gate(s) INACTIVE locally (variable injected by CI, "
            f"unset here -- not actually checked): {', '.join(inactive)}",
            flush=True,
        )
    print("\nALL GREEN", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
