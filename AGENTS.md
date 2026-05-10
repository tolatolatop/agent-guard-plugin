# AGENTS.md

## Project Overview

This repository implements an agent runtime guard plugin for long-running coding tasks.

The plugin’s purpose is not to make the model smarter. Its purpose is to make long-running agent work observable, resumable, interruptible, and harder to derail.

It provides lightweight workflow enforcement around coding agents by using:

- external state files
- hook scripts
- command and result logging
- path and stage gates
- failure-loop detection
- job polling controls
- finalization gates

The plugin is inspired by workflow-harness systems such as Superpowers, but this project focuses on hardening runtime behavior rather than only injecting process instructions.

## Core Product Goal

Build a minimal plugin named `agent-guard-plugin`.

The plugin should reduce these failure modes:

- the model stops before completing all planned steps
- the model claims completion without verification
- the model starts implementation before writing a failing test
- the model repeatedly reruns the same failing command
- the model fails to monitor long-running jobs
- the model polls long-running jobs too frequently
- the model modifies files outside the allowed task scope
- the model loses task state after session restart or context compaction

## Non-Goals

Do not build a full agent runtime.

Do not build a model scheduler.

Do not build complex multi-agent orchestration in the first version.

Do not attempt to semantically prove code correctness.

Do not rely on the model’s self-report as proof of completion.

## Architecture Principles

1. State is externalized.
   The current stage, step, job status, verification status, and failure state must be stored in files under `.agent/`.

2. Hooks are thin.
   Hook scripts should delegate to the core CLI. Avoid putting business logic directly in shell scripts.

3. Gates are explicit.
   A step is complete only when the corresponding state and artifacts prove it.

4. Failures require analysis.
   Repeating the same failed command without code or test changes must be blocked.

5. Finalization is gated.
   The agent must not claim task completion unless the finalization gate passes.

6. Keep the first version small.
   Prefer a correct, minimal implementation over a broad but fragile system.

## Runtime Directory Layout

The plugin should create and manage this directory inside the target repository:

```text
.agent/
  state.json
  plan.yaml
  jobs.json
  failures.json
  events.jsonl
  artifacts/
    design.md
    red-test.log
    green-test.log
    failure-analysis.md
    review.json
    final-verification.log
```

The `.agent/` directory is the durable task memory. The model may forget; this directory must not.

## Plugin Source Layout

Use this source layout unless there is a strong reason to change it:

```text
agent-guard-plugin/
  plugin.json

  hooks/
    session-start.sh
    before-write.sh
    after-command.sh
    before-final-response.sh
    job-monitor.sh
    failure-loop.sh

  bin/
    agent-guard

  lib/
    state.js
    plan.js
    path-policy.js
    jobs.js
    failures.js
    gates.js
    events.js
    runtime-adapter.js

  templates/
    failure-analysis.md
    review.schema.json
    plan.example.yaml

  tests/
```

If the implementation language changes, preserve the same conceptual module boundaries.

## Core Data Files

### `.agent/state.json`

Minimum shape:

```json
{
  "task_id": "password-reset",
  "stage": "RED_TEST",
  "current_step": "red-001",
  "completed_steps": [],
  "remaining_steps": ["red-001", "green-001", "review-001", "verify-001"],
  "allowed_paths": ["tests/**"],
  "forbidden_paths": ["src/**", "infra/**", ".github/**"],
  "can_finalize": false,
  "last_verification": null,
  "needs_human": false
}
```

Supported stages:

```text
IDLE
CLARIFYING
DESIGNING
PLANNING
RED_TEST
GREEN_IMPL
REVIEW
VERIFY
READY_TO_SUMMARIZE
NEEDS_FAILURE_ANALYSIS
NEEDS_HUMAN
DONE
```

### `.agent/plan.yaml`

Minimum shape:

```yaml
task_id: password-reset

steps:
  - id: red-001
    stage: RED_TEST
    goal: Add failing test for expired reset token
    allowed_paths:
      - tests/**
    forbidden_paths:
      - src/**
    commands:
      - pytest tests/auth/test_password_reset.py
    success_condition: "test fails for missing expiry validation"

  - id: green-001
    stage: GREEN_IMPL
    goal: Implement minimal expiry validation
    allowed_paths:
      - src/auth/**
      - tests/auth/**
    forbidden_paths:
      - infra/**
      - .github/**
    commands:
      - pytest tests/auth/test_password_reset.py
    success_condition: "password reset tests pass"

  - id: verify-001
    stage: VERIFY
    goal: Run final verification
    commands:
      - pytest
      - ruff check .
```

