---
name: finalization-checklist
description: Completion checklist for verification evidence, review artifacts, and finalization gates.
---

# Finalization Checklist

Use this skill before reporting completion.

Completion requires:

- `remaining_steps` is empty
- no running jobs remain
- latest final verification has `exit_code == 0`
- required review artifact exists when the plan includes review
- `can-finalize` passes

Completion evidence should include:

- completed steps
- verification command
- exit code
- log path
- review artifact when applicable

Invalid completion evidence:

- "looks good"
- "should pass"
- "I believe this is fixed"
- "tests were not run, but..."
