---
name: workflow-core
description: Coding workflow stages, legal transitions, and command rules for the default agent-guard workflow.
---

# Coding Workflow

Use this skill only when the current task is bound to the default coding workflow, usually `workflow_id = default`.

If the current task is bound to `research` or `docs`, do not use this skill as the source of stage truth. Use the matching workflow-specific skill instead.

The workflow DSL is stage-centered and uses:

- `goal`
- `plan`
- `allow`
- `deny`
- `enter`
- `exit`
- `expect`
- `next`
- `final`

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

Use these workflow commands during normal coding workflow progression:

- `agent-guard start-task <task-id> [--workflow ID]`
  Starts a new task and moves `IDLE` into the selected workflow entry stage.
- `agent-guard status`
  Shows the current task, stage, step, and plan summary.
- `agent-guard session-start`
  Shows the current workflow reminder before continuing work.
- `agent-guard next-step`
  Shows the next step derived from state and plan.
- `agent-guard advance-stage --to <stage> [--step <step-id>]`
  Moves to another stage without marking a plan step complete.
- `agent-guard complete-step <step-id> [--next-step <step-id>]`
  Marks the current workflow step complete without advancing to the next stage. This is only legal when the current stage uses `plan: advance`.
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
- `DESIGNING -> PLANNING` requires `.agent/artifacts/DESIGN.md`.
- `GREEN_IMPL` must pass through `REVIEW` before entering `VERIFY`.
- `REVIEW -> VERIFY` requires `.agent/artifacts/review.md`.
- `VERIFY -> READY_TO_SUMMARIZE` requires `.agent/artifacts/final-verification.log`.
- `VERIFY -> READY_TO_SUMMARIZE` requires the explicit `ready-to-summarize` command.
- `VERIFY` may return to `RED_TEST`, `GREEN_IMPL`, or `NEEDS_FAILURE_ANALYSIS`.
- `NEEDS_FAILURE_ANALYSIS` cannot exit until `.agent/artifacts/failure-analysis.md` exists.
- `READY_TO_SUMMARIZE -> DONE` requires `.agent/artifacts/summary.md`.
- `READY_TO_SUMMARIZE -> DONE` is only legal through `mark-done`.

## Workflow Discipline

- Respect the current stage permissions and required evidence.
- Treat `plan: create` as the only mode that may update `.agent/plan.yaml`.
- Do not skip intermediate stages in the state machine.
- Do not leave a stage without producing its required artifacts.