### `.agent/jobs.json`

Minimum shape:

```json
{
  "jobs": [
    {
      "id": "job-001",
      "command": "pytest",
      "status": "running",
      "started_at": "2026-05-11T10:00:00Z",
      "last_polled_at": null,
      "next_poll_after": "2026-05-11T10:01:00Z",
      "poll_count": 0,
      "max_polls": 20
    }
  ]
}
```

### `.agent/failures.json`

Minimum shape:

```json
{
  "last_failure": {
    "command": "pytest tests/auth/test_password_reset.py",
    "exit_code": 1,
    "failure_hash": "abc123",
    "repeat_count": 2,
    "code_changed_since_last_failure": false,
    "log_path": ".agent/artifacts/red-test.log"
  }
}
```

### `.agent/events.jsonl`

Append one JSON object per event.

Example:

```json
{"ts":"2026-05-11T10:00:00Z","hook":"SessionStart","action":"inject_state","stage":"RED_TEST"}
{"ts":"2026-05-11T10:01:00Z","hook":"BeforeWrite","decision":"block","reason":"src forbidden during RED_TEST"}
{"ts":"2026-05-11T10:02:00Z","hook":"AfterCommand","command":"pytest","exit_code":1}
```

## Required CLI

Implement a CLI named `agent-guard`.

Minimum commands:

```bash
agent-guard init
agent-guard start-task <task-id>
agent-guard status
agent-guard session-start
agent-guard can-write <path>
agent-guard record-command --cmd "<command>" --exit-code <code> --log <path>
agent-guard check-failure-loop
agent-guard check-job-poll <job-id>
agent-guard can-finalize
agent-guard next-step
```

Prefer stable JSON output from CLI commands so hooks can consume them.

Example output for a blocked write:

```json
{
  "decision": "block",
  "reason": "Current stage is RED_TEST. src/** is forbidden. Write tests/** first."
}
```

## Hook Responsibilities

### `SessionStartHook`

Implemented by `hooks/session-start.sh`.

Purpose:

- read `.agent/state.json`
- read `.agent/plan.yaml` if available
- read `.agent/jobs.json` if available
- output a concise state reminder for the agent

The reminder must include:

- current task
- current stage
- current step
- allowed paths
- forbidden paths
- next required action
- whether finalization is allowed

### `BeforeWriteHook`

Implemented by `hooks/before-write.sh`.

Purpose:

- block writes outside `allowed_paths`
- block writes inside `forbidden_paths`
- block production-code writes during `RED_TEST`
- block further source changes during `READY_TO_SUMMARIZE`
- require human escalation for sensitive files

Sensitive files include:

```text
.github/**
infra/**
migrations/**
package-lock.json
pnpm-lock.yaml
yarn.lock
poetry.lock
Cargo.lock
```

Lockfiles may be modified only if the current step explicitly allows them.

### `AfterCommandHook`

Implemented by `hooks/after-command.sh`.

Purpose:

- record command
- record exit code
- record log path
- compute or store a failure hash for failed commands
- update `.agent/failures.json`
- update `.agent/events.jsonl`
- if command failed, set stage to `NEEDS_FAILURE_ANALYSIS` unless the current stage is intentionally `RED_TEST`

During `RED_TEST`, a failing test can be valid. The implementation must distinguish expected RED failure from unexpected command failure using the current step metadata.

### `FailureLoopHook`

Implemented by `hooks/failure-loop.sh`.

Purpose:

- detect same command plus same failure hash plus no code changes
- block repeated retries after the configured threshold
- require `.agent/artifacts/failure-analysis.md`

Default threshold: 2 repeated identical failures.

Required failure analysis template:

```markdown
## Failure Summary

## Evidence

## Hypothesis

## Most Likely Root Cause

## Minimal Fix

## Next Verification Command
```

### `JobMonitorHook`

Implemented by `hooks/job-monitor.sh`.

Purpose:

- register long-running jobs
- prevent polling before `next_poll_after`
- prevent finalization while jobs are still running
- move jobs to terminal state when they complete
- escalate to `NEEDS_HUMAN` if max poll count is exceeded

