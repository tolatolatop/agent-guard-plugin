# Workflow Schema

This document defines the supported user-facing `workflow.yaml` authoring format for `agent-guard`.

Workflow authors should write workflow files in the grouped DSL used by the current Python implementation.

## Where To Put A Workflow File

Repository-local workflows:

- `workflows/default.workflow.yaml`
- `workflows/<workflow_id>.workflow.yaml`

User-level overrides:

- `~/.config/agent-guard/workflow/default.workflow.yaml`
- `~/.config/agent-guard/workflow/<workflow_id>.workflow.yaml`

When a workflow id is requested, `agent-guard` checks user-level overrides first, then repository-local files, then bundled defaults.

## Supported File Shape

The supported public schema is:

```yaml
workflow:
  id: standard
  title: Standard Workflow
  description: Reference workflow for agent-guard.
  entry: CLARIFYING

globals:
  paths:
    protected:
      - .agent/state.json
    sensitive:
      - .github/**
      - Cargo.lock

  failures:
    repeat_threshold: 2
    fingerprint_roots:
      - src
      - tests

  finalization:
    require:
      - no_running_jobs
      - can_finalize_flag
    messages:
      no_running_jobs: running jobs still exist
      can_finalize_flag: state.can_finalize is not true

  wizard:
    start_stages:
      - CLARIFYING
      - PLANNING

  session_start:
    navigator_skill: using-workflow

  install:
    skills:
      match: []
      exclude_match: []

stages:
  CLARIFYING:
    intent:
      goal: Resolve task intent before implementation.

    permissions:
      write:
        allow:
          - .agent/**
        deny: []
      actions:
        allow:
          - clarify requirements
        deny:
          - implement before requirements are clear
      commands:
        complete_step: deny
      handoff:
        human_stop: allow

    transitions:
      to:
        - DESIGNING
        - PLANNING
      enter_when: []

    evidence:
      expected: []
      required: []
```

## Top-Level Fields

### `workflow`

Type: mapping

Supported fields:

- `id`
- `title`
- `description`
- `entry`

`entry` must name one of the stages defined under `stages`.

### `globals`

Type: mapping

Supported sections:

- `paths`
- `failures`
- `finalization`
- `wizard`
- `session_start`
- `install`

### `stages`

Type: mapping

Each key is a stage name. Each stage supports:

- `intent`
- `permissions`
- `transitions`
- `evidence`

## `globals`

### `globals.paths`

Type: mapping

Supported fields:

- `protected`
- `sensitive`

`protected` paths are never directly writable by the agent.

`sensitive` paths are blocked by default and require explicit stage write permission.

Example:

```yaml
paths:
  protected:
    - .agent/state.json
  sensitive:
    - .github/**
    - Cargo.lock
```

### `globals.failures`

Type: mapping

Supported fields:

- `repeat_threshold`
- `fingerprint_roots`

Example:

```yaml
failures:
  repeat_threshold: 2
  fingerprint_roots:
    - src
    - tests
```

### `globals.finalization`

Type: mapping

Supported fields:

- `require`
- `messages`

`require` is a list of built-in finalization rule names.

Example:

```yaml
finalization:
  require:
    - no_running_jobs
    - can_finalize_flag
  messages:
    no_running_jobs: running jobs still exist
    can_finalize_flag: state.can_finalize is not true
```

### `globals.wizard`

Type: mapping

Supported fields:

- `start_stages`

### `globals.session_start`

Type: mapping

Supported fields:

- `navigator_skill`

### `globals.install`

Type: mapping

Supported fields:

- `skills.match`
- `skills.exclude_match`

## Stage Shape

Each stage must use the grouped layout:

```yaml
SOME_STAGE:
  intent:
    goal: One clear sentence describing the stage objective.

  permissions:
    write:
      allow: []
      deny: []
    actions:
      allow: []
      deny: []
    commands:
      complete_step: allow | deny
    handoff:
      human_stop: allow | deny
      deny_message: Optional message shown when human stop is blocked.

  transitions:
    to: []
    enter_when: []

  evidence:
    expected: []
    required: []
```

## Stage Fields

### `intent.goal`

Type: string

Human-readable statement of the stage objective.

### `permissions.write.allow`

Type: list of path globs

Paths the stage may write.

### `permissions.write.deny`

Type: list of path globs

Paths the stage must not write, even if a broader allow rule exists.

### `permissions.actions.allow`

Type: list of strings

Actions the stage is intended to perform.

### `permissions.actions.deny`

Type: list of strings

Actions the stage must avoid.

### `permissions.commands.complete_step`

Type: `allow` or `deny`

Controls whether `complete-step` is allowed in the stage.

### `permissions.handoff.human_stop`

Type: `allow` or `deny`

Controls whether the stage may hand off to a human stop path.

If it is `deny`, `deny_message` may be provided.

### `transitions.to`

Type: list of stage names

Legal next stages from the current stage.

### `transitions.enter_when`

Type: list

Each item must be one of:

1. A simple display string.
2. A path check:

```yaml
- path: .agent/plan.yaml
```

3. A rule check:

```yaml
- rule: active_task
  display: active task exists
```

Rule checks may also carry `value` when the built-in rule requires one.

### `evidence.expected`

Type: list of paths

Soft guidance only. Missing expected artifacts do not block stage exit.

### `evidence.required`

Type: list

Supported required-artifact forms:

1. Simple path

```yaml
required:
  - .agent/artifacts/review.md
```

2. Path plus content gate

```yaml
required:
  - path: .agent/artifacts/failure-analysis.md
    matches: '^## Failure Summary'
    display: failure-analysis.md must start with the Failure Summary section.
```

Behavior:

- if a required artifact is missing, exit is blocked
- if it existed before stage entry but was not updated during the stage, exit is blocked
- if `matches` is configured and content does not match, exit is blocked with the configured `display`

## Important Workflow Semantics

- `evidence.required` is the hard stage-exit gate.
- `evidence.expected` is prompt guidance only.
- write control comes from `globals.paths` plus `permissions.write`.
- `complete_step` permission is stage-controlled through `permissions.commands.complete_step`.
- human handoff policy is stage-controlled through `permissions.handoff.human_stop`.

## Notes On `.agent/state.json` And `.agent/plan.yaml`

- `.agent/state.json` should be treated as a protected file and changed through `agent-guard` workflow commands.
- `.agent/plan.yaml` is workflow-governed. Whether it may be updated depends on the active stage and workflow policy.

## Authoring Guidance

- Prefer repository-local files under `workflows/` for project-specific workflows.
- Use user-level files under `~/.config/agent-guard/workflow/` only when you want cross-repository overrides.
- Keep stage rules explicit and small.
- Put hard evidence requirements in `evidence.required`.
- Put human-readable stage intent in `intent.goal`.
