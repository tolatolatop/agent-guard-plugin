# Workflow Schema

This document defines the supported user-facing `workflow.yaml` authoring format for `agent-guard`.

Workflow authors should write workflow files in the stage-centered author DSL used by the bundled workflows and current Python implementation.

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
version: 2

workflow:
  id: standard
  title: Standard Workflow
  description: Reference workflow for agent-guard.
  entry: CLARIFYING

global_gates:
  - Do not write outside stage permissions.

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
      - DESIGNING
      - PLANNING
```

For a full example, see [workflow.example.yaml](./workflow.example.yaml).

## Top-Level Fields

### `version`

Type: integer

Current bundled workflows use `version: 2`.

### `workflow`

Type: mapping

Supported fields:

- `id`
- `title`
- `description`
- `entry`

`entry` must name one of the stages defined under `stages`.

`workflow.roles` is not supported. Runtime helpers infer known roles only from hard workflow structure:

- `final: true`
- `required_command` gates such as `ready-to-summarize` and `mark-done`
- required artifacts declared in `exit`
- the `NEEDS_HUMAN` stage
- the canonical `RED_TEST` stage identity for expected red-test failures

### `global_gates`

Type: list of strings

Global prompt guidance surfaced to agents during session start. Despite the historical field name, these strings are not machine gates by themselves.

### `globals`

Type: mapping

Supported sections:

- `protected`
- `sensitive`
- `failures`
- `finalize`
- `wizard`
- `session_start`
- `install`

### `stages`

Type: mapping

Each key is a stage name. Each stage supports:

- `goal`
- `plan`
- `final`
- `allow`
- `deny`
- `enter`
- `exit`
- `expect`
- `next`

## Unsupported Old Schemas

Only `version: 2` and the stage-centered schema documented here are supported.

Older workflow shapes are rejected at load time with a repair-oriented error. Unsupported examples include:

- `version: 1`
- `workflow.roles`
- `globals.paths`
- `globals.finalization`
- stage fields named `intent`, `permissions`, `transitions`, or `evidence`

Migrate old files by removing `workflow.roles`, moving path policy into `globals.protected` and `globals.sensitive`, finalization policy into `globals.finalize`, and each stage into `goal`, `plan`, `allow`, `deny`, `enter`, `exit`, `expect`, and `next`. If a runtime role no longer resolves, express it through hard structure instead of a role declaration.

## `globals`

### `globals.protected`

Type: list of path globs

Protected paths are never directly writable by the agent.

Example:

```yaml
protected:
  - .agent/state.json
```

### `globals.sensitive`

Type: list of path globs

Sensitive paths are blocked by default and require explicit stage write permission.

Example:

```yaml
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

### `globals.finalize`

Type: mapping

Supported fields:

- `require`
- `messages`

`require` is a list of built-in finalization rules. A rule can be written as a string or as an object with `rule`.
Finalization rules are completion evidence, separate from ordinary stage exit rules.

Example:

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

Type: mapping

Supported fields:

- `start_stages`

### `globals.session_start`

Type: mapping

Supported fields:

- `navigator_skill`

This is workflow-specific context packaging. It selects the navigator skill shown by `session-start`; it does not change stage execution rules.

### `globals.install`

Type: mapping

Supported fields:

- `skills.match`
- `skills.exclude_match`

These are workflow-specific default filters for installed skill context. CLI install filters take precedence over workflow defaults. If workflow defaults match no skills, install warns and falls back to full skill installation.

## DSL Layers

The schema separates hard runtime semantics from prompt/context fields:

- Flow: `workflow.entry`, stage `next`, and inferred inbound edges.
- Gates: stage `enter`, stage `exit`, `final`, `plan`, `globals.failures`, and `globals.finalize`.
- Write policy: `globals.protected`, `globals.sensitive`, stage `allow.write`, and stage `deny.write`.
- Guidance: `goal`, `global_gates`, `allow.actions`, `deny.actions`, and `expect`.
- Context packaging: `globals.session_start` and `globals.install`.

Machine-enforced behavior must come from flow, gates, write policy, plan mode, finalization policy, or failure policy. Guidance fields are displayed to agents but must not be used as a second source of runtime truth.

## Stage Shape

Each stage must use the stage-centered layout:

