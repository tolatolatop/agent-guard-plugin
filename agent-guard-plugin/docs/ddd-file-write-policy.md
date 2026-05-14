# DDD Design: Minimal File Write Policy

## Goal

Refine file write control so it is:

- static: only driven by workflow configuration
- minimal: as few configuration concepts as possible
- predictable: no hidden dynamic scope mutation is required to understand behavior
- teachable: users can configure it without learning multiple overlapping path systems

This design intentionally does not cover command policy, failure policy, or finalization policy in depth.
It focuses only on repository file write control.

## Problem

The current model mixes too many concepts:

- stage-level `allowed_paths`
- stage-level `forbidden_paths`
- top-level `path_policy`
- session-level `allowed_paths`
- session-level `forbidden_paths`
- `writable` mode
- wizard-generated path defaults

This creates three problems:

1. The same decision can be influenced by multiple places.
2. Some concepts are only documentation markers, not real behavior.
3. Users must understand runtime mutation, not just workflow configuration.

`scoped` is the clearest example.
It appears meaningful in workflow, but the implementation does not treat it as a first-class behavior mode.
That is exactly the kind of concept this design removes.

## Design Goal

Reduce write control to:

1. global path rules
2. per-stage write policy

No dynamic path scope in `state.json`.
No parallel allow/deny systems at both workflow and runtime state level.
No synthetic write mode names that do not independently drive behavior.

## Domain View

### Bounded Context

This belongs to `Workflow Definition` and `Task Execution`.

- `Workflow Definition` owns the static write policy model.
- `Task Execution` asks whether a write is legal for the current stage.

Runtime adapters and hooks do not make policy decisions.
They only forward a path and receive an allow/block decision.

### Aggregate

`TaskSession` should no longer own mutable write scope such as:

- `allowed_paths`
- `forbidden_paths`

Those are workflow policy concerns, not session state.

`TaskSession` should only carry:

- `task_id`
- `stage`
- `current_step`
- `completed_steps`
- `remaining_steps`
- `can_finalize`
- `last_verification`
- `needs_human`

### Domain Service

Introduce one explicit service for this concern:

- `WritePolicyService`

Its job is:

- load global write rules from workflow spec
- load stage write rules from workflow spec
- evaluate a target path against those rules
- return a stable `GuardDecision`

## Ubiquitous Language

Use these terms consistently:

- `Protected Path`: never directly writable by the agent
- `Sensitive Path`: blocked by default and only writable in explicitly elevated stages
- `Stage Write Policy`: the static write rule attached to one stage
- `Writable Roots`: the repo path patterns a stage may edit
- `Denied Roots`: repo path patterns a stage may not edit
- `Write Decision`: allow or block, with one concrete reason

Avoid these terms in the new model:

- `scoped`
- `managed-only`
- dynamic scope
- session allowlist
- session denylist

Those names either overlap with the real policy model or force users to learn implementation details.

## Target Workflow Shape

Keep one top-level section for cross-stage path rules:

```yaml
path_policy:
  protected_paths:
    - .agent/state.json
  sensitive_paths:
    - .github/**
    - infra/**
    - migrations/**
    - package-lock.json
    - pnpm-lock.yaml
    - yarn.lock
    - poetry.lock
    - Cargo.lock
```

Then keep only one stage-level section for write control:

```yaml
stages:
  RED_TEST:
    write_policy:
      writable_paths:
        - tests/**
      denied_paths:
        - src/**
```

This is the entire core model.

### What Gets Removed

Remove from workflow:

- `writable`
- stage-level root `allowed_paths`
- stage-level root `forbidden_paths`
- `lockfile_allowlist`
- `wizard_defaults.default_paths`

Remove from state:

- `allowed_paths`
- `forbidden_paths`

### Why `lockfile_allowlist` Is Removed

It creates a second axis inside `sensitive_paths`.
That makes the model harder to explain.

If a lockfile is writable in a certain stage, the stage should say so explicitly in `write_policy.writable_paths`.
If the system still wants extra protection for lockfiles, that belongs in code as a special-case validation rule for sensitive paths, not as another user-facing configuration primitive.

## Minimal Rule Model

The write decision should be evaluated in this order:

1. If path matches `protected_paths`, block.
2. If path matches stage `denied_paths`, block.
3. If path matches `sensitive_paths` and is not explicitly listed in stage `writable_paths`, block.
4. If stage has no `writable_paths`, block all project writes.
5. If path matches stage `writable_paths`, allow.
6. Otherwise, block.

