# DDD Design: Workflow-Driven Engine DSL

This document is a design note, not the source of truth for the current shipped workflow file format.

For the supported authoring schema, see [workflow-schema.md](./workflow-schema.md).

## Goal

Turn `agent-guard` into a workflow-driven engine whose execution semantics come from a stable DSL, not from scattered branch logic in hooks, CLI glue, or prompt assembly.

For a more explicit split between soft prompts, hard gates, state flow, and write control, see `docs/ddd-dsl-layers.md`.

For a concrete workflow example aligned with the current standard workflow, see `docs/workflow.example.yaml`.

The workflow DSL should describe:

- stage goal
- stage plan mode
- stage allow and deny rules
- stage enter and exit gates
- stage transitions
- global path, failure, and finalization policy

Runtime adapters should translate events into application commands, but they should not own workflow semantics.

## Design Principles

1. Keep the DSL small.
2. Use stable domain language instead of runtime-specific knobs.
3. Prefer `allow` and `deny` pairs over one-off flags.
4. Keep stage-local rules inside the stage.
5. Keep global completion and failure rules at the top level.
6. Fail closed when a rule is omitted or invalid.

## Bounded Contexts

### Workflow Definition

Owns the static workflow DSL:

- stage catalog
- transition graph
- path policy
- failure policy
- finalization policy
- wizard defaults

### Task Execution

Owns the mutable task lifecycle:

- current stage
- current step
- plan progress
- verification state
- failure state
- finalization state

Primary aggregate:

- `TaskSession`

### Runtime Integration

Owns translation only:

- Claude Code hook payloads
- Codex runtime events
- OpenCode runtime events

This layer must not decide whether a write, transition, or finalization is legal.

### Installation and Provisioning

Owns:

- installer entrypoints
- runtime-specific hook wiring
- packaged workflow and skill assets

## Ubiquitous Language

Use these terms consistently:

- `Workflow`: the static policy document
- `Stage`: a named execution state
- `TaskSession`: the current task aggregate
- `Transition`: a legal move between stages
- `Permission`: what a stage allows or denies
- `Evidence`: durable artifacts required by the workflow
- `GuardDecision`: allow or block with a reason
- `Finalization`: the completion gate for the whole task
- `Failure Loop`: repeated equivalent failure without meaningful change

## Target DSL Shape

The target workflow shape is:

```yaml
version: 2

workflow:
  id: standard
  title: Standard Agent Guard Workflow
  entry: CLARIFYING

globals:
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

  failures:
    threshold: 2
    fingerprint:
      - src
      - tests

  finalize:
    require:
      - no_running_jobs
      - can_finalize_flag
      - all_plan_steps_terminal
  session_start:
    navigator_skill: using-workflow

stages:
  RED_TEST:
    goal: Create a failing test that proves the missing behavior.
    plan: advance
    allow:
      write:
        - tests/**
      actions:
        - write tests
        - run targeted tests
        - save failing logs
      stop: false
      human: false
    deny:
      write:
        - src/**
      actions:
        - write production code
        - claim implementation is complete
    enter: []
    exit: []
    expect:
      - .agent/artifacts/red-test.log
    next:
      - GREEN_IMPL
      - NEEDS_FAILURE_ANALYSIS
```

## Stage Structure

Every stage should use the same small set of top-level fields.

### `goal`

Contains the stage goal only.

Example:

```yaml
goal: Implement the smallest code change that makes the targeted test pass.
```

This is descriptive. It tells the agent what the stage is for.

### `plan`

Contains the stage's relationship to `.agent/plan.yaml` and planned execution.

Valid modes are:

- `deny`
- `create`
- `follow`
- `advance`
- `complete`

`plan: create` allows `.agent/plan.yaml` writes and injects the default plan artifact gates.

`plan: advance` enables `complete-step`.

### `allow` and `deny`

Contain everything the stage allows or denies.

```yaml
allow:
  write:
    - src/**
    - tests/**
  actions:
    - write minimal production code
    - update tests if required
    - run targeted verification
  stop: false
  human: false
deny:
  write: []
  actions:
    - broad refactors
    - unrelated formatting
```

This replaces field sprawl such as:

