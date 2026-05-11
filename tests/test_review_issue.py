"""Tests for `aidevkit.review_issue` (DevKit#17).

All `gh` invocations flow through the `subprocess_capture` fixture from
``conftest.py`` (which monkeypatches ``aidevkit.util.run`` — the project-wide
hermeticity seam). No real `gh` or network calls are made.

Helpers in this module:
- ``make_issue_fixture``: build a synthetic gh JSON response.
- ``valid_findings_doc`` / ``invalid_findings_doc``: minimal findings docs for
  schema-validation tests.
- ``cortex_expertise_issue_fixture``: the DevKit#17 motivating example
  (positive AC: env-var config; negative AC: does-not-require-cortex-config).
- ``standard_path_env``: monkeypatch the issue-authoring standard path so the
  runtime existence check finds it during tests.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import typer

from aidevkit import review_issue
from aidevkit.util import RunResult

# --------------------------------------------------------------------------- #
# Fixtures and helpers (T011)
# --------------------------------------------------------------------------- #


def make_issue_fixture(
    *,
    body: str = "## Summary\nTest issue.\n",
    title: str = "Test issue",
    number: int = 42,
    repo: str = "App-Empire-LLC/DevKit",
    comments: list[dict[str, Any]] | None = None,
    labels: list[dict[str, Any]] | None = None,
    project_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "number": number,
        "url": f"https://github.com/{repo}/issues/{number}",
        "title": title,
        "body": body,
        "labels": labels or [],
        "assignees": [],
        "milestone": None,
        "projectItems": project_items or [],
        "comments": comments or [],
    }


def cortex_expertise_issue_fixture() -> dict[str, Any]:
    """The DevKit#17 motivating example.

    Body matches `quickstart.md` § "Worked example: derived-negative AC pair".
    """
    body = (
        "## Summary\n"
        "Extract cortex-expertise as a standalone service.\n\n"
        "## Acceptance Criteria\n\n"
        "- Configuration delivered via a single environment variable "
        "(plain text or base64), read at startup.\n"
        "- The service starts without requiring cortex-config or any "
        "external configuration service.\n"
    )
    return make_issue_fixture(body=body, title="Extract cortex-expertise", number=7,
                              repo="App-Empire-LLC/cortex-expertise")


def valid_findings_doc(
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {"schema_version": "1", "findings": findings or []}


def invalid_findings_doc(missing_field: str = "findings") -> dict[str, Any]:
    base = {"schema_version": "1", "findings": []}
    base.pop(missing_field, None)
    return base


def make_finding(
    fid: str = "F01",
    *,
    category: str = "completeness",
    severity: str = "warning",
    location: str = "Body §Summary",
    summary: str = "Example finding",
    recommendation: str = "Example recommendation",
    evidence: str | None = None,
    pair: dict[str, Any] | None = None,
) -> dict[str, Any]:
    f: dict[str, Any] = {
        "id": fid,
        "category": category,
        "severity": severity,
        "location": location,
        "summary": summary,
        "recommendation": recommendation,
    }
    if evidence is not None:
        f["evidence"] = evidence
    if pair is not None:
        f["pair"] = pair
    return f


def cortex_pair_finding() -> dict[str, Any]:
    """A derived-negative-pair finding matching the cortex-expertise example."""
    return make_finding(
        fid="F02",
        category="derived-negative-pair",
        severity="warning",
        location="Acceptance Criteria, items 1-2",
        summary="AC-2 (does not require cortex-config) is entailed by AC-1 (loads from env var).",
        recommendation=(
            "Drop the negative AC, keep as non-goal docs only, or escalate to risk control."
        ),
        pair={
            "positive_ref": "AC-1: loads config from a single env var",
            "negative_ref": "AC-2: does not require cortex-config",
            "entailment_explanation": "Verifying AC-1 (env-var config works) verifies AC-2.",
            "dispositions": [
                {"choice": "drop", "description": "Let SpecKit infer the negative."},
                {"choice": "non-goal", "description": "Keep as non-goal documentation only."},
                {"choice": "risk-control", "description": "Escalate to a hardening test (rare)."},
            ],
        },
    )


@pytest.fixture
def standard_path_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Materialise a stub issue-authoring standard and point the resolver at it.

    The resolver checks ``$DEVKIT_REVIEW_ISSUE_STANDARD_PATH`` first; setting
    that lets tests run from any cwd without dragging in the real appire_docs.
    """
    standard = tmp_path / "issue_authoring.md"
    standard.write_text("# Issue Authoring\nStub for tests.\n")
    monkeypatch.setenv("DEVKIT_REVIEW_ISSUE_STANDARD_PATH", str(standard))
    return standard


