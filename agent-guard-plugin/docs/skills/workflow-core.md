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

Use these commands for mainline progression:

- `agent-guard complete-step <step-id> --next-stage <stage> [--next-step <step-id>]`
- `agent-guard advance-stage --to <stage> [--step <step-id>]`
- `agent-guard ready-to-summarize`
- `agent-guard mark-done`

Transition rules:

- Prefer `complete-step` whenever a real workflow step finished and the corresponding `plan.yaml` step should be marked `done`.
- Use `advance-stage` for stage-only moves such as `CLARIFYING -> PLANNING` or when re-entering execution with the same step context.
- `PLANNING -> RED_TEST` or `PLANNING -> GREEN_IMPL` uses static stage write permissions; it does not accept runtime scope overrides.
- `GREEN_IMPL` must pass through `REVIEW` before entering `VERIFY`; direct `GREEN_IMPL -> VERIFY` is not allowed.
- `REVIEW -> VERIFY` requires `.agent/artifacts/review.md`.
- `VERIFY -> READY_TO_SUMMARIZE` requires successful `last_verification`, no running jobs, and the explicit `ready-to-summarize` command.
- `VERIFY` may return directly to `RED_TEST` or `GREEN_IMPL` when more test or implementation work is needed.
- `READY_TO_SUMMARIZE -> DONE` is only legal through `mark-done`, which internally requires `agent-guard can-finalize` to pass.
- `NEEDS_FAILURE_ANALYSIS` cannot exit until `.agent/artifacts/failure-analysis.md` exists.

Global workflow gates:

- Respect the current stage permissions, especially write boundaries and required evidence.
- When adding an artifact, state the allowed modification scope or directory up front.
- Do not retry identical failures without analysis.
- Do not finalize without passing `can-finalize`.
