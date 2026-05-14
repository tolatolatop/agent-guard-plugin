# DDD Design: File Write Policy In The Stage DSL

## Goal

Refine file write control so it fits the latest DDD workflow DSL:

- static
- minimal
- stage-oriented
- runtime-neutral
- easy to explain

The write model should come entirely from workflow configuration.
No dynamic path scope.
No write-mode vocabulary.
No duplicate allow and deny systems in state.

## Design Position

File write control belongs to two places only:

- `globals.paths`
- `stages.<stage>.permissions.write`

It does not belong in:

- `TaskSession`
- `PlanStep`
- runtime hook scripts
- wizard-generated path defaults

## Ubiquitous Language

Use these terms:

- `Protected Path`: never writable by the agent
- `Sensitive Path`: blocked by default and only writable when a stage explicitly allows it
- `Write Permission`: the allow and deny rules for one stage
- `Writable Roots`: patterns listed in `permissions.write.allow`
- `Denied Roots`: patterns listed in `permissions.write.deny`
- `Write Decision`: allow or block with a concrete reason

Avoid these terms:

- dynamic scope
- scoped
- managed-only
- session allowlist
- session denylist

Those names describe old implementation models, not the target domain model.

## Target DSL Shape

The write policy surface should be:

```yaml
globals:
  paths:
    protected:
      - .agent/state.json
    sensitive:
      - .github/**
      - infra/**
      - migrations/**
      - package-lock.json
      - pnpm-lock.yaml
      - yarn.lock
      - poetry.lock
      - Cargo.lock

stages:
  RED_TEST:
    permissions:
      write:
        allow:
          - tests/**
        deny:
          - src/**
```

This is the full user-facing write model.

## Why This Model

### One global concern

`globals.paths` captures cross-stage protections:

- files the agent should never edit directly
- paths that need deliberate elevation

### One stage-local concern

`permissions.write` captures what the current stage may edit.

This keeps write control where users expect it:

- global path safety at the top
- stage write rules inside the stage

## Rule Evaluation

Write decisions should be evaluated in this order:

1. If the target path matches `globals.paths.protected`, block.
2. If the target path matches `permissions.write.deny`, block.
3. If the target path matches `globals.paths.sensitive` and is not in `permissions.write.allow`, block.
4. If `permissions.write.allow` is empty or missing, block project writes.
5. If the target path matches `permissions.write.allow`, allow.
6. Otherwise, block.

This is intentionally fail-closed.

## Examples

### Planning

```yaml
PLANNING:
  permissions:
    write:
      allow:
        - .agent/**
        - ./PLAN.md
      deny: []
```

Meaning:

- planning may update workflow artifacts
- planning may not edit product code

### Red Test

```yaml
RED_TEST:
  permissions:
    write:
      allow:
        - tests/**
      deny:
        - src/**
```

Meaning:

- tests are writable
- production code is explicitly blocked

### Green Implementation

```yaml
GREEN_IMPL:
  permissions:
    write:
      allow:
        - src/**
        - tests/**
      deny: []
```

Meaning:

- code and tests are writable
- sensitive paths remain blocked unless explicitly allowed

### Review

```yaml
REVIEW:
  permissions:
    write:
      allow:
        - .agent/**
      deny: []
```

Meaning:

- review may write review artifacts
- review may not edit source files

## Domain Model Impact

### `TaskSession`

`TaskSession` should not store mutable path scope such as:

```json
{
  "allowed_paths": [],
  "forbidden_paths": []
}
```

Those are not task-state facts.
They are workflow policy.

### `PlanStep`

`PlanStep` should not duplicate per-step path permissions.

The write boundary is stage policy, not plan-step-local policy.

### `WritePolicyService`

This domain service should:

- load `globals.paths`
- load the current stage's `permissions.write`
- evaluate a repo-relative path
- return a `GuardDecision`

The runtime adapter should only forward the path and present the result.

## Compatibility Mapping

The current repository still uses:

- `path_policy`
- `write_policy.writable_paths`
- `write_policy.denied_paths`

The target mapping is:

- `path_policy.protected_paths` -> `globals.paths.protected`
- `path_policy.sensitive_paths` -> `globals.paths.sensitive`
- `write_policy.writable_paths` -> `permissions.write.allow`
- `write_policy.denied_paths` -> `permissions.write.deny`

This is a structural rename, not a semantic change.

## Runtime Compatibility

This design works cleanly across Claude Code, Codex, and OpenCode because it depends only on:

- current stage
- workflow config
- target path

It does not depend on:

- runtime-specific job handles
- mutable session scope
- adapter-specific path mutation behavior

That makes write control one of the most portable guard mechanisms in the system.

## Migration Guidance

Migration should remain simple:

1. Treat write permissions conceptually as `permissions.write`.
2. Keep a parser shim from the current flat fields if necessary.
3. Remove any remaining runtime references to state-level path scopes.
4. Update docs and prompts to talk about stage permissions, not write modes.

## Test Expectations

Tests should prove:

- protected paths are always blocked
- denied stage paths are blocked
- sensitive paths require explicit allow
- missing write permissions fail closed
- allowed stage paths succeed
- current stage alone determines the write scope

## Summary

The file write model should be:

- one global path policy
- one stage-local write policy
- no dynamic scope
- no mode vocabulary

In the latest DDD DSL, that means:

- `globals.paths`
- `stages.<stage>.permissions.write`
