---
name: workflow-core
description: Canonical workflow stages, legal transitions, and command rules for agent-guard.
---

# Core Workflow

The latest DDD DSL groups stage rules into:

- `intent`
- `permissions`
- `transitions`
- `evidence`

The current runtime still reads a flatter `.workflow.yaml`, but agents should reason about stage behavior using the grouped model above.

State machine:

```text
IDLE
  -> CLARIFYING

CLARIFYING
  -> DESIGNING
  -> PLANNING

DESIGNING
  -> PLANNING

PLANNING
  -> RED_TEST
  -> GREEN_IMPL

RED_TEST
  -> GREEN_IMPL
  -> NEEDS_FAILURE_ANALYSIS

GREEN_IMPL
  -> REVIEW
  -> NEEDS_FAILURE_ANALYSIS

REVIEW
  -> VERIFY
  -> GREEN_IMPL

VERIFY
  -> READY_TO_SUMMARIZE
  -> RED_TEST
  -> GREEN_IMPL
  -> NEEDS_FAILURE_ANALYSIS

READY_TO_SUMMARIZE
  -> DONE

NEEDS_FAILURE_ANALYSIS
  -> RED_TEST
  -> GREEN_IMPL
  -> VERIFY
  -> NEEDS_HUMAN

NEEDS_HUMAN
  -> CLARIFYING
  -> PLANNING

DONE
  -> reset-task / next-task only
```

## Command Manual

Use only these workflow commands during normal stage progression:

- `agent-guard start-task <task-id>`
  Starts a new task and moves `IDLE` into `CLARIFYING`.
- `agent-guard status`
  Shows the current task, stage, step, and plan summary.
- `agent-guard session-start`
  Shows the current workflow reminder before continuing work.
- `agent-guard next-step`
  Shows the next step derived from state and plan.
- `agent-guard advance-stage --to <stage> [--step <step-id>]`
  Moves to another stage without marking a plan step complete.
- `agent-guard complete-step <step-id> --next-stage <stage> [--next-step <step-id>]`
  Marks the current workflow step complete and advances to the next stage.
- `agent-guard ready-to-summarize`
  Moves `VERIFY` into `READY_TO_SUMMARIZE` when verification is complete.
- `agent-guard mark-done`
  Moves `READY_TO_SUMMARIZE` into `DONE`.

Use them like this:

- Use `start-task` once at task start.
- Use `status`, `session-start`, and `next-step` to rehydrate workflow context before acting.
- Prefer `complete-step` when a real planned step finished.
- Use `advance-stage` for stage-only moves such as `CLARIFYING -> PLANNING` or `REVIEW -> GREEN_IMPL`.
- Use `ready-to-summarize` only after `VERIFY` is satisfied.
- Use `mark-done` only from `READY_TO_SUMMARIZE`.

## Transition Rules

- `PLANNING -> RED_TEST` or `PLANNING -> GREEN_IMPL` requires `.agent/plan.yaml`.
- `GREEN_IMPL` must pass through `REVIEW` before entering `VERIFY`.
- `REVIEW -> VERIFY` requires `.agent/artifacts/review.md`.
- `VERIFY -> READY_TO_SUMMARIZE` requires the explicit `ready-to-summarize` command.
- `VERIFY` may return to `RED_TEST`, `GREEN_IMPL`, or `NEEDS_FAILURE_ANALYSIS`.
- `NEEDS_FAILURE_ANALYSIS` cannot exit until `.agent/artifacts/failure-analysis.md` exists.
- `READY_TO_SUMMARIZE -> DONE` is only legal through `mark-done`.

## Workflow Discipline

- Respect the current stage permissions and required evidence.
- Do not skip intermediate stages in the state machine.
- Do not leave a stage without producing its required artifacts.