```yaml
SOME_STAGE:
  goal: One clear sentence describing the stage objective.
  plan: deny | create | follow | advance | complete
  final: false

  allow:
    write: []
    actions: []
    stop: true
    human: true

  deny:
    write: []
    actions: []

  enter: []
  exit: []
  expect: []
  next: []
```

## Stage Fields

### `goal`

Type: string

Human-readable statement of the stage objective.
This is prompt guidance and the primary human-facing statement of stage responsibility.

### `plan`

Type: string

Allowed values:

- `deny`
- `create`
- `follow`
- `advance`
- `complete`

This field controls how the stage relates to `.agent/plan.yaml` and step progression.

### `final`

Type: boolean

Optional marker for a final stage.

### `allow.write`

Type: list of path globs

Paths the stage may write.
This is part of machine write policy.

### `allow.actions`

Type: list of strings

Actions the stage is intended to perform.
This is prompt guidance only. It is projected as `guidance.allowed_actions` during session start and is not a machine permission.

### `allow.stop`

Type: boolean

Controls whether the stage may stop naturally.

### `allow.human`

Type: boolean

Controls whether the stage may hand off to a human stop path.

### `deny.write`

Type: list of path globs

Paths the stage must not write, even if a broader allow rule exists.
This is part of machine write policy.

### `deny.actions`

Type: list of strings

Actions the stage must avoid.
This is prompt guidance only. It is projected as `guidance.forbidden_actions` during session start and is not a machine permission.

### `enter`

Type: list

Stage-entry gates. Each item may be:

1. A simple path string.
2. A path object:

```yaml
- path: .agent/plan.yaml
```

3. A rule object:

```yaml
- rule: active_task
  display: active task exists
```

Rule checks may also carry `value` when the built-in rule requires one.

Path-based enter checks support:

- one exact file
- one directory
- one glob pattern such as `output/**` or `output/*/review.md`

Path objects may also carry optional content validation:

```yaml
- path: output/** 
  matches: '^# Ready'
  display: validated output must start with # Ready
```

If an item only contains `display`, it is treated as prompt text rather than a blocking machine check.

### `exit`

Type: list

Hard stage-exit gates. Each item may be:

1. A simple required artifact path.
2. A path object with optional content validation:

```yaml
- path: .agent/artifacts/failure-analysis.md
  matches: '^## Failure Summary'
  display: failure-analysis.md must start with the Failure Summary section.
```

3. A rule object:

```yaml
- rule: command_ran
  value: "(^|\\s)pytest(\\s|$)"
  display: must run pytest during VERIFY
```

Behavior:

- `path` may refer to one file, one directory, or a glob pattern such as `output/**` or `output/*/review.md`
- if a required artifact is missing, exit is blocked
- if it existed before stage entry but was not updated during the stage, exit is blocked
- if `matches` is configured and content does not match, exit is blocked with the configured `display`

### `expect`

Type: list of paths

Soft guidance only. Missing expected artifacts do not block stage exit.
Expected artifacts are displayed to agents but do not participate in exit gates, finalization gates, or runtime role inference.

### `next`

Type: list of stage names

Legal next stages from the current stage.

## Important Workflow Semantics

- `exit` is the hard stage-exit gate.
- `agent-guard verify [--auto-ready] -- <command>` is the preferred CLI path for verification stages: it runs the command, writes `.agent/artifacts/final-verification.log`, records `last_verification`, and can run `ready-to-summarize` after success.
- `expect`, `allow.actions`, `deny.actions`, `goal`, and `global_gates` are prompt guidance only.
- write control comes from `globals.protected`, `globals.sensitive`, `allow.write`, and `deny.write`.
- `plan: create` is the stage mode that opens normal plan authoring.
- `plan: advance` enables `complete-step`.

## Notes On `.agent/state.json` And `.agent/plan.yaml`

- `.agent/state.json` should be treated as a protected file and changed through `agent-guard` workflow commands.
- `.agent/plan.yaml` is workflow-governed. Whether it may be updated depends on the active stage and workflow policy.

## Authoring Guidance

- Prefer repository-local files under `workflows/` for project-specific workflows.
- Use user-level files under `~/.config/agent-guard/workflow/` only when you want cross-repository overrides.
- Keep stage rules explicit and small.
- Put hard evidence requirements in `exit`.
- Put soft guidance artifacts in `expect`.
- Keep stage intent in `goal`.
