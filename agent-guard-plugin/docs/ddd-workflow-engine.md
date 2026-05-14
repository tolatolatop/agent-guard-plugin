# DDD Design: Agent Guard as a Workflow-Driven Engine

## Goal

Turn `agent-guard` from a CLI-and-hook tool with embedded workflow policy into a workflow-driven engine.

The engine should own execution semantics, while runtimes, hooks, files, and prompts become adapters around the same domain model.

This does not mean every concern belongs in workflow configuration.
It means workflow policy should be the primary source of truth for:

- stage model
- transition rules
- path policy
- command policy
- artifact requirements
- finalization conditions
- failure-loop behavior
- job polling policy

Infrastructure concerns should stay in code:

- file IO
- JSON/YAML parsing
- CLI argument parsing
- runtime payload translation
- install/uninstall for Claude Code, Codex, and OpenCode

## Design Lens

Use DDD to separate:

- domain: workflow rules and task progression
- application: use cases and orchestration
- infrastructure: files, CLI, runtime hooks, generated installers

The key shift is:

`agent-guard` should stop encoding workflow behavior in Python branch logic wherever that behavior can be expressed as workflow data plus a small set of stable rule evaluators.

## Problem With Current Shape

The repository already externalizes part of the workflow into `.workflow.yaml`, but core policy still leaks into source modules:

- `path_policy.py` hardcodes sensitive paths
- `failures.py` hardcodes repeat thresholds, code-fingerprint scope, and RED/VERIFY semantics
- `gates.py` hardcodes finalization checks and still underspecifies required evidence
- `wizard.py` hardcodes start stages, default scopes, and plan template conventions
- `transitions.py` hardcodes the supported transition rule types in `if/elif` form
- `workflow.py` hardcodes the reminder/prompt assembly shape

That means the system is not yet a workflow engine.
It is a workflow-aware application.

## Ubiquitous Language

Define the domain vocabulary first:

- `Task`: the guarded unit of work
- `Workflow`: the policy model that governs the task
- `Stage`: a named execution state in the workflow
- `Step`: a planned unit of progress within a task
- `Transition`: a legal move from one stage to another
- `Guard`: a decision that allows or blocks an action
- `Artifact`: durable evidence produced during execution
- `Command Execution`: a recorded tool or shell action with result and evidence
- `Failure Loop`: repeated equivalent failure without meaningful change
- `Job`: long-running work that must be polled under policy
- `Finalization`: the transition from active work to completion summary
- `Runtime Event`: an external hook event translated into a domain command

These terms should appear in types, CLI outputs, tests, and docs consistently.

## Bounded Contexts

The system fits best as four bounded contexts.

### 1. Workflow Definition

Owns the static policy model:

- stage catalog
- transition graph
- rule declarations
- artifact declarations
- path policy declarations
- command policy declarations
- failure policy declarations
- job policy declarations
- finalization policy declarations

Primary artifact:

- `workflow spec`

This is today’s `.workflow.yaml`, but it needs to grow into a fuller policy document.

### 2. Task Execution

Owns the mutable lifecycle of one task:

- current stage
- current step
- completed and pending plan steps
- verification evidence
- current scope
- escalation state

Primary aggregate:

- `TaskSession`

Primary persistence:

- `.agent/state.json`
- `.agent/plan.yaml`
- `.agent/jobs.json`
- `.agent/failures.json`
- `.agent/events.jsonl`

### 3. Runtime Integration

Owns translation between external tools and domain commands:

- Claude Code hook payloads
- Codex hook payloads
- OpenCode plugin events

This context should not make workflow decisions.
It should translate external events into application commands and map guard results back into runtime-specific response formats.

### 4. Installation and Provisioning

Owns:

- runtime-specific install paths
- generated hook configs
- bundled skill/workflow assets

This context is infrastructure-heavy and should remain separate from workflow policy.

## Aggregates and Entities

### Aggregate: TaskSession

`TaskSession` is the main aggregate root.

It should represent the guarded state of one active task:

- `task_id`
- `workflow_id` or `workflow_version`
- `stage`
- `current_step`
- `step_statuses`
- `active_scope`
- `last_verification`
- `needs_human`
- `can_finalize`

Responsibilities:

- apply stage transitions
- evaluate whether actions are legal under current policy
- record command outcomes
- enter failure-analysis state when required
- enter ready-to-summarize only when all required evidence exists

### Entity: PlanStep

Today `plan.yaml` is treated as a lightweight file helper.
In the target design, a step should become a domain entity:

- `id`
- `goal`
- `status`
- `stage`
- `commands`
- `success_conditions`
- `artifacts_required`

This aligns more closely with the project’s own AGENTS requirements.

### Entity: Job

A tracked long-running operation:

