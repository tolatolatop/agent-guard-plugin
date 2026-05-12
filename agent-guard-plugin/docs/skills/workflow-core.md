# Core Workflow

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
  -> VERIFY
  -> NEEDS_FAILURE_ANALYSIS

REVIEW
  -> VERIFY
  -> GREEN_IMPL

VERIFY
  -> READY_TO_SUMMARIZE
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
- `agent-guard advance-stage --to <stage> [--step <step-id>] [--allowed-paths <csv>] [--forbidden-paths <csv>]`
- `agent-guard ready-to-summarize`
- `agent-guard mark-done`

Transition rules:

- Prefer `complete-step` whenever a real workflow step finished and state must move that step from `remaining_steps` to `completed_steps`.
- Use `advance-stage` for stage-only moves such as `CLARIFYING -> PLANNING` or when re-entering execution after explicit scope selection.
- `PLANNING -> RED_TEST` or `PLANNING -> GREEN_IMPL` requires a selected step plus non-empty scope from `plan.yaml` or explicit CLI flags.
- `REVIEW -> VERIFY` requires `.agent/artifacts/review.json` when the plan includes a review step.
- `VERIFY -> READY_TO_SUMMARIZE` requires successful `last_verification`, no running jobs, empty `remaining_steps`, and the explicit `ready-to-summarize` command.
- `READY_TO_SUMMARIZE -> DONE` is only legal through `mark-done`, which internally requires `agent-guard can-finalize` to pass.
- `NEEDS_FAILURE_ANALYSIS` cannot exit until `.agent/artifacts/failure-analysis.md` exists.

Automatic transitions already present:

- `start-task`: `IDLE -> CLARIFYING`
- `wizard`: initializes directly into the selected starting stage
- `record-command`: failed non-red command -> `NEEDS_FAILURE_ANALYSIS`
- `record-command` in `VERIFY`: updates `last_verification`
- `reset-task`: archives the completed task and starts a new one in `CLARIFYING`

Global workflow gates:

- Respect `allowed_paths` and `forbidden_paths`.
- Do not retry identical failures without analysis.
- Do not finalize without passing `can-finalize`.
