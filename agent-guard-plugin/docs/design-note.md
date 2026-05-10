# Design Note

The first milestone implements a file-backed runtime guard with a small Node.js CLI and thin shell hooks.

Key decisions:

- Persist durable task memory under `.agent/` and fail closed when state is missing or invalid.
- Keep hook scripts as wrappers that call the CLI and return machine-readable JSON.
- Implement policy in pure `lib/` modules so stage gates, failure-loop checks, and finalization checks are deterministic and unit-testable.
- Use zero runtime dependencies for the milestone to keep bootstrap small and avoid lockfile churn.

Scope of this milestone:

- state initialization and status reporting
- path gating for writes
- command recording and failure-loop detection
- finalization gate checks
- thin hooks for the main entry points
