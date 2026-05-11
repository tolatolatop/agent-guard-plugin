# Core Workflow

Canonical stage flow:

`IDLE -> CLARIFYING -> DESIGNING -> PLANNING -> RED_TEST -> GREEN_IMPL -> REVIEW -> VERIFY -> READY_TO_SUMMARIZE -> DONE`

Exceptional flow:

- Any stage can move to `NEEDS_FAILURE_ANALYSIS` when verification or command execution fails unexpectedly.
- Sensitive or blocked work can move to `NEEDS_HUMAN`.

Stage intent:

- `RED_TEST`: prove the missing behavior with a failing test.
- `GREEN_IMPL`: make the smallest code change to pass targeted verification.
- `REVIEW`: capture review evidence without silent code changes.
- `VERIFY`: run verification and collect final evidence.
- `READY_TO_SUMMARIZE`: summarize only; no new edits.

Global workflow gates:

- Respect `allowed_paths` and `forbidden_paths`.
- Do not retry identical failures without analysis.
- Do not finalize without passing `can-finalize`.
