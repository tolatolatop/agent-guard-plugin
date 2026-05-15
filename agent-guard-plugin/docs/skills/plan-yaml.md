---
name: plan-yaml
description: Read and write a minimal .agent/plan.yaml for agent-guard tasks using only step name, description, and status.
---

# Plan YAML

Use this skill when:

- creating `.agent/plan.yaml`
- updating planned steps before execution
- reading a plan to understand task progress
- reconciling workflow state with a human-readable task checklist

What `plan.yaml` is for:

- declare concrete workflow steps in a human-readable checklist
- track what is pending, in progress, or done
- describe intent without carrying execution policy

What `plan.yaml` is not for:

- file write policy
- stage transitions
- required commands
- review gates

## File shape

`plan.yaml` is a YAML mapping. The main field is `steps`, which must be a list.

Each step is a mapping with exactly these practical fields:

- `name`: stable step name such as `red-001` or `review-001`
- `description`: one short sentence describing the concrete outcome
- `status`: simple progress marker such as `pending`, `in_progress`, or `done`

Minimal example:

```yaml
task_id: password-reset
steps:
  - name: red-001
    description: Add a failing password reset API test
    status: done
  - name: green-001
    description: Implement the password reset handler
    status: in_progress
  - name: review-001
    description: Review the implementation diff and capture findings
    status: pending
```

## Reading checklist

When reading an existing plan:

1. Check that `steps` is a list.
2. Find the first non-terminal step by scanning `status`.
3. Confirm the step name exists at most once.
4. Read `description` to understand the intended outcome.
5. Read `status` to understand human-visible progress.
6. Do not infer write policy or transition legality from the plan.

## Writing checklist

When writing or updating a plan:

1. Keep steps small enough that one step has one clear completion event.
2. Use stable step names. Do not rename a step after execution has started unless you also reconcile state.
3. Keep descriptions short and outcome-focused.
4. Use a small status vocabulary such as `pending`, `in_progress`, `done`.
5. Prefer one real completion event per step.
6. Keep execution policy in workflow config, not in `plan.yaml`.

## Step progression

Use `complete-step` when a real planned step finished and its `status` in `plan.yaml` should be set to `done`.

Use `advance-stage` when:

- moving through a non-execution stage without finishing a planned step
- re-entering an execution stage under the stage's static workflow policy
- changing stage while preserving the current step context

## Common mistakes

- writing `steps` as a mapping instead of a list
- trying to store path policy or stage policy in the plan
- making one step too broad to have a clear done condition
- changing step names after agents have started using them as stable plan identifiers
