"""Archive a completed per-issue worktree.

Reads spec.md files from the worktree, posts them as comments on the target
GitHub issue (splitting oversized specs into multiple comments), closes the
issue, moves the worktree directory into `_archived/`, and prunes dangling
`git worktree` registrations in each upstream repo.

See `specs/4-archive-subcommand/spec.md` for the full specification and
`specs/4-archive-subcommand/research.md` for implementation decisions.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from .util import (
    E_ARCHIVE_COLLISION,
    E_DEP_MISSING,
    E_PRS_NOT_MERGED,
    E_USAGE,
    E_WORKSPACE_MISSING,
    die,
    gh,
    git,
    info,
    log,
)

_ISSUE_REF = re.compile(r"^([^/]+)/([^#]+)#(\d+)$")
_BARE_NUM = re.compile(r"^#?(\d+)$")
_REMOTE_GITHUB = re.compile(
    r"^(?:https://github\.com/|git@github\.com:)([^/]+)/([^/]+?)(?:\.git)?$"
)

COMMENT_SIZE_THRESHOLD = 60_000
COMMENT_SIZE_WINDOW = 500


def _check_deps() -> None:
    for binary in ("git", "gh"):
        if shutil.which(binary) is None:
            die(f"{binary} not found in PATH (run 'devkit doctor')", code=E_DEP_MISSING)

    if not os.environ.get("APP_EMPIRE_WORKTREES_HOME"):
        die(
            "$APP_EMPIRE_WORKTREES_HOME not set (run 'devkit doctor')",
            code=E_DEP_MISSING,
        )
    if not Path(os.environ["APP_EMPIRE_WORKTREES_HOME"]).is_dir():
        die(
            f"$APP_EMPIRE_WORKTREES_HOME does not point at a directory: "
            f"{os.environ['APP_EMPIRE_WORKTREES_HOME']}",
            code=E_DEP_MISSING,
        )


def _parse_issue_ref(issue_arg: str) -> tuple[Optional[str], Optional[str], int]:
    """Parse `owner/repo#N` or bare `N`/`#N`. Returns (owner, repo, num).

    For the bare form, (owner, repo) are None and the caller must infer from CWD.
    """
    m = _ISSUE_REF.match(issue_arg)
    if m:
        return m.group(1), m.group(2), int(m.group(3))
    m = _BARE_NUM.match(issue_arg)
    if m:
        return None, None, int(m.group(1))
    die(
        f"issue must be in form 'owner/repo#N' or bare '#N' (got: {issue_arg})",
        code=E_USAGE,
    )
    return None, None, 0  # unreachable — die raises


def _infer_from_cwd(num: int) -> Optional[tuple[str, Path]]:
    """Return (repo_name, workspace_path) if CWD is inside a matching per-issue workspace.

    Walks up from `Path.cwd()` looking for an ancestor directly under
    $APP_EMPIRE_WORKTREES_HOME whose name matches `<Repo>-issue-<N>`.
    """
    home = Path(os.environ["APP_EMPIRE_WORKTREES_HOME"]).resolve()
    cwd = Path.cwd().resolve()
    current = cwd
    while current != current.parent:
        if current.parent == home:
            name = current.name
            suffix = f"-issue-{num}"
            if name.endswith(suffix):
                repo = name[: -len(suffix)]
                return repo, current
            return None
        current = current.parent
    return None


def _resolve_issue(
    issue_arg: str,
) -> tuple[str, str, int, Path]:
    """Return (owner, repo, num, workspace_path) or die."""
    owner, repo, num = _parse_issue_ref(issue_arg)
    home = Path(os.environ["APP_EMPIRE_WORKTREES_HOME"])

    if owner is None or repo is None:
        inferred = _infer_from_cwd(num)
        if inferred is None:
            die(
                f"cannot infer owner/repo from CWD for bare '#{num}'. "
                f"Pass 'owner/repo#{num}' explicitly.",
                code=E_USAGE,
            )
        repo, workspace = inferred
        # Try to recover owner from a subdir's remote (best-effort); fall back
        # to assuming the issue's home owner matches the first sibling repo we
        # can probe. If we can't determine owner, die with a clear message.
        upstream_info = _discover_upstream_repos(workspace)
        for owner_repo, _path in upstream_info:
            candidate_owner, candidate_repo = owner_repo.split("/", 1)
            if candidate_repo == repo:
                owner = candidate_owner
                break
        if owner is None:
            die(
                f"inferred repo '{repo}' from CWD but could not determine owner "
                f"from worktree remotes. Pass 'owner/{repo}#{num}' explicitly.",
                code=E_USAGE,
            )
    else:
        workspace = home / f"{repo}-issue-{num}"

    return owner, repo, num, workspace


def _discover_upstream_repos(workspace: Path) -> list[tuple[str, Path]]:
    """Return list of (owner/repo, upstream_path) for each worktree subdir.

    Each entry represents one upstream repo that has a registered worktree
    inside `workspace`. Non-worktree subdirs (e.g., `specs/`) are ignored.
    """
    found: list[tuple[str, Path]] = []
    if not workspace.is_dir():
        return found

    for subdir in sorted(workspace.iterdir()):
        if not subdir.is_dir():
            continue
        dotgit = subdir / ".git"
        if not dotgit.is_file():
            continue

        # `.git` file format: "gitdir: <abs path to upstream/.git/worktrees/<name>>"
        content = dotgit.read_text()
        m = re.match(r"gitdir:\s*(.+)$", content.strip())
        if not m:
            continue
        worktree_gitdir = Path(m.group(1)).resolve()
        # Upstream root is the parent of <upstream>/.git/worktrees/<name>
        # i.e., worktree_gitdir.parent.parent.parent
        try:
            upstream_root = worktree_gitdir.parent.parent.parent
        except Exception:
            continue
        if not upstream_root.is_dir():
            continue

        remote_res = git("remote", "get-url", "origin", cwd=upstream_root)
        if remote_res.code != 0:
            continue
        owner_repo = _parse_owner_repo_from_url(remote_res.stdout.strip())
        if owner_repo is None:
            continue
        found.append((owner_repo, upstream_root))

    return found


def _parse_owner_repo_from_url(url: str) -> Optional[str]:
    """Extract 'owner/repo' from a GitHub HTTPS or SSH URL."""
    m = _REMOTE_GITHUB.match(url)
    if not m:
        return None
    return f"{m.group(1)}/{m.group(2)}"


def _check_prs_merged(
    repos: list[tuple[str, Path]],
    branch: str,
) -> list[str]:
    """Return list of blocker descriptions (empty list == all merged).

    A "blocker" is any PR on `branch` in any repo with state != 'MERGED'.
    """
    blockers: list[str] = []
    for owner_repo, _path in repos:
        res = gh(
            "pr", "list",
            "--repo", owner_repo,
            "--head", branch,
            "--state", "all",
            "--json", "number,state,url",
        )
        if res.code != 0:
            # Treat query failure as a blocker — we can't verify safety.
            blockers.append(
                f"{owner_repo} — failed to query PRs: "
                f"{res.stderr.strip() or res.stdout.strip()}"
            )
            continue
        try:
            prs = json.loads(res.stdout or "[]")
        except json.JSONDecodeError:
            blockers.append(f"{owner_repo} — unparseable PR list")
            continue
        for pr in prs:
            if pr.get("state") != "MERGED":
                blockers.append(
                    f"{owner_repo}#{pr.get('number')} ({pr.get('state')}) — "
                    f"{pr.get('url')}"
                )
    return blockers


def _find_spec_files(workspace: Path) -> list[Path]:
    """Return sorted list of `<workspace>/specs/*/spec.md` paths (one level deep)."""
    specs_dir = workspace / "specs"
    if not specs_dir.is_dir():
        return []
    return sorted(specs_dir.glob("*/spec.md"))


def _split_for_comments(
    text: str,
    threshold: int = COMMENT_SIZE_THRESHOLD,
    window: int = COMMENT_SIZE_WINDOW,
) -> list[str]:
    """Split `text` into chunks of at most `threshold` characters each.

    Prefers splitting at a trailing newline within the last `window` chars of
    each threshold-sized slice, so splits land on line boundaries when possible.
    Falls back to a hard split at exactly `threshold` when no newline sits in
    the window.
    """
    if len(text) <= threshold:
        return [text]
    slices: list[str] = []
    remaining = text
    while len(remaining) > threshold:
        search_start = threshold - window
        candidate = remaining[:threshold]
        newline_idx = candidate.rfind("\n", search_start, threshold)
        split_at = newline_idx + 1 if newline_idx != -1 else threshold
        slices.append(remaining[:split_at])
        remaining = remaining[split_at:]
    if remaining:
        slices.append(remaining)
    return slices


def _post_spec_comments(
    owner_repo: str,
    num: int,
    spec_paths: list[Path],
) -> int:
    """Post each spec.md (splitting if oversized). Returns total comment count posted."""
    if not spec_paths:
        info("no spec artifact found; skipping issue comment")
        return 0

    posted = 0
    for spec_path in spec_paths:
        text = spec_path.read_text()
        slices = _split_for_comments(text)
        total = len(slices)
        rel = spec_path.name
        try:
            rel = str(spec_path.relative_to(spec_path.parents[2]))
        except (IndexError, ValueError):
            pass

        for i, chunk in enumerate(slices, start=1):
            prefix = (
                f"> **Archived spec.md — part {i} of {total}** "
                f"(from `{rel}`)\n\n"
            )
            body = prefix + chunk
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".md", delete=False
            ) as tf:
                tf.write(body)
                body_path = tf.name
            try:
                res = gh(
                    "issue", "comment", str(num),
                    "--repo", owner_repo,
                    "--body-file", body_path,
                )
            finally:
                try:
                    os.unlink(body_path)
                except OSError:
                    pass
            if res.code != 0:
                raise RuntimeError(
                    f"failed to post spec comment part {i}/{total} for {rel}: "
                    f"{res.stderr.strip() or res.stdout.strip()}"
                )
            posted += 1
            out_url = res.stdout.strip()
            info(f"posted comment {i}/{total} for {rel}: {out_url}")
    return posted


def _close_issue_if_open(owner_repo: str, num: int) -> str:
    """Close the issue if it's currently open. Returns 'closed', 'already-closed', or 'skipped'."""
    res = gh(
        "issue", "view", str(num),
        "--repo", owner_repo,
        "--json", "state",
    )
    if res.code != 0:
        log(
            f"WARN: could not read issue state for {owner_repo}#{num}: "
            f"{res.stderr.strip() or res.stdout.strip()}"
        )
        return "skipped"
    try:
        payload = json.loads(res.stdout or "{}")
    except json.JSONDecodeError:
        return "skipped"
    state = (payload.get("state") or "").upper()
    if state == "CLOSED":
        return "already-closed"
    close_res = gh("issue", "close", str(num), "--repo", owner_repo)
    if close_res.code != 0:
        log(
            f"WARN: failed to close {owner_repo}#{num}: "
            f"{close_res.stderr.strip() or close_res.stdout.strip()}"
        )
        return "skipped"
    return "closed"


