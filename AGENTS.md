# AGENTS.md

## Project Overview

This repository contains `agent-guard-plugin`, a lightweight runtime guard for long-running coding tasks.

The product goal is operational discipline, not model intelligence. The guard makes agent work:

- observable
- resumable
- interruptible
- harder to derail

It does that through:

- durable state in `.agent/`
- thin runtime hooks and bridges
- stage-based workflow gates
- write controls
- repeated-failure detection
- finalization checks

## Current Implementation Shape

The implementation is Python-first and managed with `uv`.

Main package layout:

```text
agent-guard-plugin/
  pyproject.toml
  plugin.json
  src/agent_guard/
  docs/
  tests/
  workflows/
```

Important source modules:

- `src/agent_guard/cli.py`
- `src/agent_guard/workflow_spec.py`
- `src/agent_guard/workflow.py`
- `src/agent_guard/state.py`
- `src/agent_guard/transitions.py`
- `src/agent_guard/install.py`
- `src/agent_guard/runtime_bridge.py`

Do not reintroduce the old JavaScript-oriented layout from earlier planning notes unless explicitly asked.

## Core Principles

1. State is externalized.
   Workflow state must live under `.agent/`.

2. Hooks stay thin.
   Runtime integration should delegate to the Python CLI and bridge.

3. Gates are evidence-based.
   Stage exit and task completion depend on state and artifacts, not self-report.

4. Failures require analysis.
   Repeating the same failure without meaningful change must stop progress.

5. Workflow policy is declarative.
   `workflows/*.workflow.yaml` defines the workflow DSL; code evaluates built-in rules.

6. Keep the system small.
   Prefer explicit, testable behavior over broad abstraction.

## Runtime State Layout

The plugin manages durable task memory in:

```text
.agent/
  state.json
  plan.yaml
  jobs.json
  failures.json
  events.jsonl
  stage-artifacts.json
  artifacts/
    DESIGN.md
    PLAN.md
    red-test.log
    failure-analysis.md
    review.md
    summary.md
```

Notes:

- `.agent/state.json` is protected and must not be edited directly.
- `stage-artifacts.json` records stage entry time plus required artifact mtimes.
- Required artifacts must exist and be updated during the active stage before exit is allowed.

## Workflow Model

The canonical bundled workflow source lives under [`agent-guard-plugin/workflows/`](./agent-guard-plugin/workflows/).

It uses the stage-centered author DSL:

- top level:
  - `version`
  - `workflow`
  - `global_gates`
  - `globals`
  - `stages`
- per stage:
  - `goal`
  - `plan`
  - `final`
  - `allow`
  - `deny`
  - `enter`
  - `exit`
  - `expect`
  - `next`

Important workflow rules:

- write control is static and workflow-driven
- no dynamic path scope is used at runtime
- `artifacts_required` are hard gates
- `artifacts_expected` are soft guidance only
- `artifacts_required` also appear in display/projection automatically

### Global Workflow Policies

Current global policy areas are:

- `globals.protected`
- `globals.sensitive`
- `globals.failures`
- `globals.finalize`
- `globals.wizard`
- `globals.install`

`globals.install.skills.match` and `exclude_match` may provide default install-time skill filters. If workflow defaults match nothing, install should warn and fall back to full skill installation instead of blocking.

## Supported Stages

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

Core transition expectations:

- `PLANNING -> RED_TEST` or `PLANNING -> GREEN_IMPL` requires `.agent/plan.yaml`
- `GREEN_IMPL -> VERIFY` is not direct; it must pass through `REVIEW`
- `REVIEW -> VERIFY` requires `.agent/artifacts/review.md`
- `NEEDS_FAILURE_ANALYSIS` requires `.agent/artifacts/failure-analysis.md`
- `READY_TO_SUMMARIZE -> DONE` is only legal through `mark-done`

## Workflow Commands

These are the main workflow progression commands:

- `agent-guard start-task <task-id>`
- `agent-guard status`
- `agent-guard session-start`
- `agent-guard next-step`
- `agent-guard advance-stage --to <stage> [--step <step-id>]`
- `agent-guard complete-step <step-id> --next-stage <stage> [--next-step <step-id>]`
- `agent-guard ready-to-summarize`
- `agent-guard mark-done`

Use `complete-step` when a real step finished. Use `advance-stage` for stage-only moves.

Do not document or prioritize non-workflow commands when the task is specifically about workflow guidance unless needed.

## Write Control

Write control is intentionally minimal now.

Global write policy:

- `globals.protected`
- `globals.sensitive`

Per-stage write policy:

- `allow.write`
- `deny.write`

Current behavior is workflow-driven and static:

- no runtime `allowed_paths`
- no runtime `forbidden_paths`
- no `scoped`
- no `managed-only`

Do not reintroduce dynamic write-scope behavior unless explicitly requested.

## Evidence and Exit Gates

Stage exit is controlled by `exit`.

Supported required-artifact forms:

1. Simple path

```yaml
exit:
  - .agent/artifacts/review.md
```

2. Path plus content gate

```yaml
exit:
  - path: .agent/artifacts/failure-analysis.md
    matches: '^## Failure Summary'
    display: failure-analysis.md must start with the Failure Summary section.
```

Exit behavior:

- if a required artifact is missing: block
- if it existed before stage entry but was not updated in the stage: block
- if `matches` is configured and content does not match: block with configured `message`

## Finalization

Task completion is separate from ordinary stage flow.

Current finalization checks come from `globals.finalize.require` and built-in rules in code.

Finalization should be treated as completion evidence, not as a place to enforce extra review content rules.

## Skills and Installation

The installer can update runtime integrations for:

- `claude-code`
- `codex`
- `opencode`

Selective skill installation is supported through:

- `--match REGEX`
- `--exclude-match REGEX`

CLI filters override workflow defaults.

If the task is about workflow behavior, prioritize the workflow DSL and skill docs over install details.

## Testing Expectations

Before claiming completion on code changes, run relevant tests. Prefer targeted pytest runs first, then full suite when appropriate.

Common commands:

```bash
uv run pytest -q
uv run pytest -q tests/test_workflow_spec.py
uv run pytest -q tests/test_install.py
```

## Working Rules For Agents

- Do not edit `.agent/state.json` directly.
- Do not bypass workflow commands for stage progression.
- Do not claim completion without satisfying workflow evidence and finalization gates.
- Do not reintroduce outdated concepts such as dynamic path scopes or review.json.
- Keep docs aligned with the current stage-centered workflow DSL and Python implementation.
