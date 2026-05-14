# DDD Design: DSL Layers For Soft Prompts, Hard Gates, State Flow, And Write Control

## Goal

Continue the DSL-first direction without overloading one configuration layer with every concern.

For `agent-guard`, the important question is not only "what should be configurable," but also "what kind of thing is it?"

In software-development workflows, four concerns must stay distinct:

- soft prompts
- hard gates
- state flow
- write control

If they collapse into one flat workflow file, the system becomes hard to teach, hard to evolve, and easy to misconfigure.

## Core DDD Position

These concerns belong to different conceptual layers.

### 1. Soft Prompts

Purpose:

- steer the agent
- communicate intent
- suggest behavior
- improve consistency

Soft prompts should never be the final source of truth for safety or completion.

Examples:

- the stage goal
- stage-level allowed and forbidden actions written in human language
- the session-start reminder
- workflow-oriented skill text

### 2. Hard Gates

Purpose:

- allow or block actions
- enforce evidence
- keep stage exits honest
- keep completion claims verifiable

Hard gates must be machine-evaluable.

Examples:

- transition legality
- required artifacts
- finalization rules
- failure-loop thresholds
- write decisions

### 3. State Flow

Purpose:

- represent the mutable lifecycle of a task
- record where the task is now
- record what happened
- support resumption after restart

State flow is not policy.
It is the execution history and current session fact set that policy evaluates against.

Examples:

- current `stage`
- current `step`
- `remaining_steps`
- `last_verification`
- `needs_human`
- stage entry timestamps
- artifact snapshots for exit checks

### 4. Write Control

Purpose:

- keep edits inside safe workflow boundaries
- prevent accidental source changes in the wrong stage
- protect sensitive files

Write control is a specific kind of hard gate.
It deserves its own focused submodel because it is central to coding workflows.

## Recommended Layer Split

The workflow system should be thought of as four stacked layers.

### Layer A: Definition DSL

This is the static workflow policy document.

It should express:

- stage intent
- stage permissions
- stage transitions
- stage evidence
- global path policy
- global failure policy
- global finalization policy

This is where the latest grouped DSL belongs.

### Layer B: Session State

This is mutable task execution state under `.agent/`.

It should express:

- current workflow location
- current evidence state
- command outcomes
- failure history
- snapshot data used by hard gates

This layer should not duplicate workflow policy.

### Layer C: Gate Evaluators

This is code, not user configuration.

It should:

- normalize workflow data
- evaluate rules safely
- produce `GuardDecision`
- remain runtime-neutral

Examples:

- `WritePolicyService`
- `FailurePolicyService`
- `FinalizationPolicyService`
- transition guard logic

### Layer D: Prompt Projections

This is the soft-prompt layer.

It should combine:

- current session state
- selected workflow facts
- current next-step projection
- skill text

into a concise reminder for the agent.

This layer is for readability and steering, not truth.

## What Should Live In The DSL

The DSL should hold things that are:

- stable across runtimes
- understandable by users
- small enough to validate safely
- meaningful in domain language

Good DSL candidates:

- stage goal
- stage write allow and deny patterns
- legal next stages
- entry conditions
- required artifacts
- failure repeat threshold
- fingerprint roots
- finalization rules

Weak DSL candidates:

- adapter-specific payload details
- low-level hook behavior
- shell snippets
- runtime-specific polling cadence
- derived prompt formatting

## Soft Prompts Versus Hard Gates

This distinction matters most in software development, because coding agents often obey prose until they do not.

### Soft prompts should answer:

- what is the stage trying to achieve
- what kind of work is encouraged
- what kind of work is suspicious
- what artifact is probably expected next

### Hard gates should answer:

- can this path be written
- can this stage transition happen
- can this step be marked complete
- can this task claim completion
- does this artifact satisfy exit conditions

The system should never rely on prose such as:

- "write tests first"
- "do review before verify"
- "do not finalize early"

if the corresponding hard gate does not exist.

## Software Development Scenarios

### Scenario 1: Red-Green TDD

Soft prompt:

- `RED_TEST.intent.goal` tells the agent to create a failing test first.

Hard gates:

- `RED_TEST.permissions.write` blocks `src/**`
- `RED_TEST.transitions.to` prevents illegal stage jumps
- failure policy tolerates the expected red failure only in implementation code, not in prompt text

State flow:

- `TaskSession.stage == RED_TEST`
- failure record tracks repeated identical failures

### Scenario 2: Review Before Verify

Soft prompt:

- `REVIEW.intent.goal` says review the diff and capture evidence.

Hard gates:

