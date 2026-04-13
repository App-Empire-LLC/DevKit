#!/usr/bin/env bash
# DevKit — companion tooling for GitHub Spec-Kit
# https://github.com/App-Empire-LLC/DevKit

set -euo pipefail

DEVKIT_VERSION="0.1.0"

# Error codes
E_USAGE=2
E_REPOS_MISSING=10
E_WORKTREE_EXISTS=11
E_DEP_MISSING=12
E_REPO_NOT_FOUND=13

# ---------- utilities ----------

log()  { printf '[devkit] %s\n' "$*" >&2; }
info() { printf '[devkit] %s\n' "$*"; }
die()  { printf '[devkit] ERROR: %s\n' "$1" >&2; exit "${2:-1}"; }

devkit_root() {
    local src="${BASH_SOURCE[0]}"
    while [ -L "$src" ]; do
        local dir
        dir="$(cd -P "$(dirname "$src")" && pwd)"
        src="$(readlink "$src")"
        [[ "$src" != /* ]] && src="$dir/$src"
    done
    (cd -P "$(dirname "$src")/.." && pwd)
}

# ---------- subcommand: doctor ----------

cmd_doctor() {
    local ok=1
    info "DevKit doctor — checking dependencies and environment"

    for dep in bash git gh jq; do
        if command -v "$dep" >/dev/null 2>&1; then
            printf '  [ok]   %-28s %s\n' "$dep" "$(command -v "$dep")"
        else
            printf '  [FAIL] %-28s not found in PATH\n' "$dep"
            ok=0
        fi
    done

    if [ -n "${APP_EMPIRE_PROJECTS:-}" ] && [ -d "${APP_EMPIRE_PROJECTS}" ]; then
        printf '  [ok]   %-28s %s\n' '$APP_EMPIRE_PROJECTS' "$APP_EMPIRE_PROJECTS"
    else
        printf '  [FAIL] %-28s not set or not a directory\n' '$APP_EMPIRE_PROJECTS'
        ok=0
    fi

    if [ -n "${APP_EMPIRE_WORKTREES_HOME:-}" ] && [ -d "${APP_EMPIRE_WORKTREES_HOME}" ]; then
        printf '  [ok]   %-28s %s\n' '$APP_EMPIRE_WORKTREES_HOME' "$APP_EMPIRE_WORKTREES_HOME"
    else
        printf '  [FAIL] %-28s not set or not a directory\n' '$APP_EMPIRE_WORKTREES_HOME'
        ok=0
    fi

    if gh auth status >/dev/null 2>&1; then
        printf '  [ok]   %-28s authenticated\n' 'gh auth'
    else
        printf '  [FAIL] %-28s not authenticated (run: gh auth login)\n' 'gh auth'
        ok=0
    fi

    case ":${PATH}:" in
        *":$HOME/.local/bin:"*)
            printf '  [ok]   %-28s in PATH\n' '~/.local/bin' ;;
        *)
            printf '  [warn] %-28s not in PATH (add: export PATH="$HOME/.local/bin:$PATH")\n' '~/.local/bin' ;;
    esac

    if [ "$ok" -eq 1 ]; then
        info "All checks passed."
        return 0
    else
        die "One or more required checks failed. Fix the issues above and re-run 'devkit doctor'." "$E_DEP_MISSING"
    fi
}

# ---------- subcommand: install ----------

cmd_install() {
    cmd_doctor

    local root; root="$(devkit_root)"
    local bin_target="$HOME/.local/bin/devkit"
    local cmd_dir="$HOME/.claude/commands"

    mkdir -p "$HOME/.local/bin" "$cmd_dir"

    if [ -L "$bin_target" ] || [ -f "$bin_target" ]; then
        rm "$bin_target"
    fi
    ln -s "$root/bin/devkit" "$bin_target"
    info "Linked $bin_target -> $root/bin/devkit"

    local count=0
    for f in "$root/.claude/commands/"devkit.*.md; do
        [ -e "$f" ] || continue
        local name; name="$(basename "$f")"
        local target="$cmd_dir/$name"
        if [ -L "$target" ] || [ -f "$target" ]; then
            rm "$target"
        fi
        ln -s "$f" "$target"
        count=$((count + 1))
    done
    info "Linked $count slash command(s) into $cmd_dir/"

    info "Install complete."
}

# ---------- subcommand: bootstrap ----------

bootstrap_usage() {
    cat <<EOF
usage: devkit bootstrap <owner/repo#N> [--repos owner/a,owner/b] [--dry-run] [--no-ack]

Create a per-issue worktree directory at
  \$APP_EMPIRE_WORKTREES_HOME/<repo>-issue-<N>/
containing git worktrees for each affected repo on branch
  issue-<repo>-<N>
and post an ack comment on the GH issue.

Affected repos are determined by, in priority order:
  1. --repos flag (if provided)
  2. '## Affected Repos' section in the issue body (bulleted list of owner/repo)
  3. The issue's home repo (always included unless it's a draft)

appire_docs is always included automatically (required for SpecKit).
Duplicates are suppressed if appire_docs is already in the set.

Error codes:
  2  — usage error
  10 — no affected repos could be determined (draft issue, no list)
  11 — worktree directory already exists
  12 — dependency missing
  13 — source repo not found at \$APP_EMPIRE_PROJECTS
EOF
}

parse_affected_repos() {
    # Stdin: issue body. Stdout: one owner/repo per line.
    awk '
        /^##[[:space:]]+Affected[[:space:]]+Repos[[:space:]]*$/ { in_section=1; next }
        /^##[[:space:]]/ && in_section { exit }
        in_section && /^-[[:space:]]*[^[:space:]]+\/[^[:space:]]+/ {
            sub(/^-[[:space:]]*/, "")
            sub(/[[:space:]].*$/, "")
            print
        }
    '
}