Default polling rules:

```text
unit tests: 10-30 seconds
full test suite: 30-60 seconds
build: 60 seconds
deployment-like commands: require human approval
```

### `BeforeFinalResponseHook`

Implemented by `hooks/before-final-response.sh`.

Purpose:

Block completion unless all are true:

- `remaining_steps` is empty
- no running jobs exist
- latest final verification has `exit_code == 0`
- review artifact exists if the plan includes review
- `can_finalize == true`

If blocked, report the exact missing condition.

## Stage Rules

### `RED_TEST`

Allowed:

- write tests
- run targeted tests
- save failing test logs

Forbidden:

- write production source files
- claim implementation is complete
- run broad refactors

### `GREEN_IMPL`

Allowed:

- write minimal production code
- update tests if required
- run targeted verification

Forbidden:

- broad refactors
- unrelated formatting
- dependency upgrades unless explicitly planned

### `REVIEW`

Allowed:

- read diff
- read files
- write review artifact

Forbidden:

- source modifications unless the review has been converted into a new implementation step

### `VERIFY`

Allowed:

- run verification commands
- write verification logs

Forbidden:

- new implementation work unless verification fails and the state moves to `NEEDS_FAILURE_ANALYSIS`

### `READY_TO_SUMMARIZE`

Allowed:

- summarize work
- list changed files
- list verification commands and results
- ask user for next action

Forbidden:

- further code changes

## Failure Handling Rules

Never rerun the same failing command repeatedly without a change or analysis.

If the same failure appears twice and no code changed, switch to analysis mode.

In analysis mode, do not modify source files until `.agent/artifacts/failure-analysis.md` exists.

The analysis must identify evidence from logs, not only speculate.

## Finalization Rules

Do not say the task is complete unless `agent-guard can-finalize` passes.

If finalization fails, state what is missing and continue with the next required action.

Valid completion evidence includes:

- completed steps
- verification command
- exit code
- log path
- review artifact if applicable

Invalid completion evidence:

- “looks good”
- “should pass”
- “I believe this is fixed”
- “tests were not run, but…”

## Development Workflow for This Repository

When implementing this plugin:

1. Start with a small design note if the task is non-trivial.
2. Implement one feature at a time.
3. Add tests for the state transition or gate being implemented.
4. Prefer pure functions in `lib/`.
5. Keep hooks thin.
6. Run the relevant test command before claiming completion.
7. Do not introduce broad framework changes unless asked.

## Testing Expectations

At minimum, add tests for:

- state loading and saving
- path allowlist and denylist matching
- stage-based write blocking
- command result recording
- repeated failure detection
- finalization gate
- job polling interval logic

Prefer small deterministic tests over integration-heavy tests.

## Coding Style

- Keep modules small.
- Use explicit names.
- Avoid hidden global state.
- Validate JSON/YAML input.
- Fail closed when state is missing or invalid.
- Emit actionable error messages.
- Prefer stable machine-readable JSON for CLI output.

## Safety Rules

Never run destructive commands unless the user explicitly asks and the current task state permits it.

Commands requiring explicit approval:

```text
rm -rf
git reset --hard
git clean -fd
git push --force
dropdb
terraform apply
terraform destroy
kubectl delete
docker system prune
```

Do not modify these paths unless explicitly planned:

```text
.github/**
infra/**
migrations/**
```

## Expected First Milestone

The first milestone is not the full plugin.

Build only:

- `.agent/state.json` support
- `agent-guard init`
- `agent-guard status`
- `agent-guard can-write <path>`
- `agent-guard record-command`
- `agent-guard check-failure-loop`
- `agent-guard can-finalize`
- thin hook scripts that call the CLI

A successful first milestone should demonstrate these cases:

1. During `RED_TEST`, writing `src/**` is blocked.
2. During `RED_TEST`, writing `tests/**` is allowed.
3. Repeating the same failed command twice without changes is blocked.
4. Finalization is blocked when verification is missing.
5. Finalization is allowed only when state says all steps are complete and verification passed.

## Agent Behavior Rules

When working in this repository:

- Do not skip state updates.
- Do not claim completion without running or recording verification.
- Do not modify files outside the current task scope.
- Do not add complex abstractions before the minimal hook/CLI path works.
- If a requirement is ambiguous, ask before implementing.
- If tests fail twice with the same failure, stop and analyze before retrying.