- `GREEN_IMPL -> VERIFY` is illegal
- `REVIEW -> VERIFY` requires the review artifact
- stage-exit snapshot logic confirms the artifact was produced or refreshed during the stage

State flow:

- stage-entry snapshot records when `REVIEW` began
- exit gate compares current artifact mtime against the recorded baseline

### Scenario 3: Verification Before Completion

Soft prompt:

- `VERIFY.intent.goal` encourages running verification commands and recording evidence.

Hard gates:

- `ready-to-summarize` requires verification success
- `mark-done` requires `can-finalize`

State flow:

- `last_verification`
- `remaining_steps`
- running jobs
- `can_finalize`

### Scenario 4: Design And Planning

Soft prompt:

- `DESIGNING.intent.goal` and `PLANNING.intent.goal` guide early task shaping.

Hard gates:

- write rules limit these stages to workflow-managed files
- stage transitions keep the workflow from skipping directly to completion

State flow:

- the task can still move back into execution stages later, but planning does not mutate write scope dynamically

## Recommended DSL Responsibilities

The grouped stage DSL should be interpreted like this.

To make this explicit in code, the workflow normalizer should expose a companion role view that marks each grouped field as:

- `soft_prompt`
- `hard_gate`
- `projection`
- `mixed`

### `intent`

Belongs to the soft-prompt layer.

It should include:

- `goal`

It may later include:

- concise checklist-style reminders
- stage summary text

But it should not contain machine-enforced policy.

### `permissions`

Mixed layer:

- `permissions.write` is a hard gate
- `permissions.commands` is a hard gate
- `permissions.handoff` is a hard gate
- `permissions.actions` is mostly soft prompt today

This is an important design point.
Not every field under `permissions` is equally enforceable yet.

Recommended direction:

- keep `actions.allow` and `actions.deny` as guidance
- avoid pretending they are enforcement unless the runtime actually checks them

### `transitions`

Hard gate.

This should remain strictly machine-evaluable:

- legal destinations
- entry conditions

### `evidence`

Mixed layer with a clear split:

- `required` is hard gate
- `expected` is soft prompt

That split is clean and should remain.

## Write Control As A First-Class Slice

Write control is important enough to keep conceptually separate from the rest of stage behavior.

Recommended final form:

```yaml
globals:
  paths:
    protected:
      - .agent/state.json
    sensitive:
      - .github/**
      - infra/**

stages:
  RED_TEST:
    permissions:
      write:
        allow:
          - tests/**
        deny:
          - src/**
```

Why this works well:

- small user-facing model
- fail-closed behavior
- runtime-neutral
- directly testable

## State Flow Should Stay Out Of The DSL

This is a common failure mode in workflow systems.

The DSL should not try to store dynamic execution facts such as:

- currently allowed runtime paths
- current failure hash
- current artifact timestamps
- current poll count

Those belong in `.agent/` state and repositories.

The new stage-artifact snapshot mechanism is a good example:

- the workflow DSL says which artifacts are required
- runtime state records when the stage began and what the baseline mtimes were
- the transition guard evaluates whether exit evidence is fresh enough

That is a correct DDD split.

## Where The Current Repository Still Mixes Layers

The current implementation is closer than before, but a few mixed areas remain.

### Prompt assembly still reads flat workflow fields

`workflow.py` still builds prompts from:

- `goal`
- `allowed_actions`
- `forbidden_actions`
- `write_policy`

Conceptually these should be read through the grouped DSL view, even if a compatibility layer remains internally.

### `permissions.actions` are not enforced

They are still guidance, not real gates.

That is acceptable if documented clearly, but the model should not imply otherwise.

### Global gates are partly prompt copy

`global_gates` are useful reminders, but they are not by themselves enforcement.
Each one should map to a concrete service or CLI gate if it is meant to be binding.

## Recommended Next Steps

If DSL-ization continues, the most coherent order is:

1. Make `workflow_spec.py` expose the grouped DSL view directly, even if it still reads the current flat YAML.
2. Move `workflow.py` prompt assembly to that grouped view so prompt projection stops depending on old field names.
3. Clearly label soft-prompt-only fields versus hard-gate fields in the workflow spec normalizer.
4. Decide whether `permissions.actions` should remain descriptive forever or gain partial enforcement later.
5. Keep dynamic execution evidence in state repositories, not in the workflow document.

## Summary

The clean DDD answer is:

- soft prompts are projections and intent
- hard gates are machine-evaluable workflow policy
- state flow is mutable execution fact
- write control is a first-class hard gate for coding work

For software development workflows, those boundaries matter more than adding more fields.
The DSL should become smaller, sharper, and more explicit about which parts guide the agent and which parts actually stop it.
