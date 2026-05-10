---
description: Review a GitHub issue against the App Empire product-request standard before SpecKit handoff
---

# /devkit.review-issue

Pre-SpecKit quality gate. Reviews a GitHub issue against `appire_docs/docs/engineering/standards/product_requests.md` and posts a single consolidated review comment with a `READY` / `READY_WITH_WARNINGS` / `BLOCKED` gate.

This command is operator-explicit only. There is no auto-trigger on issue events or comment activity.

## Usage

The user gives you an issue reference. Either form is accepted:

- Fully qualified: `App-Empire-LLC/DevKit#42`
- Bare (expanded via the `org` config field): `DevKit#42`

```bash
/devkit.review-issue App-Empire-LLC/DevKit#42
/devkit.review-issue DevKit#42
/devkit.review-issue DevKit#42 --dry-run
/devkit.review-issue DevKit#42 --json
/devkit.review-issue DevKit#42 --verbose
/devkit.review-issue DevKit#42 --min-severity warning
```

If the user gives you a bare number with no repo (e.g. `#42`), ask them to confirm the `owner/repo` before running.

## What to do

Orchestrate two sub-invocations of `devkit review-issue`:

### Step 1 — inspect

Run:

```bash
devkit review-issue inspect <ref> [--reviewer-id <id>]
```

Parse the JSON envelope it prints. You'll use `issue.ref`, `issue.url`, the next `run.n_next`, and any `prior_runs` to ground your review.

### Step 2 — read the canon

Read `appire_docs/docs/engineering/standards/product_requests.md`. It's the source of truth for everything below; do not rely on training data.

### Step 3 — apply the detectors

Build a findings list classified by category and severity. Each finding is one of:

**Review Checklist (9 questions from `product_requests.md`)** — for each, emit a `completeness` finding when the answer is "no" or "unclear":

1. Does this issue describe what needs to be true?
2. Did the author accidentally describe how to build it?
3. Are implementation notes clearly separated from acceptance criteria?
4. Would `clarify` or `analyze` complain that the spec contains technical implementation details?
5. Are the acceptance criteria observable and judgeable?
6. Is the out-of-scope section strong enough to prevent scope creep?
7. Could Claude Code implement the wrong thing because the issue is too vague?
8. Could Claude Code over-constrain the spec because the issue is too specific?
9. Does the issue stand alone without relying on chat history?

**Definition of Done for Issue Authoring (8 items from `product_requests.md`)** — for each, emit a `completeness` finding when the item isn't satisfied:

1. Actor and desired outcome are clear.
2. Acceptance criteria describe observable outcomes.
3. Technical details are limited to true constraints.
4. Implementation advice is separated from requirements.
5. Out-of-scope boundaries are explicit.
6. The issue can be understood without reading prior chat history.
7. SpecKit can generate a spec without inheriting accidental implementation requirements.
8. Claude Code has enough context to proceed without guessing product intent.

**Anti-patterns (3, from `product_requests.md`)** — emit one finding per detected instance:

- `requirement-leakage` — implementation choices presented as acceptance criteria (e.g., "Use Ory Kratos for auth").
- `test-plan-as-ac` — acceptance criteria that name test mechanics rather than expected behavior.
- `chat-history-dependency` — issue depends on prior chat history for core meaning.

**Negative-wording pass** — for each AC containing words like "without", "does not", "must not", "not require", "no external", "out of scope", "avoid", "prevent", "never", emit a `negative-wording` finding flagged for operator triage.

**Issue-internal entailment pass** — for each negative AC, ask: *Does any positive AC in the same issue describe a behavior whose verification would catch a violation of this negative?*

- If yes → emit a `derived-negative-pair` finding (severity `warning`) with both AC references and three operator dispositions:
  - `drop` — let SpecKit infer the negative from the positive.
  - `non-goal` — keep as non-goal documentation only, no separate test.
  - `risk-control` — escalate to a hardening test (rare; security/cost/data-loss vectors).
- If no positive counterpart exists → emit only the `negative-wording` finding (no entailment claim).

**Label / project-board hygiene** — emit `label-hygiene` for missing type/project/initiative labels; emit `board-hygiene` (severity `blocker` by default; the harness downgrades to `warning` when no project board exists for the repo) when the issue isn't on a project board with required fields set.

**Explicit exclusions** (do NOT check):

- "Estimates present?" — App Empire does not estimate. The 17 items above are the complete checklist; do not add an estimates-presence check.
- Anything that requires spec / plan / tasks artifacts (the deeper six-category disposition: functional contract / runtime-startup / arch boundary / non-goal / risk control / derived-negative-from-spec). That belongs to `/speckit.analyze`.

### Step 4 — assign IDs

Number the findings `F01`, `F02`, ... in this order: anti-patterns first, then completeness, then derived-negative pairs, then ambiguity, then nits.

