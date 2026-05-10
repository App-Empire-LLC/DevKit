"""DevKit `review-issue` — pre-SpecKit issue quality gate (DevKit#17).

Two subcommands compose into the `/devkit.review-issue` slash command:

- ``inspect``: fetch the issue + its comment thread, scan for prior run
  markers, emit a JSON envelope the slash-command markdown (LLM-side)
  consumes to drive its semantic review.
- ``post``: validate a findings JSON document supplied on stdin against
  ``review-issue-findings.schema.json``, compute the gate, render the
  consolidated review comment, optionally post it via ``gh issue comment``.

The split keeps semantic analysis (anti-pattern detection, AC entailment,
ambiguity, derived-negative pairs) in the slash-command markdown where the
LLM does that work naturally, and keeps the Python harness deterministic +
hermetic. All ``gh`` calls flow through ``aidevkit.util.run`` per the
project-wide hermeticity rule.

See ``specs/001-review-issue/`` for the full design (spec, plan, research,
data-model, contracts, tasks, creep notes).
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from importlib.resources import files as _resource_files
from pathlib import Path
from typing import Any

import jsonschema
import typer

from . import __version__
from .config import (
    ReviewIssueConfig,
    load_review_issue_config,
    resolve_projects_home,
)
from .util import (
    E_CONFIG_INVALID,
    E_FINDINGS_INVALID,
    E_GH_COMMENT_FAILED,
    E_REPO_NOT_FOUND,
    die,
    gh,
    info,
    log,
    out,
)

# Regex for parsing prior-run markers on the issue's comment thread.
# Anchored to start-of-line so an HTML comment elsewhere in a body cannot be
# confused with a run marker.
_RUN_MARKER_RE = re.compile(
    r"^<!--\s*devkit-review-issue:([a-z][a-z0-9-]{0,30}):run-(\d+)\s*-->",
    re.MULTILINE,
)

# Issue-ref parser: matches `owner/repo#N`. Mirrors bootstrap.py's _ISSUE_REF.
_ISSUE_REF_RE = re.compile(r"^([^/\s#]+)/([^/\s#]+)#(\d+)$")

_SEVERITY_ORDER = {"blocker": 3, "warning": 2, "nit": 1}
_ANTIPATTERN_CATEGORIES = frozenset(
    {"requirement-leakage", "test-plan-as-ac", "chat-history-dependency"}
)


@dataclass(frozen=True)
class ReviewConfig:
    """Resolved per-invocation review configuration.

    Composes the persisted ``ReviewIssueConfig`` with per-call overrides and
    runtime context (e.g., whether the repo has a project board configured).
    """

    reviewer_id: str
    project_board_required: bool
    # True when gh confirmed a project board exists for the repo. Drives the
    # board-degradation rule in ``_compute_gate``: a "not on board" finding is
    # downgraded blocker→warning when no board exists.
    project_board_available_for_repo: bool = True


# --------------------------------------------------------------------------- #
# Schema loading (cached at module level so tests don't reload on every call)
# --------------------------------------------------------------------------- #


def _load_schema(name: str) -> dict[str, Any]:
    raw = _resource_files("aidevkit.schemas").joinpath(name).read_text()
    return json.loads(raw)


_FINDINGS_SCHEMA = _load_schema("review-issue-findings.schema.json")
_OUTPUT_SCHEMA = _load_schema("review-issue-output.schema.json")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _resolve_review_config(reviewer_id_override: str | None) -> ReviewConfig:
    """Resolve the review config from .devkit/config.yaml + CLI override.

    Priority for reviewer_id (research R4): CLI flag > config > default "claude".
    Falls back to defaults when projects-home isn't resolvable (e.g., running
    outside any DevKit workspace).
    """
    persisted = ReviewIssueConfig()
    try:
        projects_home = resolve_projects_home()
        persisted = load_review_issue_config(projects_home)
    except typer.Exit:
        # No projects-home config — defaults apply. The standard-path resolver
        # (T010) will surface a clearer error if the operator is genuinely in
        # the wrong context.
        pass
    return ReviewConfig(
        reviewer_id=reviewer_id_override or persisted.reviewer_id,
        project_board_required=persisted.project_board_required,
    )


def _resolve_product_request_standard_path() -> Path:
    """Locate the product-request standard.

    Per research R10 / creep K3, the path is hardcoded — no config field.
    Search order:
      1. ``$DEVKIT_REVIEW_ISSUE_STANDARD_PATH`` env var (test hook only).
      2. ``<cwd>/appire_docs/...`` — sibling repo in the workspace.
      3. ``<cwd>/../appire_docs/...`` — sibling at the workspace root.
    Fails with E_CONFIG_INVALID if none resolve.
    """
    rel = "appire_docs/docs/engineering/standards/product_requests.md"
    env_override = os.environ.get("DEVKIT_REVIEW_ISSUE_STANDARD_PATH")
    if env_override:
        candidate = Path(env_override)
        if candidate.is_file():
            return candidate.resolve()
    cwd = Path.cwd()
    for base in (cwd, cwd.parent):
        candidate = base / rel
        if candidate.is_file():
            return candidate.resolve()
    die(
        f"product-request standard not found.\n"
        f"  Expected: <workspace>/{rel}\n"
        f"  Searched: {cwd / rel}\n"
        f"           {cwd.parent / rel}\n"
        f"  Likely cause: appire_docs is not checked out as a sibling repo in this workspace.\n"
        f"  Fix: clone or worktree appire_docs alongside the repo you're reviewing from.",
        code=E_CONFIG_INVALID,
    )
    raise AssertionError("die() should have exited")  # pragma: no cover


def _parse_ref(ref: str) -> tuple[str, str, int]:
    """Split `owner/repo#N` → (owner, repo, num). gh CLI doesn't accept the
    combined form for `issue view`, so callers split and pass `--repo` + num.
    """
    m = _ISSUE_REF_RE.match(ref)
    if not m:
        die(
            f"issue ref must be in form 'owner/repo#N' (got: {ref!r})",
            code=2,  # E_USAGE
        )
    return m.group(1), m.group(2), int(m.group(3))


def _fetch_issue(ref: str) -> dict[str, Any]:
    """Fetch the issue body, comments, labels, and project items via gh.

    Raises E_REPO_NOT_FOUND when gh reports the issue doesn't exist or is
    inaccessible. Other gh failures bubble up as E_GH_COMMENT_FAILED-equivalent
    errors via the caller (post-mode only — inspect treats them as terminal).
    """
    owner, repo, num = _parse_ref(ref)
    result = gh(
        "issue", "view", str(num),
        "--repo", f"{owner}/{repo}",
        "--json", "number,url,title,body,labels,assignees,milestone,projectItems,comments",
    )
    if result.code != 0:
        stderr = result.stderr or ""
        if "could not resolve" in stderr.lower() or "not found" in stderr.lower():
            die(
                f"issue not found or inaccessible: {ref}\n"
                f"  gh stderr: {stderr.strip()}\n"
                f"  Fix: confirm the ref is correct and `gh auth status` shows access.",
                code=E_REPO_NOT_FOUND,
            )
        die(
            f"failed to fetch issue {ref}.\n"
            f"  gh exit: {result.code}\n"
            f"  gh stderr: {stderr.strip()}",
            code=E_REPO_NOT_FOUND,
        )
    return json.loads(result.stdout)


def _scan_prior_runs(comments: list[dict[str, Any]]) -> list[tuple[str, int]]:
    """Extract (reviewer_id, n) tuples from prior review comments.

    Anchored to start-of-line via re.MULTILINE so the marker must be at the
    top of a line. Returns the full list (unsorted, in source order).
    """
    out_pairs: list[tuple[str, int]] = []
    for c in comments:
        body = c.get("body") or ""
        for m in _RUN_MARKER_RE.finditer(body):
            out_pairs.append((m.group(1), int(m.group(2))))
    return out_pairs


def _next_n_for(prior_runs: list[tuple[str, int]], reviewer_id: str) -> int:
    matching = [n for r, n in prior_runs if r == reviewer_id]
    return (max(matching) + 1) if matching else 1


# --------------------------------------------------------------------------- #
# Gate + render + post
# --------------------------------------------------------------------------- #


def _normalize_findings(
    findings: list[dict[str, Any]], policy: ReviewConfig,
) -> list[dict[str, Any]]:
    """Apply policy normalizations to findings before gate computation.

    Currently: when the repo has no project board configured, demote any
    ``board-hygiene`` finding from ``blocker`` to ``warning`` so a missing
    board doesn't block a repo that doesn't use boards. Returns a new list.
    """
    if policy.project_board_available_for_repo:
        return findings
    out_list: list[dict[str, Any]] = []
    for f in findings:
        if f.get("category") == "board-hygiene" and f.get("severity") == "blocker":
            demoted = dict(f)
            demoted["severity"] = "warning"
            out_list.append(demoted)
        else:
            out_list.append(f)
    return out_list


def _compute_gate(findings: list[dict[str, Any]], policy: ReviewConfig) -> str:
    """Compute the gate result from the findings list.

    Pure function (after the normalize pass). Per spec FR-012 / data-model §4:
      - any blocker → BLOCKED
      - else any warning → READY_WITH_WARNINGS
      - else → READY (nits don't gate)
    """
    normalized = _normalize_findings(findings, policy)
    severities = {f.get("severity") for f in normalized}
    if "blocker" in severities:
        return "BLOCKED"
    if "warning" in severities:
        return "READY_WITH_WARNINGS"
    return "READY"


def _compute_metrics(findings: list[dict[str, Any]]) -> dict[str, int]:
    blockers = sum(1 for f in findings if f.get("severity") == "blocker")
    warnings = sum(1 for f in findings if f.get("severity") == "warning")
    nits = sum(1 for f in findings if f.get("severity") == "nit")
    antipatterns = sum(1 for f in findings if f.get("category") in _ANTIPATTERN_CATEGORIES)
    pairs = sum(1 for f in findings if f.get("category") == "derived-negative-pair")
    return {
        "total": len(findings),
        "blockers": blockers,
        "warnings": warnings,
        "nits": nits,
        "antipatterns": antipatterns,
        "derived_negative_pairs": pairs,
    }


def _escape_cell(text: str) -> str:
    """Escape pipe and newline so a cell stays inside the markdown table."""
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _render_row(f: dict[str, Any]) -> str:
    return (
        f"| {f['id']} "
        f"| {_escape_cell(f['category'])} "
        f"| {f['severity']} "
        f"| {_escape_cell(f['location'])} "
        f"| {_escape_cell(f['summary'])} "
        f"| {_escape_cell(f['recommendation'])} |"
    )


def _render_comment(
    reviewer_id: str,
    n: int,
    findings: list[dict[str, Any]],
    gate: str,
    policy: ReviewConfig,
    verbose: bool = False,
) -> str:
    """Render the consolidated review comment markdown.

    Per research R6 + data-model §5: marker on line 1, gate, findings table,
    metrics, footer. Default mode aggregates nits into one row whose Summary
    points at --verbose; verbose mode renders each nit as its own row.
    """
    normalized = _normalize_findings(findings, policy)
    metrics = _compute_metrics(normalized)
    nits = [f for f in normalized if f.get("severity") == "nit"]
    non_nits = [f for f in normalized if f.get("severity") != "nit"]

    lines: list[str] = []
    lines.append(f"<!-- devkit-review-issue:{reviewer_id}:run-{n} -->")
    lines.append("")
    lines.append("## Issue Review")
    lines.append("")
    lines.append(f"**Gate**: `{gate}`")
    lines.append("")
    lines.append("| ID | Category | Severity | Location | Summary | Recommendation |")
    lines.append("|----|----------|----------|----------|---------|----------------|")
    if not non_nits and not nits:
        lines.append("| — | (none) | — | — | No findings — issue is clean. | — |")
    for f in non_nits:
        lines.append(_render_row(f))
    if verbose:
        for f in nits:
            lines.append(_render_row(f))
    elif nits:
        count = len(nits)
        plural = "s" if count != 1 else ""
        lines.append(
            f"| — | nit (n={count}) | nit | (multiple) "
            f"| {count} nit-level finding{plural} — "
            f"re-run with --verbose to inspect "
            f"| — |"
        )
    lines.append("")
    lines.append(
        f"**Metrics**: {metrics['total']} findings · "
        f"{metrics['blockers']} blocker{'s' if metrics['blockers'] != 1 else ''} · "
        f"{metrics['warnings']} warning{'s' if metrics['warnings'] != 1 else ''} · "
        f"{metrics['nits']} nit{'s' if metrics['nits'] != 1 else ''} · "
        f"{metrics['antipatterns']} anti-pattern{'s' if metrics['antipatterns'] != 1 else ''} · "
        f"{metrics['derived_negative_pairs']} derived-negative pair"
        f"{'s' if metrics['derived_negative_pairs'] != 1 else ''}"
    )
    lines.append("")
    lines.append(f"> Generated by `/devkit.review-issue` (run {n}). Re-run to refresh.")
    return "\n".join(lines)


def _post_comment(ref: str, body: str) -> str:
    """Post the consolidated comment via gh.

    Uses a tempfile (rather than extending util.run to accept stdin input) so
    the shell seam stays unchanged and other callers aren't affected. Returns
    the posted comment URL parsed from gh's stdout.
    """
    owner, repo, num = _parse_ref(ref)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    )
    try:
        tmp.write(body)
        tmp.close()
        result = gh(
            "issue", "comment", str(num),
            "--repo", f"{owner}/{repo}",
            "--body-file", tmp.name,
        )
        if result.code != 0:
            die(
                f"`gh issue comment` failed for {ref}.\n"
                f"  gh exit: {result.code}\n"
                f"  gh stderr: {(result.stderr or '').strip()}",
                code=E_GH_COMMENT_FAILED,
            )
        return (result.stdout or "").strip()
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# JSON envelope
# --------------------------------------------------------------------------- #


def _build_inspect_envelope(
    issue: dict[str, Any],
    config: ReviewConfig,
    prior_runs: list[tuple[str, int]],
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "issue": {
            "ref": _ref_from_issue(issue),
            "url": issue.get("url", ""),
        },
        "reviewer": {"id": config.reviewer_id, "version": __version__},
        "run": {
            "n_next": _next_n_for(prior_runs, config.reviewer_id),
            "started_at": _now_iso(),
        },
        "policy": {"project_board_required": config.project_board_required},
        "prior_runs": [{"reviewer_id": r, "n": n} for r, n in prior_runs],
    }


def _emit_json_envelope(
    issue: dict[str, Any],
    config: ReviewConfig,
    n: int,
    gate: str,
    findings: list[dict[str, Any]],
    comment_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "1",
        "issue": {
            "ref": _ref_from_issue(issue),
            "url": issue.get("url", ""),
        },
        "reviewer": {"id": config.reviewer_id, "version": __version__},
        "run": {"n": n, "started_at": _now_iso()},
        "policy": {"project_board_required": config.project_board_required},
        "gate": gate,
        "findings": findings,
        "metrics": _compute_metrics(_normalize_findings(findings, config)),
        "comment": comment_state,
    }


def _ref_from_issue(issue: dict[str, Any]) -> str:
    """Derive 'owner/repo#N' from the gh JSON issue payload's url field."""
    url = issue.get("url", "")
    m = re.match(r"https?://github\.com/([^/]+/[^/]+)/issues/(\d+)", url)
    if m:
        return f"{m.group(1)}#{m.group(2)}"
    # Fallback: just the issue number — sufficient for tests, never hit in prod.
    return f"unknown#{issue.get('number', 0)}"


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #


def cmd_review_issue_inspect(ref: str, reviewer_id: str | None) -> int:
    """Fetch issue + prior runs, emit JSON envelope to stdout."""
    config = _resolve_review_config(reviewer_id)
    _resolve_product_request_standard_path()  # fail-fast on missing standard
    issue = _fetch_issue(ref)
    prior = _scan_prior_runs(issue.get("comments") or [])
    envelope = _build_inspect_envelope(issue, config, prior)
    print(json.dumps(envelope))
    return 0


_SEVERITY_LEVELS = ("blocker", "warning", "nit")


def cmd_review_issue_post(
    ref: str,
    reviewer_id: str | None,
    dry_run: bool,
    json_output: bool,
    verbose: bool,
    min_severity: str,
) -> int:
    """Validate findings JSON from stdin → render → post (unless suppressed)."""
    if min_severity not in _SEVERITY_LEVELS:
        die(
            f"--min-severity must be one of {list(_SEVERITY_LEVELS)} (got {min_severity!r})",
            code=2,
        )

    raw = sys.stdin.read()
    if not raw.strip():
        die(
            "no findings JSON on stdin. Pipe a document conforming to "
            "review-issue-findings.schema.json into `devkit review-issue post`.",
            code=E_FINDINGS_INVALID,
        )
    try:
        findings_doc = json.loads(raw)
    except json.JSONDecodeError as exc:
        die(f"findings stdin is not valid JSON: {exc}", code=E_FINDINGS_INVALID)
    try:
        jsonschema.validate(findings_doc, _FINDINGS_SCHEMA)
    except jsonschema.ValidationError as exc:
        die(
            f"findings JSON failed schema validation.\n"
            f"  Path: {'/'.join(str(p) for p in exc.absolute_path) or '(root)'}\n"
            f"  Problem: {exc.message}",
            code=E_FINDINGS_INVALID,
        )

    config = _resolve_review_config(reviewer_id)
    _resolve_product_request_standard_path()  # fail-fast on missing standard
    issue = _fetch_issue(ref)
    prior = _scan_prior_runs(issue.get("comments") or [])
    n = _next_n_for(prior, config.reviewer_id)
    findings = findings_doc.get("findings", [])
    gate = _compute_gate(findings, config)

    # Decide whether to suppress posting under --min-severity.
    threshold = _SEVERITY_ORDER[min_severity]
    above_threshold = [
        f for f in findings if _SEVERITY_ORDER.get(f.get("severity"), 0) >= threshold
    ]
    suppress_for_severity = len(above_threshold) == 0

    body = _render_comment(config.reviewer_id, n, findings, gate, config, verbose=verbose)

    comment_state: dict[str, Any]
    if dry_run:
        comment_state = {"posted": False, "suppression_reason": "dry-run"}
        if not json_output:
            out.print(body)
            info(f"gate: {gate} (dry-run; nothing posted)")
    elif suppress_for_severity:
        comment_state = {"posted": False, "suppression_reason": "below-min-severity"}
        if not json_output:
            info(
                f"gate: {gate} — no comment posted; "
                f"all findings below threshold {min_severity}"
            )
    else:
        url = _post_comment(ref, body)
        comment_state = {"posted": True, "url": url} if url else {"posted": True}
        if not json_output:
            info(f"gate: {gate}")
            if url:
                info(f"posted run-{n} comment: {url}")
            else:
                info(f"posted run-{n} comment")

    if json_output:
        envelope = _emit_json_envelope(issue, config, n, gate, findings, comment_state)
        # Validate our own output too (cheap; surfaces drift between code + schema).
        try:
            jsonschema.validate(envelope, _OUTPUT_SCHEMA)
        except jsonschema.ValidationError as exc:  # pragma: no cover
            log(f"internal: output envelope failed self-validation: {exc.message}")
        print(json.dumps(envelope))

    return 0
