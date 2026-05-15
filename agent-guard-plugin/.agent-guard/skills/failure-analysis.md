---
name: failure-analysis
description: Evidence-first recovery guide for repeated failures, blocked verification, and analysis mode.
---

# Failure Analysis

Use when the same failure repeats, when the stage is `NEEDS_FAILURE_ANALYSIS`, or when verification fails without an obvious fix.

Required process:

1. Read the failing log artifact.
2. Summarize concrete evidence, not guesses.
3. Identify the most likely root cause.
4. Propose the smallest fix.
5. Name the next verification command.

Do not continue with source changes until `failure-analysis.md` exists when the guard requires it.

The minimum artifact sections are:

- `Failure Summary`
- `Evidence`
- `Hypothesis`
- `Most Likely Root Cause`
- `Minimal Fix`
- `Next Verification Command`