### Step 5 — build the findings JSON

Construct a document conforming to `review-issue-findings.schema.json` (shipped at `aidevkit/schemas/`):

```json
{
  "schema_version": "1",
  "findings": [
    {
      "id": "F01",
      "category": "requirement-leakage",
      "severity": "blocker",
      "location": "Acceptance Criteria, item 3",
      "summary": "AC-3 names a specific framework rather than the desired behavior.",
      "recommendation": "Reword as observable behavior; move framework choice to Notes / Context.",
      "evidence": "> AC-3: Use Express for the API."
    }
  ]
}
```

For `derived-negative-pair` findings, include the required `pair` object with `positive_ref`, `negative_ref`, optional `entailment_explanation`, and exactly three `dispositions`:

```json
{
  "id": "F02",
  "category": "derived-negative-pair",
  "severity": "warning",
  "location": "Acceptance Criteria, items 1-2",
  "summary": "AC-2 (does not require cortex-config) is entailed by AC-1 (loads from env var).",
  "recommendation": "Drop AC-2, keep as non-goal documentation, or escalate to a risk-control test.",
  "pair": {
    "positive_ref": "AC-1: loads config from a single env var",
    "negative_ref": "AC-2: does not require cortex-config",
    "entailment_explanation": "Verifying AC-1 verifies AC-2.",
    "dispositions": [
      {"choice": "drop", "description": "Let SpecKit infer the negative."},
      {"choice": "non-goal", "description": "Keep as non-goal documentation only."},
      {"choice": "risk-control", "description": "Escalate to a hardening test (rare)."}
    ]
  }
}
```

### Step 6 — pipe to post

Pipe the findings JSON to:

```bash
devkit review-issue post <ref> --findings-stdin \
  --reviewer-id <id> \
  [--dry-run] [--json] [--verbose] [--min-severity <level>]
```

**Forward all operator-supplied flags verbatim**, and use the SAME `--reviewer-id` value you passed to `inspect` so the run-N counter stays consistent. The harness will validate the findings JSON, compute the gate, render the consolidated comment, and post it (unless suppressed).

## Authoring loop with --dry-run

While iterating on a draft issue, run with `--dry-run`:

```bash
/devkit.review-issue DevKit#42 --dry-run
```

The full findings table and gate are printed in the operator's session; nothing is posted. Re-run as the issue is edited until the gate is `READY`.

## --json mode

Run with `--json` to get a machine-readable envelope conforming to `review-issue-output.schema.json`:

```bash
/devkit.review-issue DevKit#42 --json
```

Use this mode when feeding downstream automation (e.g., a future "promote to Ready" workflow). Combine with `--dry-run` to get the envelope without posting.

## Posting-mode tuning

- `--verbose` — include nit-level findings as their own rows in the comment table. Without this flag, nits are aggregated into a single row whose Summary names the count and points the operator at `--verbose`.
- `--min-severity <level>` — `blocker` / `warning` / `nit`. When all findings are below the threshold, the comment is NOT posted (the gate is still computed and shown locally and via `--json`).

## Common exit codes

- **2** `E_USAGE` — bad ref or unknown flag.
- **13** `E_REPO_NOT_FOUND` — gh says the issue or repo doesn't exist or isn't accessible.
- **70** `E_CONFIG_INVALID` — `.devkit/config.yaml` `review_issue` block fails schema, or the hardcoded product-request standard path can't be found in this workspace (likely cause: `appire_docs` not checked out as a sibling repo).
- **74** `E_FINDINGS_INVALID` — the findings JSON failed schema validation; the harness posts no comment.
- **75** `E_GH_COMMENT_FAILED` — `gh issue comment` returned non-zero; the issue thread is unchanged.

## Notes

- One consolidated comment per run. The slash command never posts per-finding comments.
- Each comment carries an HTML marker `<!-- devkit-review-issue:<reviewer-id>:run-N -->` on its first line. Re-runs add a new comment with an incremented `run-N`; prior comments are not edited or deleted by the harness.
- The product-request standard's path is locked at `appire_docs/docs/engineering/standards/product_requests.md` per spec FR-006 (configurability deferred — see `specs/001-review-issue/creep.md` K3).
- The default gate policy (per spec FR-012):
  - `BLOCKED` — no summary, no AC section, no observable outcome, all ACs are implementation detail (Requirement Leakage), or issue not on a project board (when the repo has one).
  - `READY_WITH_WARNINGS` — ambiguity placeholders ("TBD", "we'll figure out"), AC duplication or entailment, broad prohibitions, missing labels, missing parent-epic reference where applicable, negatives needing operator triage.
  - `READY` — none of the above. Nits may still be present.
- Run from any directory; the command does not require a per-issue workspace. It does require `appire_docs` to be checked out as a sibling repo so the standard resolves.