cmd_bootstrap() {
    local issue_arg=""
    local repos_override=""
    local dry_run=0
    local no_ack=0

    while [ $# -gt 0 ]; do
        case "$1" in
            --repos)    repos_override="$2"; shift 2 ;;
            --dry-run)  dry_run=1; shift ;;
            --no-ack)   no_ack=1; shift ;;
            -h|--help)  bootstrap_usage; return 0 ;;
            -*)         bootstrap_usage >&2; die "unknown flag: $1" "$E_USAGE" ;;
            *)
                if [ -z "$issue_arg" ]; then
                    issue_arg="$1"
                else
                    bootstrap_usage >&2
                    die "unexpected argument: $1" "$E_USAGE"
                fi
                shift ;;
        esac
    done

    if [ -z "$issue_arg" ]; then
        bootstrap_usage >&2
        exit "$E_USAGE"
    fi

    # Parse owner/repo#N
    if [[ ! "$issue_arg" =~ ^([^/]+)/([^#]+)#([0-9]+)$ ]]; then
        die "issue must be in form 'owner/repo#number' (got: $issue_arg)" "$E_USAGE"
    fi
    local owner="${BASH_REMATCH[1]}"
    local repo="${BASH_REMATCH[2]}"
    local num="${BASH_REMATCH[3]}"
    local issue_home="$owner/$repo"

    # Require env vars
    [ -n "${APP_EMPIRE_PROJECTS:-}" ] || die "\$APP_EMPIRE_PROJECTS not set (run 'devkit doctor')" "$E_DEP_MISSING"
    [ -n "${APP_EMPIRE_WORKTREES_HOME:-}" ] || die "\$APP_EMPIRE_WORKTREES_HOME not set (run 'devkit doctor')" "$E_DEP_MISSING"
    [ -d "$APP_EMPIRE_WORKTREES_HOME" ] || die "\$APP_EMPIRE_WORKTREES_HOME does not exist: $APP_EMPIRE_WORKTREES_HOME" "$E_DEP_MISSING"

    info "Bootstrapping $issue_home#$num"

    # Fetch issue
    local issue_json
    if ! issue_json="$(gh issue view "$num" --repo "$issue_home" --json title,body,isPinned,url 2>&1)"; then
        die "failed to fetch $issue_home#$num: $issue_json" 1
    fi

    local title body url
    title="$(printf '%s' "$issue_json" | jq -r '.title')"
    body="$(printf '%s' "$issue_json" | jq -r '.body // ""')"
    url="$(printf '%s' "$issue_json" | jq -r '.url')"

    info "Issue: $title"
    info "URL:   $url"

    # Resolve affected repos
    local repo_set_str=""
    if [ -n "$repos_override" ]; then
        repo_set_str="$(printf '%s\n' "$repos_override" | tr ',' '\n' | sed '/^$/d')"
        log "using --repos override"
    else
        repo_set_str="$(printf '%s\n' "$body" | parse_affected_repos || true)"
    fi

    # Always include the issue's home repo (when we know it — we always do, since
    # 'gh issue view owner/repo#N' succeeded, meaning the issue has a repo).
    # If the user explicitly passed --repos and omitted the home repo, we still
    # add it silently and log — intent is "edit the issue's home plus these extras".
    if ! printf '%s\n' "$repo_set_str" | grep -qxF "$issue_home"; then
        if [ -n "$repo_set_str" ]; then
            log "adding issue's home repo to set: $issue_home"
        fi
        repo_set_str="$(printf '%s\n%s\n' "$issue_home" "$repo_set_str" | sed '/^$/d')"
    fi

    # Always include appire_docs (SpecKit lives there)
    local appire_docs_repo="$owner/appire_docs"
    if ! printf '%s\n' "$repo_set_str" | grep -qxF "$appire_docs_repo"; then
        log "adding appire_docs to set (required for SpecKit)"
        repo_set_str="$(printf '%s\n%s\n' "$repo_set_str" "$appire_docs_repo" | sed '/^$/d')"
    fi

    if [ -z "$repo_set_str" ]; then
        die "no affected repos could be determined. Add a '## Affected Repos' section to the issue body, or re-run with --repos owner/a,owner/b" "$E_REPOS_MISSING"
    fi

    # Validate each repo exists at $APP_EMPIRE_PROJECTS
    local repo_list=""
    while IFS= read -r full; do
        [ -z "$full" ] && continue
        local reponame="${full##*/}"
        local src="$APP_EMPIRE_PROJECTS/$reponame"
        if [ ! -d "$src/.git" ]; then
            die "source repo not found at $src (from $full)" "$E_REPO_NOT_FOUND"
        fi
        repo_list="${repo_list}${full}\n"
    done <<< "$repo_set_str"

    # Compute worktree dir and branch
    local wt_dir="$APP_EMPIRE_WORKTREES_HOME/${repo}-issue-${num}"
    if [ -e "$wt_dir" ]; then
        die "worktree dir already exists: $wt_dir (archive or remove it first)" "$E_WORKTREE_EXISTS"
    fi
    local branch="issue-${repo}-${num}"

    info "Worktree: $wt_dir"
    info "Branch:   $branch"
    info "Repos:"
    printf '%b' "$repo_list" | sed 's/^/  - /'

    if [ "$dry_run" -eq 1 ]; then
        info ""
        info "[dry-run] would create worktree dir, git init, add worktrees, post ack comment"
        return 0
    fi

    mkdir -p "$wt_dir"
    (cd "$wt_dir" && git init --quiet)

    while IFS= read -r full; do
        [ -z "$full" ] && continue
        local reponame="${full##*/}"
        local src="$APP_EMPIRE_PROJECTS/$reponame"
        info "Adding worktree: $reponame  ($src -> $wt_dir/$reponame, $branch)"
        (cd "$src" && git worktree add "$wt_dir/$reponame" -b "$branch" 2>&1 | sed 's/^/    /')
    done <<< "$repo_set_str"

    # Post ack comment
    if [ "$no_ack" -eq 0 ]; then
        local repos_line
        repos_line="$(printf '%b' "$repo_list" | tr '\n' ' ' | sed 's/ *$//')"
        local comment="Bootstrap started by claude. Worktree: \`$wt_dir\`. Affected repos: ${repos_line}. (Comment auto-posted by devkit-bootstrap.)"
        if gh issue comment "$num" --repo "$issue_home" --body "$comment" >/dev/null 2>&1; then
            info "Posted ack comment on $issue_home#$num"
        else
            log "WARN: failed to post ack comment (continuing)"
        fi
    fi

    info ""
    info "Ready. Start an implementation session with:"
    info ""
    info "    cd $wt_dir && claude"
    info ""
}

# ---------- main dispatch ----------

usage() {
    cat <<EOF
devkit $DEVKIT_VERSION — companion tooling for GitHub Spec-Kit

usage: devkit <subcommand> [args]

subcommands:
  bootstrap <owner/repo#N>   create a per-issue worktree directory
  doctor                     check dependencies and environment
  install                    run doctor then symlink devkit + slash commands
  version                    show version
  help                       show this message

Run 'devkit <subcommand> --help' for subcommand details.
EOF
}

main() {
    if [ $# -eq 0 ]; then
        usage
        exit "$E_USAGE"
    fi
    local sub="$1"; shift
    case "$sub" in
        bootstrap)          cmd_bootstrap "$@" ;;
        doctor)             cmd_doctor "$@" ;;
        install)            cmd_install "$@" ;;
        version|--version)  echo "$DEVKIT_VERSION" ;;
        help|-h|--help)     usage ;;
        *)                  usage >&2; exit "$E_USAGE" ;;
    esac
}

main "$@"
