# DDD Design: Workflow-Driven Engine DSL

## Goal

Turn `agent-guard` into a workflow-driven engine whose execution semantics come from a stable DSL, not from scattered branch logic in hooks, CLI glue, or prompt assembly.

For a more explicit split between soft prompts, hard gates, state flow, and write control, see `docs/ddd-dsl-layers.md`.

For a concrete grouped DSL example that is semantically aligned with the current standard workflow, see `docs/grouped-workflow.example.yaml`.

The workflow DSL should describe:

- stage intent
- stage permissions
- stage transitions
- stage evidence
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
version: 1

workflow:
  id: standard
  title: Standard Agent Guard Workflow
  description: Minimal workflow-driven guard for long-running coding tasks.

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

  failures:
    repeat_threshold: 2
    fingerprint_roots:
      - src
      - tests

  finalization:
    require:
      - remaining_steps_empty
      - no_running_jobs
      - successful_last_verification
      - can_finalize_flag
      - all_plan_steps_terminal
    messages:
      remaining_steps_empty: remaining_steps must be empty
      no_running_jobs: running jobs still exist
      successful_last_verification: last_verification.exit_code must be 0
      can_finalize_flag: state.can_finalize is not true
      all_plan_steps_terminal: all plan steps must be done or failed

  wizard:
    start_stages:
      - CLARIFYING
      - PLANNING
      - RED_TEST
      - GREEN_IMPL

stages:
  RED_TEST:
    intent:
      goal: Create a failing test that proves the missing behavior.

    permissions:
      write:
        allow:
          - tests/**
        deny:
          - src/**
      actions:
        allow:
          - write tests
          - run targeted tests
          - save failing logs
        deny:
          - write production code
          - claim implementation is complete
      commands:
        complete_step: allow
      handoff:
        human_stop: deny
        deny_message: Current stage does not allow human intervention; continue advancing the task.

    transitions:
      to:
        - GREEN_IMPL
        - NEEDS_FAILURE_ANALYSIS
      enter_when: []

    evidence:
      expected:
        - .agent/artifacts/red-test.log
      required: []
```

## Stage Structure

Every stage should use the same four groups.

### `intent`

Contains the stage goal only.

Example:

```yaml
intent:
  goal: Implement the smallest code change that makes the targeted test pass.
```

This is descriptive. It tells the agent what the stage is for.

### `permissions`

Contains everything the stage allows or denies.

```yaml
permissions:
  write:
    allow:
      - src/**
      - tests/**
    deny: []
  actions:
    allow:
      - write minimal production code
      - update tests if required
      - run targeted verification
    deny:
      - broad refactors
      - unrelated formatting
  commands:
    complete_step: allow
  handoff:
    human_stop: deny
    deny_message: Current stage does not allow human intervention; continue advancing the task.
```

This replaces field sprawl such as:

- `write_policy`
- `allowed_actions`
- `forbidden_actions`
- `allows_complete_step`
- `forbid_needs_human`

### `transitions`

Contains the state graph and transition-entry rules.

```yaml
transitions:
  to:
    - REVIEW
    - NEEDS_FAILURE_ANALYSIS
  enter_when:
    - rule: active_task
      display: active task exists
```

This replaces:

- `allowed_next_stages`
- `entry_conditions`

`enter_when` stays declarative. It names built-in evaluator rules, but does not execute arbitrary scripts.

### `evidence`

Contains stage artifacts.

```yaml
evidence:
  expected:
    - .agent/artifacts/final-verification.log
  required:
    - .agent/artifacts/review.md
```

Rules:

- `required` participates in guards and display.
- `expected` is optional display-only metadata.
- Display should dedupe `required` and `expected`.

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
- `completed_steps`
- `remaining_steps`
- `can_finalize`
- `last_verification`
- `needs_human`

It should not own workflow configuration.

### `PlanStep`

`PlanStep` should stay focused on task planning:

- `id`
- `stage`
- `goal`
- `commands`
- `success_condition`
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

- `active_task`
- `required_command`
- `successful_last_verification`
- `no_running_jobs`
- `all_plan_steps_terminal`
- `can_finalize_passes`

The registry is code.
The rule composition is workflow data.

This preserves safety and testability while avoiding arbitrary script execution in the DSL.

## Compatibility Mapping

The current repository still uses a flatter `.workflow.yaml`.
The target DSL should map mechanically from the current shape.

Mapping:

- `goal` -> `intent.goal`
- `write_policy.writable_paths` -> `permissions.write.allow`
- `write_policy.denied_paths` -> `permissions.write.deny`
- `allowed_actions` -> `permissions.actions.allow`
- `forbidden_actions` -> `permissions.actions.deny`
- `allows_complete_step` -> `permissions.commands.complete_step`
- `forbid_needs_human` -> `permissions.handoff.human_stop: deny`
- `allowed_next_stages` -> `transitions.to`
- `entry_conditions.any` -> `transitions.enter_when`
- `artifacts_expected` -> `evidence.expected`
- `artifacts_required` -> `evidence.required`

Top-level mapping:

- `metadata` -> `workflow`
- `path_policy` -> `globals.paths`
- `failure_policy` -> `globals.failures`
- `finalization_policy` -> `globals.finalization`
- `wizard_defaults` -> `globals.wizard`

## Migration Guidance

Migration should happen in two steps.

### Step 1

Keep runtime behavior the same, but update docs and internal adapters to think in:

- `intent`
- `permissions`
- `transitions`
- `evidence`

### Step 2

Update `.workflow.yaml` parsing so the grouped DSL becomes the actual source format, and keep a compatibility shim only if necessary.

## Test Expectations

Tests for the DSL should cover:

- invalid top-level sections fail closed
- invalid stage grouping fails closed
- unknown transition rule names fail closed
- `permissions.write.allow` and `permissions.write.deny` drive write guards
- `permissions.commands.complete_step` drives `complete-step`
- `transitions.to` drives the generated Mermaid graph
- `evidence.required` drives exit gating
- `globals.finalization.require` drives `can-finalize`

## Summary

The target DDD DSL is a stage-grouped policy language:

- `intent`
- `permissions`
- `transitions`
- `evidence`

plus a small `globals` section for cross-stage rules.

That keeps the workflow explicit, teachable, and portable across agent runtimes without leaking runtime mechanics into user-facing configuration.
