# Workflow Schema

This document defines the workflow authoring schema that `agent-guard` should treat as the supported user-facing `.workflow.yaml` format.

It deliberately separates:

- the author-facing workflow DSL
- internal normalized runtime structures
- compatibility layers for older workflow files

The goal is to make workflow authoring stable and unambiguous.

## Scope

This document describes the schema that workflow authors should write in:

- `workflows/default.workflow.yaml`
- `workflows/<workflow_id>.workflow.yaml`
- repository-local workflow overrides
- user-level workflow overrides

It does not describe internal normalized structures such as:

- `entry_conditions`
- `exit_conditions`
- `write_policy`
- `artifacts_required`
- `path_policy`
- `finalization_policy`

Those are runtime projection structures, not the public authoring format.

## Status

The supported public schema is the stage-centered v2 DSL.

Compatibility support may still exist in code for older grouped or normalized workflow documents, but those formats are not the intended long-term authoring interface and should not be documented as first-class workflow authoring options.

## File Shape

The supported workflow file shape is:

```yaml
version: 2

workflow:
  id: default
  title: Default Workflow
  description: Reference workflow for agent-guard.
  entry: CLARIFYING

global_gates:
  - Do not modify .agent/state.json directly.

globals:
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

  finalize:
    require:
      - rule: no_running_jobs
      - rule: can_finalize_flag
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
    goal: Resolve task intent before implementation.
    plan: deny
    allow:
      write:
        - .agent/**
      actions:
        - clarify requirements
      stop: true
      human: true
    deny:
      write: []
      actions:
        - implement before requirements are clear
    enter: []
    exit: []
    expect: []
    next:
      - PLANNING
```

## Top-Level Fields

### `version`

- Type: integer
- Supported public value: `2`

This identifies the author-facing schema generation.

### `workflow`

- Type: mapping
- Required fields:
  - `id`: string
  - `title`: string
  - `description`: string
  - `entry`: stage name

This is workflow metadata plus the default workflow entry stage.

### `global_gates`

- Type: list of strings

These are human-readable global discipline rules shown to the agent/operator. They are guidance text, not independently executable rule definitions.

### `globals`

- Type: mapping

Supported fields:

- `protected`
- `sensitive`
- `failures`
- `finalize`
- `wizard`
- `session_start`
- `install`

## `globals`

### `globals.protected`

- Type: list of path globs

Paths managed by `agent-guard` and not directly writable through normal agent file edits.

Example:

```yaml
protected:
  - .agent/state.json
```

### `globals.sensitive`

- Type: list of path globs

Paths that require explicit stage write permission.

Example:

```yaml
sensitive:
  - .github/**
  - infra/**
```

### `globals.failures`

- Type: mapping

Supported fields:

- `repeat_threshold`: integer
- `fingerprint_roots`: list of directory roots

Example:

```yaml
failures:
  repeat_threshold: 2
  fingerprint_roots:
    - src
    - tests
```

### `globals.finalize`

- Type: mapping

Supported fields:

- `require`: list of rule objects
- `messages`: mapping of rule name -> failure message

`require` items should be rule mappings:

```yaml
finalize:
  require:
    - rule: no_running_jobs
    - rule: can_finalize_flag
  messages:
    no_running_jobs: running jobs still exist
    can_finalize_flag: state.can_finalize is not true
```

### `globals.wizard`

- Type: mapping

Supported fields:

- `start_stages`: list of stage names

### `globals.session_start`

- Type: mapping

Supported fields:

- `navigator_skill`: string

### `globals.install.skills`

- Type: mapping

Supported fields:

- `match`: list of regex strings
- `exclude_match`: list of regex strings

## `stages`

`stages` is a mapping from stage name to stage policy.

Each stage supports:

- `goal`
- `plan`
- `final`
- `allow`
- `deny`
- `enter`
- `exit`
- `expect`
- `next`

## Stage Fields

### `goal`

- Type: string

Human-readable description of the stage objective.

### `plan`

- Type: string
- Allowed values:
  - `deny`
  - `create`
  - `follow`
  - `advance`
  - `complete`

This is a workflow policy mode for `plan.yaml`, not just a display label.

Meaning:

- `deny`: plan edits are not part of this stage
- `create`: the stage is allowed to create or define the plan
- `follow`: the stage follows an existing plan without advancing plan step state
- `advance`: the stage may advance plan step execution state
- `complete`: the workflow is in completion-oriented plan semantics

This field influences:

- whether `plan.yaml` is directly writable
- whether `plan.yaml` is expected/required by default
- whether `complete-step` is allowed from the stage

### `final`

- Type: boolean
- Optional

Marks the workflow completion stage.

### `allow`

- Type: mapping

Supported fields:

- `write`: list of path globs
- `actions`: list of strings
- `stop`: boolean
- `human`: boolean

Example:

```yaml
allow:
  write:
    - tests/**
  actions:
    - write tests
    - run targeted tests
  stop: false
  human: false
```