This is intentionally fail-closed.

## Stage Semantics

The system should not need a `writable` mode field if the stage policy is explicit.

Examples:

### Planning-like stages

```yaml
PLANNING:
  write_policy:
    writable_paths:
      - .agent/**
      - PLAN.md
```

Interpretation:

- planning may update workflow artifacts
- planning may not edit project source because no source path is writable

### Red test stage

```yaml
RED_TEST:
  write_policy:
    writable_paths:
      - tests/**
    denied_paths:
      - src/**
```

Interpretation:

- tests may be edited
- source may not be edited

### Green implementation stage

```yaml
GREEN_IMPL:
  write_policy:
    writable_paths:
      - src/**
      - tests/**
```

Interpretation:

- implementation may edit code and tests
- sensitive paths stay blocked unless explicitly added

### Review stage

```yaml
REVIEW:
  write_policy:
    writable_paths:
      - .agent/**
```

Interpretation:

- review can write review artifacts
- review cannot edit source

## Aggregate and Repository Impact

### `TaskSession`

Remove these fields from state:

```json
{
  "allowed_paths": [],
  "forbidden_paths": []
}
```

They do not belong to the aggregate in the simplified model.

### Workflow Repository

The workflow repository should normalize:

```yaml
stages:
  <STAGE>:
    write_policy:
      writable_paths: []
      denied_paths: []
```

If `write_policy` is missing, it should normalize to empty lists and fail closed.

## Application Use Cases

Only one use case is required for this feature:

- `CheckWritePermission`

Input:

- current stage
- target path

Output:

- `GuardDecision`

The use case should not accept dynamic allowlists or deny lists from CLI flags or in-memory state.

## Infrastructure and Runtime

Hooks and runtime bridges stay thin.

They call:

```text
agent-guard can-write <path>
```

The CLI resolves:

- current task session
- workflow spec
- stage write policy

and returns:

```json
{
  "decision": "block",
  "reason": "Path src/auth/reset.py is denied during RED_TEST."
}
```

## Backward Compatibility Strategy

This should be migrated in two steps.

### Step 1: Dual-read

Read old fields:

- stage `allowed_paths`
- stage `forbidden_paths`
- state `allowed_paths`
- state `forbidden_paths`

but normalize them internally into the new `write_policy` model.

State-level path scope should be treated as deprecated and ignored when a stage `write_policy` exists.

### Step 2: Remove old fields

Remove:

- workflow `writable`
- workflow stage `allowed_paths`
- workflow stage `forbidden_paths`
- state `allowed_paths`
- state `forbidden_paths`

At that point, write control becomes fully static and workflow-owned.

## Validation Rules

Workflow validation should enforce:

- `path_policy.protected_paths` is a list
- `path_policy.sensitive_paths` is a list
- each stage `write_policy` is a mapping
- `write_policy.writable_paths` is a list
- `write_policy.denied_paths` is a list

Fail closed when invalid.

## Example Final Shape

```yaml
path_policy:
  protected_paths:
    - .agent/state.json
  sensitive_paths:
    - .github/**
    - infra/**
    - migrations/**
    - package-lock.json
    - pnpm-lock.yaml
    - yarn.lock
    - poetry.lock
    - Cargo.lock

stages:
  PLANNING:
    write_policy:
      writable_paths:
        - .agent/**
        - PLAN.md

  RED_TEST:
    write_policy:
      writable_paths:
        - tests/**
      denied_paths:
        - src/**

  GREEN_IMPL:
    write_policy:
      writable_paths:
        - src/**
        - tests/**

  REVIEW:
    write_policy:
      writable_paths:
        - .agent/**
```

This is enough to express the core write behavior with far less user confusion.

## Out of Scope

Not part of this design:

- dynamic task-step path scopes
- runtime-generated path policy
- per-command temporary write elevation
- human-approval workflow for sensitive files
- command/failure/finalization redesign beyond what write control depends on

Those can be revisited later, but they should not be part of the minimal first model.

## Recommended Next Implementation Slice

1. Add `stage.write_policy` as the canonical workflow field.
2. Make `can-write` read only `path_policy` + `stage.write_policy`.
3. Ignore `writable` in policy decisions.
4. Deprecate `state.allowed_paths` and `state.forbidden_paths`.
5. Update wizard defaults so they generate stage examples, not runtime path state.
6. Rewrite tests around static workflow-owned policy.
