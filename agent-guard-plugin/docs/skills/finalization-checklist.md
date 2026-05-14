---
name: finalization-checklist
description: Completion checklist for verification evidence, review artifacts, and finalization gates.
---

# Finalization Checklist

Use this skill before reporting completion.

Completion requires:

- no running jobs remain
- `can-finalize` passes
- if `plan.yaml` exists, every step status is `done` or `failed`

Completion evidence should include:

- completed steps
- relevant validation evidence, if any
- unresolved risks or skipped checks

Invalid completion evidence:

- "looks good"
- "should pass"
- "I believe this is fixed"
- "tests were not run, but..."