- `write_policy`
- `allowed_actions`
- `forbidden_actions`

### `enter`, `exit`, and `next`

Contain the state graph and machine-evaluable gates.

```yaml
enter: []
exit:
  - .agent/artifacts/review.md
  - rule: can_finalize_passes
next:
  - REVIEW
  - NEEDS_FAILURE_ANALYSIS
```

`enter` and `exit` items support:

- a string path shorthand
- a `{ path: ... }` object
- a `{ rule: ... }` object

`expect` remains soft guidance for likely artifacts:

```yaml
expect:
  - .agent/artifacts/final-verification.log
```

Rules:

- `exit` participates in guards and display.
- `expect` is optional display-only metadata.
- Display should dedupe `exit` and `expect`.

This replaces:

- `artifacts_expected`
- `artifacts_required`

## Why This DSL Is Better

### It matches the domain

Each stage becomes a small policy object:

- why the stage exists
- what the stage allows
- where the stage can go
- what evidence the stage expects

That is a cleaner domain model than a flat bag of fields.

### It reduces user confusion

Users do not need to learn:

- write modes
- dynamic path scopes
- special top-level command rules
- mixed action and transition flags at the same level

They only learn one stage pattern.

### It is runtime-neutral

Claude Code, Codex, and OpenCode can all consume the same semantics:

- write permissions
- transition rules
- failure policy
- finalization policy

The runtime adapter only translates payload shape and response format.

## Domain Model Impact

### `TaskSession`

`TaskSession` should own current execution state only:

- `task_id`
- `stage`
- `current_step`
- `workflow_id` when multi-workflow selection exists
- `can_finalize`
- `last_verification`
- `needs_human`

It should not own workflow configuration.

### `PlanStep`

`PlanStep` should stay focused on task planning:

- `name`
- `description`
- `status`

It should not duplicate stage-level write permissions.

### Policy Services

The DSL maps naturally to policy services:

- `WritePolicyService`
- `FailurePolicyService`
- `FinalizationPolicyService`
- `TransitionPolicyService`

Each service evaluates one slice of workflow semantics against `TaskSession` and repository state.

## Rule Evaluator Model

The workflow remains declarative.

Allowed rule names come from a built-in registry such as:

- `required_command`
- `no_running_jobs`
- `all_plan_steps_terminal`
- `can_finalize_passes`

The registry is code.
The rule composition is workflow data.

This preserves safety and testability while avoiding arbitrary script execution in the DSL.

## Historical Compatibility Mapping

This section records the historical migration concern that led to the stage-centered DSL.
It is not a current implementation contract: current workflow files must use `version: 2`, and the runtime no longer exposes the old canonical compatibility projection.

Historical mapping:

- `goal` -> stage `goal`
- `plan_mode` -> stage `plan`
- `write_policy.writable_paths` -> `allow.write`
- `write_policy.denied_paths` -> `deny.write`
- `allowed_actions` -> `allow.actions`
- `forbidden_actions` -> `deny.actions`
- `entry_conditions` -> `enter`
- `artifacts_expected` -> `expect`
- `artifacts_required` -> `exit`
- `allowed_next_stages` -> `next`

Top-level mapping:

- `metadata` -> `workflow`
- `path_policy` -> `globals.protected` and `globals.sensitive`
- `failure_policy` -> `globals.failures`
- `finalization_policy` -> `globals.finalize`
- `session_start_defaults` -> `globals.session_start`

## Test Expectations

Tests for the DSL should cover:

- invalid top-level sections fail closed
- invalid stage shapes fail closed
- unknown transition rule names fail closed
- `allow.write` and `deny.write` drive write guards
- `plan: advance` drives `complete-step`
- `next` drives the generated Mermaid graph
- `exit` drives exit gating
- `globals.finalize.require` drives `can-finalize`

## Summary

The target DDD DSL is a small stage-centered policy language:

- `goal`
- `plan`
- `allow`
- `deny`
- `enter`
- `exit`
- `expect`
- `next`

plus a small `globals` section for cross-stage rules.

That keeps the workflow explicit, teachable, and portable across agent runtimes without leaking runtime mechanics into user-facing configuration.