@pytest.fixture
def feed_findings(monkeypatch: pytest.MonkeyPatch):
    """Helper that stuffs a JSON document into stdin for `cmd_review_issue_post`."""
    def _feed(doc: dict[str, Any]) -> None:
        import io
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(doc)))
    return _feed


# --------------------------------------------------------------------------- #
# Phase 3: User Story 1 tests (T012–T020a)
# --------------------------------------------------------------------------- #


def test_inspect_emits_envelope(
    subprocess_capture, standard_path_env, capsys
) -> None:
    """T012 — inspect emits a JSON envelope conforming to the schema."""
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_inspect(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None
    )
    assert rc == 0
    captured = capsys.readouterr().out
    envelope = json.loads(captured)
    # Validate against the inspect-subset of the output schema.
    jsonschema.validate(envelope, review_issue._OUTPUT_SCHEMA)
    assert envelope["run"]["n_next"] == 1
    assert envelope["reviewer"]["id"] == "claude"
    assert envelope["issue"]["ref"] == "App-Empire-LLC/DevKit#42"


def test_gate_blocked_when_blocker_present(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T013 — any blocker → BLOCKED in both rendered comment and JSON."""
    feed_findings(valid_findings_doc([
        make_finding(severity="blocker", category="completeness",
                     summary="No Acceptance Criteria section"),
    ]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    subprocess_capture.queue(RunResult(  # for the post call
        code=0, stdout="https://github.com/App-Empire-LLC/DevKit/issues/42#issuecomment-1\n",
        stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=True, json_output=True, verbose=False, min_severity="warning",
    )
    assert rc == 0
    out_text = capsys.readouterr().out
    envelope = json.loads(out_text)
    assert envelope["gate"] == "BLOCKED"


def test_gate_warnings_when_warnings_only(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T014 — only warnings → READY_WITH_WARNINGS."""
    feed_findings(valid_findings_doc([
        make_finding(severity="warning"),
    ]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=True, json_output=True, verbose=False, min_severity="warning",
    )
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["gate"] == "READY_WITH_WARNINGS"


def test_gate_ready_when_clean(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T015 — empty or nit-only findings → READY."""
    for findings_list in ([], [make_finding(severity="nit")]):
        feed_findings(valid_findings_doc(findings_list))
        issue = make_issue_fixture()
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
        rc = review_issue.cmd_review_issue_post(
            ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
            dry_run=True, json_output=True, verbose=False, min_severity="warning",
        )
        assert rc == 0
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["gate"] == "READY"


def test_run_n_increments_per_reviewer(
    subprocess_capture, standard_path_env, capsys
) -> None:
    """T016 — run-N counter is per-reviewer-id."""
    issue = make_issue_fixture(comments=[
        {"body": "<!-- devkit-review-issue:claude:run-1 -->\n## Issue Review\n..."},
        {"body": "<!-- devkit-review-issue:claude:run-2 -->\n## Issue Review\n..."},
    ])
    # claude → 3
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    review_issue.cmd_review_issue_inspect(
        ref="App-Empire-LLC/DevKit#42", reviewer_id="claude"
    )
    env_claude = json.loads(capsys.readouterr().out)
    assert env_claude["run"]["n_next"] == 3
    # gpt → 1 (no prior runs)
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    review_issue.cmd_review_issue_inspect(
        ref="App-Empire-LLC/DevKit#42", reviewer_id="gpt"
    )
    env_gpt = json.loads(capsys.readouterr().out)
    assert env_gpt["run"]["n_next"] == 1


def test_derived_negative_pair_finding(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T017 + SC-007 — cortex-expertise pair renders + counts in metrics."""
    feed_findings(valid_findings_doc([cortex_pair_finding()]))
    issue = cortex_expertise_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/cortex-expertise#7", reviewer_id=None,
        dry_run=True, json_output=False, verbose=False, min_severity="warning",
    )
    assert rc == 0
    out_text = capsys.readouterr().out
    assert "F02" in out_text
    assert "derived-negative-pair" in out_text
    assert "1 derived-negative pair" in out_text


def test_post_calls_gh_comment(
    subprocess_capture, standard_path_env, feed_findings
) -> None:
    """T018 — happy-path post invokes gh issue comment exactly once."""
    feed_findings(valid_findings_doc([make_finding(severity="warning")]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    subprocess_capture.queue(RunResult(
        code=0, stdout="https://github.com/App-Empire-LLC/DevKit/issues/42#issuecomment-1\n",
        stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=False, json_output=False, verbose=False, min_severity="warning",
    )
    assert rc == 0
    comment_calls = [
        c for c in subprocess_capture.calls
        if len(c["cmd"]) >= 3 and c["cmd"][:3] == ["gh", "issue", "comment"]
    ]
    assert len(comment_calls) == 1
    # Confirm no edit/delete subcommands were issued.
    edit_calls = [
        c for c in subprocess_capture.calls
        if "edit" in c["cmd"] or "delete" in c["cmd"]
    ]
    assert edit_calls == []


def test_post_emits_run_marker(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T019 — the rendered comment's first line is the run marker."""
    feed_findings(valid_findings_doc([make_finding(severity="warning")]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=True, json_output=False, verbose=False, min_severity="warning",
    )
    assert rc == 0
    body = capsys.readouterr().out
    first_line = body.lstrip().splitlines()[0]
    import re as _re
    assert _re.match(r"^<!--\s*devkit-review-issue:claude:run-1\s*-->$", first_line)


def test_findings_schema_rejects_bad_input(
    subprocess_capture, standard_path_env, feed_findings
) -> None:
    """T020 — malformed findings JSON exits with E_FINDINGS_INVALID and posts nothing."""
    # Missing the required `findings` field.
    feed_findings(invalid_findings_doc(missing_field="findings"))
    with pytest.raises(typer.Exit) as exc_info:
        review_issue.cmd_review_issue_post(
            ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
            dry_run=False, json_output=False, verbose=False, min_severity="warning",
        )
    assert exc_info.value.exit_code == 74  # E_FINDINGS_INVALID
    comment_calls = [
        c for c in subprocess_capture.calls
        if len(c["cmd"]) >= 3 and c["cmd"][:3] == ["gh", "issue", "comment"]
    ]
    assert comment_calls == []

    # Also: derived-negative-pair without the required `pair` object.
    bad_doc = valid_findings_doc([
        make_finding(category="derived-negative-pair", severity="warning"),  # no pair=
    ])
    feed_findings(bad_doc)
    with pytest.raises(typer.Exit) as exc_info2:
        review_issue.cmd_review_issue_post(
            ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
            dry_run=False, json_output=False, verbose=False, min_severity="warning",
        )
    assert exc_info2.value.exit_code == 74


def test_fetch_error_is_actionable(
    subprocess_capture, standard_path_env, feed_findings, capsys
) -> None:
    """T020a + FR-005 — issue not found exits cleanly with E_REPO_NOT_FOUND, no comment."""
    feed_findings(valid_findings_doc([make_finding(severity="warning")]))
    subprocess_capture.queue(RunResult(
        code=1, stdout="",
        stderr="GraphQL: Could not resolve to an Issue with the number of 999. (repository.issue)",
    ))
    with pytest.raises(typer.Exit) as exc_info:
        review_issue.cmd_review_issue_post(
            ref="App-Empire-LLC/DevKit#999", reviewer_id=None,
            dry_run=False, json_output=False, verbose=False, min_severity="warning",
        )
    assert exc_info.value.exit_code == 13  # E_REPO_NOT_FOUND
    comment_calls = [
        c for c in subprocess_capture.calls
        if len(c["cmd"]) >= 3 and c["cmd"][:3] == ["gh", "issue", "comment"]
    ]
    assert comment_calls == []
    captured_err = capsys.readouterr().err
    assert "DevKit#999" in captured_err
    assert "Could not resolve" in captured_err


# --------------------------------------------------------------------------- #
# Phase 4: User Story 2 — dry-run (T027, T028)
# --------------------------------------------------------------------------- #


def test_dry_run_does_not_post(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T027 — --dry-run records zero comment calls and prints markdown."""
    feed_findings(valid_findings_doc([make_finding(severity="warning")]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=True, json_output=False, verbose=False, min_severity="warning",
    )
    assert rc == 0
    comment_calls = [
        c for c in subprocess_capture.calls
        if len(c["cmd"]) >= 3 and c["cmd"][:3] == ["gh", "issue", "comment"]
    ]
    assert comment_calls == []
    out_text = capsys.readouterr().out
    assert "## Issue Review" in out_text


def test_dry_run_prints_markdown(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T028 — dry-run output contains marker, gate line, and table header."""
    feed_findings(valid_findings_doc([make_finding(severity="warning")]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=True, json_output=False, verbose=False, min_severity="warning",
    )
    assert rc == 0
    out_text = capsys.readouterr().out
    assert "<!-- devkit-review-issue:claude:run-" in out_text
    assert "**Gate**:" in out_text
    assert "| ID | Category | Severity | Location | Summary | Recommendation |" in out_text


# --------------------------------------------------------------------------- #
# Phase 5: User Story 3 — JSON (T031, T032, T033)
# --------------------------------------------------------------------------- #


def test_json_output_validates_schema(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T031 — --json output validates against review-issue-output.schema.json."""
    feed_findings(valid_findings_doc([make_finding(severity="warning")]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    subprocess_capture.queue(RunResult(
        code=0, stdout="https://github.com/App-Empire-LLC/DevKit/issues/42#issuecomment-1\n",
        stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=False, json_output=True, verbose=False, min_severity="warning",
    )
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    jsonschema.validate(envelope, review_issue._OUTPUT_SCHEMA)


def test_json_dry_run_combination(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T032 — --json + --dry-run emits envelope and posts nothing."""
    feed_findings(valid_findings_doc([make_finding(severity="warning")]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=True, json_output=True, verbose=False, min_severity="warning",
    )
    assert rc == 0
    comment_calls = [
        c for c in subprocess_capture.calls
        if len(c["cmd"]) >= 3 and c["cmd"][:3] == ["gh", "issue", "comment"]
    ]
    assert comment_calls == []
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["comment"]["posted"] is False
    assert envelope["comment"]["suppression_reason"] == "dry-run"


def test_json_gate_matches_comment(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T033 — gate string in JSON matches `**Gate**: <value>` in comment (SC-004)."""
    cases = [
        ([make_finding(severity="blocker")], "BLOCKED"),
        ([make_finding(severity="warning")], "READY_WITH_WARNINGS"),
        ([], "READY"),
    ]
    for findings, expected_gate in cases:
        # JSON pass
        feed_findings(valid_findings_doc(findings))
        issue = make_issue_fixture()
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
        review_issue.cmd_review_issue_post(
            ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
            dry_run=True, json_output=True, verbose=False, min_severity="warning",
        )
        envelope = json.loads(capsys.readouterr().out)
        assert envelope["gate"] == expected_gate

        # Markdown pass — same fixtures
        feed_findings(valid_findings_doc(findings))
        subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
        review_issue.cmd_review_issue_post(
            ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
            dry_run=True, json_output=False, verbose=False, min_severity="warning",
        )
        body = capsys.readouterr().out
        assert f"**Gate**: `{expected_gate}`" in body


# --------------------------------------------------------------------------- #
# Phase 6: User Story 4 — verbose / min-severity (T037, T038, T039, T040)
# --------------------------------------------------------------------------- #


def test_verbose_includes_nits_inline(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T037 — --verbose renders each nit as its own row."""
    feed_findings(valid_findings_doc([
        make_finding(fid="F01", severity="warning"),
        make_finding(fid="F02", severity="nit"),
        make_finding(fid="F03", severity="nit"),
    ]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=True, json_output=False, verbose=True, min_severity="warning",
    )
    assert rc == 0
    body = capsys.readouterr().out
    # Each finding ID appears as a row in the table.
    assert "| F01 " in body
    assert "| F02 " in body
    assert "| F03 " in body


def test_default_aggregates_nits(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T038 — without --verbose, nits are aggregated into one row."""
    feed_findings(valid_findings_doc([
        make_finding(fid="F01", severity="warning"),
        make_finding(fid="F02", severity="nit"),
        make_finding(fid="F03", severity="nit"),
    ]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=True, json_output=False, verbose=False, min_severity="warning",
    )
    assert rc == 0
    body = capsys.readouterr().out
    assert "| F01 " in body          # warning still rendered as its own row
    assert "| F02 " not in body      # individual nits aggregated away
    assert "| F03 " not in body
    assert "nit (n=2)" in body
    assert "re-run with --verbose" in body


def test_min_severity_suppresses_post(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T039 — --min-severity warning suppresses post when only nits exist."""
    feed_findings(valid_findings_doc([
        make_finding(fid="F01", severity="nit"),
        make_finding(fid="F02", severity="nit"),
    ]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=False, json_output=False, verbose=False, min_severity="warning",
    )
    assert rc == 0
    comment_calls = [
        c for c in subprocess_capture.calls
        if len(c["cmd"]) >= 3 and c["cmd"][:3] == ["gh", "issue", "comment"]
    ]
    assert comment_calls == []
    captured = capsys.readouterr()
    # Status line goes through info() → out.print → captured stdout, but the
    # gate line is the one that always shows up via the info() helper.
    combined = captured.out + captured.err
    assert "below threshold" in combined or "no comment posted" in combined
    assert "READY" in combined  # gate still computed and shown


def test_min_severity_emits_suppression_in_json(
    subprocess_capture, standard_path_env, capsys, feed_findings
) -> None:
    """T040 — JSON envelope reflects min-severity suppression."""
    feed_findings(valid_findings_doc([make_finding(severity="nit")]))
    issue = make_issue_fixture()
    subprocess_capture.queue(RunResult(code=0, stdout=json.dumps(issue), stderr=""))
    rc = review_issue.cmd_review_issue_post(
        ref="App-Empire-LLC/DevKit#42", reviewer_id=None,
        dry_run=False, json_output=True, verbose=False, min_severity="warning",
    )
    assert rc == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["comment"]["posted"] is False
    assert envelope["comment"]["suppression_reason"] == "below-min-severity"