### `deny`

- Type: mapping

Supported fields:

- `write`: list of path globs
- `actions`: list of strings

Example:

```yaml
deny:
  write:
    - src/**
  actions:
    - write production code
```

### `enter`

- Type: list

This defines entry gates for the stage.

Supported item forms:

1. Rule condition

```yaml
- rule: active_task
  display: active task exists
```

2. Path existence condition

```yaml
- path: .agent/artifacts/review.md
```

3. Display-only note

```yaml
- display: can_finalize enabled only through ready-to-summarize
```

`display` is the user-facing explanation shown when the rule is presented or fails.

### `exit`

- Type: list

This is a mixed stage-exit list. It currently supports both:

1. Required artifact evidence

```yaml
- .agent/artifacts/review.md
```

or

```yaml
- path: .agent/artifacts/failure-analysis.md
  matches: '^## Failure Summary'
  display: failure-analysis.md must start with the Failure Summary section.
```

2. Rule-based exit conditions

```yaml
- rule: command_succeeded
  value: "(^|\\s)pytest(\\s|$)"
  display: pytest must succeed during VERIFY
```

Important:

- artifact entries are hard exit evidence
- `matches` and artifact `display` belong only to artifact entries
- rule entries use `display` as the surfaced failure message

Current behavior note:

- `exit` is a mixed field in the author DSL
- internally it is projected into:
  - required artifact evidence
  - rule-based exit conditions

That mixed shape is supported, but authors should use it carefully because it combines two different domain concepts in one list.

### `expect`

- Type: list of path strings

These are expected artifacts, not hard gates.

### `next`

- Type: list of stage names

These are the legal next stages.

## Supported Rule Objects

Where rule items are supported, the public shape is:

```yaml
- rule: rule_name
  value: optional string
  display: human-readable explanation
```

`display` should be treated as required for rule-based stage conditions, because it is the message surfaced to the user when a gate blocks.

The allowed rule names come from built-in rule evaluation in code. Workflow authors should use only documented built-in rule names.

## Supported Artifact Objects

Artifact requirements support these forms:

1. Simple path:

```yaml
- .agent/artifacts/review.md
```

2. Path with content requirement:

```yaml
- path: .agent/artifacts/failure-analysis.md
  matches: '^## Failure Summary'
  display: failure-analysis.md must start with the Failure Summary section.
```

Supported fields:

- `path`
- `matches`
- `display`

Compatibility-only input:

- `message`

Artifact validation text should use `display`. `message` is accepted only as a legacy alias.

## Not Part Of The Public Authoring Schema

The following fields may still appear in code or internal normalized structures, but they are not part of the supported author-facing workflow schema:

- `metadata`
- `entry_stage`
- `protected_paths`
- `path_policy`
- `failure_policy`
- `finalization_policy`
- `wizard_defaults`
- `session_start_defaults`
- `install_defaults`
- `entry_conditions`
- `exit_conditions`
- `write_policy`
- `artifacts_expected`
- `artifacts_required`

Likewise, older grouped forms such as:

- `globals.paths`
- `globals.finalization`
- `stages.*.intent`
- `stages.*.permissions`
- `stages.*.transitions`
- `stages.*.evidence`

should be treated as compatibility input only, not as the preferred workflow authoring format.

## Semantics And Caveats

### Clear semantics

These concepts are reasonably clear and stable:

- `workflow.entry`
- `goal`
- `allow.write`
- `deny.write`
- `allow.actions`
- `deny.actions`
- `expect`
- `next`
- `globals.failures`
- `globals.finalize`

### Mixed semantics

These areas need care when authoring:

#### `exit`

`exit` mixes:

- evidence requirements
- rule-based transition guards

That is convenient, but it is not conceptually pure. Authors should remember that:

- path entries become required evidence
- rule entries become machine-evaluated exit guards

#### `display-only` condition items

`enter` currently accepts `{display: ...}` without `rule` or `path`.

This is best understood as explanatory prompt text, not a real machine-evaluated condition.

Authors should not rely on `display`-only entries when they need a hard gate.

## Recommended Authoring Rules

When writing new workflows:

1. Use only the v2 stage-centered schema documented here.
2. Do not write internal normalized fields directly.
3. Prefer rule objects with explicit `display` text for stage conditions.
4. Use artifact objects only when you need `matches` or artifact `display`.
5. Treat `expect` as soft evidence and `exit` artifact entries as hard evidence.
6. Do not rely on compatibility-only grouped or flat workflow formats for new workflow files.

## Future Cleanup Direction

To keep the DSL clearer over time, the intended direction is:

1. keep this v2 author schema as the only documented public schema
2. reduce compatibility exposure of older grouped and flat formats
3. eventually separate mixed `exit` semantics into distinct author concepts for:
   - required evidence
   - rule-based exit guards

Until then, this document is the authoritative statement of the intended supported workflow authoring format.