def _move_to_archived(workspace: Path) -> Path:
    """Move `workspace` under `<home>/_archived/`. Returns the destination path."""
    archived_root = workspace.parent / "_archived"
    archived_root.mkdir(parents=True, exist_ok=True)
    dest = archived_root / workspace.name
    shutil.move(str(workspace), str(dest))
    return dest


def _prune_worktrees(
    repos: list[tuple[str, Path]],
    original_workspace: Path,
) -> list[str]:
    """Run `git worktree prune` in each upstream. Returns lingering-entry warnings."""
    warnings: list[str] = []
    original_str = str(original_workspace)
    for owner_repo, upstream_path in repos:
        prune_res = git("worktree", "prune", cwd=upstream_path)
        if prune_res.code != 0:
            warnings.append(
                f"{owner_repo}: prune failed — "
                f"{prune_res.stderr.strip() or prune_res.stdout.strip()}"
            )
            continue
        list_res = git("worktree", "list", "--porcelain", cwd=upstream_path)
        if list_res.code != 0:
            continue
        for line in list_res.stdout.splitlines():
            if line.startswith("worktree ") and original_str in line:
                warnings.append(
                    f"{owner_repo}: stale worktree registration still present — "
                    f"{line[len('worktree '):].strip()}"
                )
    return warnings