- `id`
- `kind`
- `command`
- `status`
- `started_at`
- `last_polled_at`
- `next_poll_after`
- `poll_count`
- `max_polls`

### Entity: FailureRecord

Represents the most recent failure-loop candidate:

- `command_signature`
- `failure_hash`
- `repeat_count`
- `code_fingerprint`
- `log_path`
- `analysis_required`

### Value Objects

Stable domain value objects should be introduced for:

- `StageName`
- `StepId`
- `PathPattern`
- `ArtifactPath`
- `CommandPolicy`
- `TransitionCondition`
- `GuardDecision`
- `VerificationRecord`
- `FailureFingerprint`

## Domain Services

The engine needs explicit domain services instead of scattered helper logic.

### WorkflowPolicyService

Evaluates static workflow rules:

- allowed writes
- legal transitions
- entry and exit conditions
- expected artifacts
- finalization requirements

This should consume the workflow spec and current aggregate state.

### FailurePolicyService

Owns:

- failure equivalence
- repeat thresholds
- analysis requirements
- escalation behavior

### JobPolicyService

Owns:

- poll intervals by job kind
- max-poll behavior
- escalation to human review

### FinalizationPolicyService

Owns:

- required verification state
- required review artifacts
- required terminal plan state
- no-running-jobs rule
- explicit finalization authorization

### SessionReminderService

Builds runtime-facing reminders from domain state plus workflow metadata.

This is still a domain-facing service, but its output format should be treated as a projection, not as domain state.

## Repositories

Repositories should hide file layout from the domain layer.

### TaskSessionRepository

Backed by:

- `.agent/state.json`
- `.agent/plan.yaml`

### JobRepository

Backed by:

- `.agent/jobs.json`

### FailureRepository

Backed by:

- `.agent/failures.json`

### EventLogRepository

Backed by:

- `.agent/events.jsonl`

### WorkflowSpecRepository

Backed by:

- packaged `.workflow.yaml`
- source `.workflow.yaml`

## Application Layer

The application layer should expose use cases instead of letting CLI commands call low-level helpers directly.

Recommended commands/use cases:

- `InitializeWorkspace`
- `StartTask`
- `ResetTask`
- `AdvanceStage`
- `CompleteStep`
- `RecordCommandExecution`
- `CheckWritePermission`
- `CheckFailureLoop`
- `CheckJobPoll`
- `CheckFinalization`
- `PrepareSummary`
- `MarkDone`
- `BuildSessionReminder`

Each use case should:

1. load aggregates from repositories
2. load workflow definition
3. invoke domain services
4. persist updated aggregates
5. emit domain events
6. return a stable machine-readable result

## Domain Events

The event log should reflect domain events, not merely hook names.

Suggested event types:

- `TaskStarted`
- `StageAdvanced`
- `StepCompleted`
- `WriteBlocked`
- `CommandRecorded`
- `FailureLoopDetected`
- `FailureAnalysisRequired`
- `JobRegistered`
- `JobPollBlocked`
- `HumanEscalationRequired`
- `FinalizationBlocked`
- `ReadyToSummarize`
- `TaskMarkedDone`

Hook names can still be included as metadata, but should not be the primary event vocabulary.

## What Belongs In Workflow Spec

To become workflow-driven, policy now embedded in code should move into the workflow definition.

### Stage Model

Already partly present and should remain:

- stage goals
- stage actions
- stage path constraints
- allowed next stages
- expected and required artifacts
- writable mode

### Transition Policy

Should be formalized further:

- named transition conditions
- conditions per transition, not only per destination stage
- whether transition is manual, command-driven, or automatic
- post-transition effects

Example shape:

```yaml
transitions:
  - from: VERIFY
    to: READY_TO_SUMMARIZE
    trigger: ready-to-summarize
    conditions:
      - rule: successful_last_verification
      - rule: no_running_jobs
      - rule: all_plan_steps_terminal
      - rule: review_artifact_present
      - rule: can_finalize_enabled
```

### Path Policy

Move these into workflow policy:

- sensitive path patterns
- protected paths
- per-stage managed-only / read-only semantics
- plan-step overrides for lockfiles or infra paths

This removes the hardcoded list now in `path_policy.py`.

### Failure Policy

Move these into workflow policy:

- repeat threshold
- fingerprint roots
- equivalent-failure strategy
- required analysis artifact
- expected-failure rules by stage or step

Example:

```yaml
failure_policy:
  repeat_threshold: 2
  fingerprint_roots:
    - src/**
    - tests/**
  expected_failures:
    - stage: RED_TEST
      exit_code: nonzero
  analysis_artifact: .agent/artifacts/failure-analysis.md
```

### Job Policy

Move these into workflow policy:

- polling interval ranges by job kind
- max poll counts
- escalation thresholds

