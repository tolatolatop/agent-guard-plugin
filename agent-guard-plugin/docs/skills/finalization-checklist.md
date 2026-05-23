---
name: finalization-checklist
description: Completion checklist for verification evidence and finalization gates.
---

# Finalization Checklist

Use this skill before reporting completion.

Completion requires:

- no running jobs remain
- `can-finalize` passes
- if `plan.yaml` exists, every step status is `done` or `failed`
- for workflows with a verification gate, `last_verification.exit_code` must be `0`

Preferred verification shortcut:

```bash
agent-guard verify --auto-ready -- pytest -q
```

This runs the command, writes `.agent/artifacts/final-verification.log`, updates `last_verification`, and moves to the completion-ready stage when the command succeeds. Use manual `record-command` only for hook internals or exceptional recovery.

Completion evidence should include:

- completed steps
- relevant validation evidence, if any
- unresolved risks or skipped checks

Invalid completion evidence:

- "looks good"
- "should pass"
- "I believe this is fixed"
- "tests were not run, but..."