def cmd_archive(
    issue_arg: str,
    force: bool = False,
    dry_run: bool = False,
) -> int:
    _check_deps()
    owner, repo, num, workspace = _resolve_issue(issue_arg)
    issue_home = f"{owner}/{repo}"
    branch = f"issue-{repo}-{num}"

    info(f"Archiving {issue_home}#{num}")
    info(f"Workspace: {workspace}")

    if not workspace.exists():
        die(f"workspace does not exist: {workspace}", code=E_WORKSPACE_MISSING)

    repos = _discover_upstream_repos(workspace)
    if repos:
        info("Upstream repos (enlisted):")
        for owner_repo, upstream in repos:
            info(f"  - {owner_repo}  ({upstream})")
    else:
        info("No upstream worktrees discovered in workspace.")

    blockers = _check_prs_merged(repos, branch)
    if blockers:
        if not force:
            log(f"ERROR: {len(blockers)} PR(s) not merged on '{branch}':")
            for b in blockers:
                log(f"  - {b}")
            log("Re-run with --force to override (at your own risk).")
            return E_PRS_NOT_MERGED
        log(f"WARN: proceeding with --force despite {len(blockers)} unmerged PR(s):")
        for b in blockers:
            log(f"  - {b}")
    else:
        info(f"PRs checked on '{branch}': all merged ✓")

    spec_paths = _find_spec_files(workspace)
    if spec_paths:
        info(f"Spec files found ({len(spec_paths)}):")
        for p in spec_paths:
            size = p.stat().st_size
            parts = len(_split_for_comments(p.read_text()))
            info(f"  - {p.name} ({size} chars, {parts} comment(s))")
    else:
        info("Spec files found: 0 (no spec.md in workspace/specs/*/)")

    archived_root = workspace.parent / "_archived"
    dest = archived_root / workspace.name
    if dest.exists():
        die(
            f"_archived/ collision: {dest} already exists. "
            f"Resolve the conflict (rename or delete the existing archive) and retry.",
            code=E_ARCHIVE_COLLISION,
        )

    if dry_run:
        info("")
        info("[dry-run] Planned actions (no changes made):")
        info(f"  - Post {sum(len(_split_for_comments(p.read_text())) for p in spec_paths)} "
             f"comment(s) on {issue_home}#{num}")
        info(f"  - Close {issue_home}#{num} (if not already closed)")
        info(f"  - Move {workspace} → {dest}")
        info(f"  - Run `git worktree prune` in {len(repos)} upstream repo(s)")
        return 0

    comments_posted = _post_spec_comments(issue_home, num, spec_paths)
    close_status = _close_issue_if_open(issue_home, num)
    dest_path = _move_to_archived(workspace)
    prune_warnings = _prune_worktrees(repos, workspace)

    info("")
    info("Archive complete:")
    if spec_paths:
        info(f"  - Spec comments posted: {comments_posted}")
    else:
        info("  - Spec comments posted: 0 (no spec.md found)")
    info(f"  - Issue {issue_home}#{num}: {close_status}")
    info(f"  - Worktree moved to: {dest_path}")
    info(f"  - Worktree prunes run in {len(repos)} upstream repo(s)")
    if prune_warnings:
        log("Post-prune warnings:")
        for w in prune_warnings:
            log(f"  - {w}")
    return 0
