---
name: research-workflow
description: Stage map, transitions, and completion rules for the research workflow.
---

# Research Workflow

Use this skill only when the current task is bound to `workflow_id = research`.

This workflow is for scoped repository research, evidence gathering, synthesis, and delivery. It is not the coding workflow and does not use `RED_TEST`, `GREEN_IMPL`, or `READY_TO_SUMMARIZE`.

State machine:

```text
IDLE
  -> QUESTIONING

QUESTIONING
  -> DISCOVER
  -> OUTLINE

OUTLINE
  -> DISCOVER

DISCOVER
  -> ANALYZE
  -> NEEDS_FAILURE_ANALYSIS

ANALYZE
  -> VALIDATE
  -> DISCOVER
  -> NEEDS_FAILURE_ANALYSIS

VALIDATE
  -> READY_TO_DELIVER
  -> DISCOVER
  -> ANALYZE
  -> NEEDS_FAILURE_ANALYSIS

READY_TO_DELIVER
  -> DONE

NEEDS_FAILURE_ANALYSIS
  -> DISCOVER
  -> ANALYZE
  -> VALIDATE
  -> DONE only after explicit workflow progression

DONE
  -> reset-task / next-task only
```

## Command Manual

- `agent-guard start-task <task-id> --workflow research`
  Starts a research task and moves `IDLE` into `QUESTIONING`.
- `agent-guard advance-stage --to <stage> [--step <step-id>]`
  Moves between research stages without implicitly completing a plan step.
- `agent-guard complete-step <step-id> [--next-step <step-id>]`
  Legal only in stages using `plan: advance`.
- `agent-guard ready-to-summarize`
  Moves `VALIDATE` into `READY_TO_DELIVER` when the workflow allows it.
- `agent-guard mark-done`
  Moves `READY_TO_DELIVER` into `DONE`.

## Transition Rules

- `OUTLINE -> DISCOVER` requires `.agent/plan.yaml`.
- `DISCOVER -> ANALYZE` requires `.agent/artifacts/research-brief.md`.
- `ANALYZE -> VALIDATE` requires `.agent/artifacts/analysis.md`.
- `VALIDATE -> READY_TO_DELIVER` requires `.agent/artifacts/final-verification.log`.
- `READY_TO_DELIVER -> DONE` requires `.agent/artifacts/summary.md`.
- `NEEDS_FAILURE_ANALYSIS` cannot exit until `.agent/artifacts/failure-analysis.md` exists.

## Workflow Discipline

- Research stages may write notes, reports, and research artifacts, but they do not authorize product implementation work by default.
- Treat `plan: create` as the only mode that may update `.agent/plan.yaml`.
- Use `VALIDATE` to challenge unsupported conclusions before claiming delivery.
- Do not route to coding-only stages or commands just because a repository contains code.