### Finalization Policy

Move these into workflow policy:

- required terminal stage
- required verification status
- required artifacts
- required review evidence
- no-running-jobs rule

This removes the partial hardcoding now in `gates.py`.

### Wizard Defaults

Wizard behavior should come from workflow spec defaults:

- allowed bootstrap stages
- default step naming templates
- default scope by stage
- whether plan creation is recommended

## What Should Stay In Code

Even in a workflow-driven engine, some things should remain explicit code.

### Runtime Adapters

The parsing of Claude/Codex/OpenCode payloads should remain code.
Those payloads are infrastructure contracts, not workflow rules.

### Installers

Hook installation, config-file edits, and generated JS/JSON should remain code.

### Repositories and Serialization

JSON/YAML parsing, schema normalization, path resolution, and file locking remain code.

### Rule Evaluator Registry

The engine should not use arbitrary user-defined code from YAML.
It should keep a stable registry of built-in rule evaluators in Python.

Important distinction:

- the existence and composition of rules should be configured
- the implementation of each safe evaluator should stay in code

This is the correct balance between workflow-driven behavior and operational safety.

## Target Architecture

Recommended package split:

```text
src/agent_guard/
  domain/
    model/
      task_session.py
      plan_step.py
      job.py
      failure_record.py
      value_objects.py
    services/
      workflow_policy.py
      failure_policy.py
      job_policy.py
      finalization_policy.py
      reminder_service.py
    events.py

  application/
    commands.py
    handlers.py
    dto.py

  infrastructure/
    repositories/
      state_repository.py
      plan_repository.py
      jobs_repository.py
      failures_repository.py
      events_repository.py
      workflow_spec_repository.py
    runtime/
      claude_adapter.py
      codex_adapter.py
      opencode_adapter.py
    install/
      installer.py

  interfaces/
    cli.py
    runtime_bridge.py
    wizard.py
```

The existing modules can migrate toward this shape incrementally rather than all at once.

## Rule Evaluation Model

The workflow engine should use declarative rules plus a fixed evaluator registry.

Example:

```python
RULE_EVALUATORS = {
    "active_task": ActiveTaskRule(),
    "successful_last_verification": SuccessfulLastVerificationRule(),
    "no_running_jobs": NoRunningJobsRule(),
    "all_plan_steps_terminal": AllPlanStepsTerminalRule(),
    "review_artifact_present": ReviewArtifactPresentRule(),
    "required_command": RequiredCommandRule(),
}
```

The workflow spec references rules by name.
The evaluator registry implements them safely in code.

This is the core pattern that lets the system become workflow-driven without turning YAML into executable code.

## Migration Strategy

### Phase 1: Extract Domain Vocabulary

- introduce domain types for task session, plan step, job, failure record
- stop passing raw dictionaries across the codebase where behavior matters

### Phase 2: Expand Workflow Spec

- add `path_policy`
- add `failure_policy`
- add `job_policy`
- add `finalization_policy`
- add `wizard_defaults`

### Phase 3: Replace Hardcoded Policy

- move sensitive paths out of `path_policy.py`
- move repeat-threshold and fingerprint roots out of `failures.py`
- move finalization criteria out of `gates.py`
- move wizard defaults out of `wizard.py`

### Phase 4: Introduce Rule Registry

- replace `if/elif` transition-rule interpretation with rule objects
- support transition-level condition composition

### Phase 5: Reframe Runtime Bridge

- bridge only translates runtime events into application commands
- runtime-specific response rendering stays outside the domain

### Phase 6: Tighten Tests Around Domain Behavior

Prefer tests at the domain-service level:

- path guards from workflow data
- transition legality from workflow data
- failure-loop behavior from workflow data
- finalization behavior from workflow data

## Non-Goals

This design should not attempt:

- arbitrary executable workflow scripting
- user-defined Python plugins for domain rules in v1
- a distributed scheduler
- autonomous multi-agent orchestration

The engine should remain deterministic, inspectable, and file-backed.

## Proposed First Refactor Slice

The highest-leverage first slice is:

1. add `failure_policy`, `path_policy`, and `finalization_policy` sections to `.workflow.yaml`
2. create `WorkflowPolicyService`
3. make `path_policy.py`, `failures.py`, and `gates.py` read policy from the workflow model instead of hardcoded constants
4. keep CLI and runtime behavior unchanged externally

This yields the biggest architectural improvement with the least runtime disruption.

## Expected Outcome

After the refactor, `agent-guard` should be describable as:

`A file-backed workflow engine with runtime adapters`

not:

`A set of CLI helpers with some workflow metadata on the side`

That distinction matters because it determines whether future policy changes require editing Python source or primarily editing a workflow definition plus tests.
