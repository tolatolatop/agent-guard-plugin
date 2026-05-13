---
name: failure-analysis
description: Investigate repeated or opaque failures by gathering concrete evidence, isolating the failing layer, and producing a minimal next-step fix plan.
---

# Failure Analysis

Use this workflow when commands are failing repeatedly or the agent cannot explain why a step is blocked.

## Steps

1. Capture the exact failing command, exit code, and stderr/stdout evidence.
2. Identify whether the failure is caused by environment, permissions, missing inputs, flaky runtime state, or code defects.
3. Stop retrying the same command until there is a concrete change in code, environment, or invocation.
4. Write a short failure analysis with:
   - what failed
   - what evidence supports the diagnosis
   - what single next action should be attempted

## Exit Criteria

- The next attempt is materially different from the failing attempt.
- The diagnosis is evidence-backed rather than speculative.
