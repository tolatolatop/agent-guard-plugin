const { loadState } = require("./state");

function getNextStep(state) {
  return state.remaining_steps[0] ?? null;
}

function getSessionReminder(rootDir) {
  const state = loadState(rootDir);
  return {
    task: state.task_id,
    stage: state.stage,
    current_step: state.current_step,
    allowed_paths: state.allowed_paths,
    forbidden_paths: state.forbidden_paths,
    next_required_action: getNextStep(state),
    can_finalize: state.can_finalize,
    reminder: `Task=${state.task_id ?? "unset"} stage=${state.stage} step=${state.current_step ?? "unset"} next=${getNextStep(state) ?? "none"} finalize=${state.can_finalize}`,
  };
}

module.exports = {
  getNextStep,
  getSessionReminder,
};
