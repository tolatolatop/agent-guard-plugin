---
name: docs-workflow
description: Stage map, transitions, and completion rules for the documentation workflow.
---

# Documentation Workflow

Use this skill only when the current task is bound to `workflow_id = docs`.

This workflow is for document intake, outlining, drafting, review, validation, and publication-ready handoff. It is not the coding workflow and should not be navigated with coding stage names.

State machine:

```text
IDLE
  -> INTAKE

INTAKE
  -> OUTLINE
  -> DRAFT

OUTLINE
  -> DRAFT

DRAFT
  -> REVIEW
  -> NEEDS_FAILURE_ANALYSIS

REVIEW
  -> VALIDATE
  -> DRAFT
  -> NEEDS_FAILURE_ANALYSIS

VALIDATE
  -> READY_TO_PUBLISH
  -> DRAFT
  -> REVIEW
  -> NEEDS_FAILURE_ANALYSIS

READY_TO_PUBLISH
  -> DONE

NEEDS_FAILURE_ANALYSIS
  -> DRAFT
  -> REVIEW
  -> VALIDATE

DONE
  -> reset-task / next-task only
```

## Command Manual

- `agent-guard start-task <task-id> --workflow docs`
  Starts a documentation task and moves `IDLE` into `INTAKE`.
- `agent-guard advance-stage --to <stage> [--step <step-id>]`
  Moves between documentation stages without implicitly completing a plan step.
- `agent-guard complete-step <step-id> [--next-step <step-id>]`
  Legal only in stages using `plan: advance`.
- `agent-guard ready-to-summarize`
  Moves `VALIDATE` into `READY_TO_PUBLISH` when the workflow allows it.
- `agent-guard mark-done`
  Moves `READY_TO_PUBLISH` into `DONE`.

## Transition Rules

- `OUTLINE -> DRAFT` requires `.agent/plan.yaml`.
- `DRAFT -> REVIEW` requires `.agent/artifacts/draft.md`.
- `REVIEW -> VALIDATE` requires `.agent/artifacts/review.md`.
- `VALIDATE -> READY_TO_PUBLISH` requires `.agent/artifacts/final-verification.log`.
- `READY_TO_PUBLISH -> DONE` requires `.agent/artifacts/summary.md`.
- `NEEDS_FAILURE_ANALYSIS` cannot exit until `.agent/artifacts/failure-analysis.md` exists.

## Workflow Discipline

- Documentation stages may write document files and documentation artifacts, but should not drift into product implementation by default.
- Treat `plan: create` as the only mode that may update `.agent/plan.yaml`.
- Use `REVIEW` and `VALIDATE` as distinct gates: review fixes wording and structure, validation confirms publishing readiness.
- Do not claim a document is final until the required artifacts and finalization checks pass.
