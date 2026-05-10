const fs = require("node:fs");
const path = require("node:path");
const { loadState, AGENT_DIR } = require("./state");
const { loadJobs } = require("./jobs");
const { loadPlanSummary } = require("./plan");

function canFinalize(rootDir) {
  const state = loadState(rootDir);
  const jobs = loadJobs(rootDir);
  const plan = loadPlanSummary(rootDir);
  const reasons = [];

  if (state.remaining_steps.length > 0) {
    reasons.push("remaining_steps is not empty");
  }

  if (jobs.jobs.some((job) => job.status === "running")) {
    reasons.push("running jobs still exist");
  }

  if (!state.last_verification || state.last_verification.exit_code !== 0) {
    reasons.push("latest final verification is missing or failed");
  }

  if (plan.includesReview) {
    const reviewPath = path.join(rootDir, AGENT_DIR, "artifacts", "review.json");
    if (!fs.existsSync(reviewPath)) {
      reasons.push("review artifact is required by plan but missing");
    }
  }

  if (state.can_finalize !== true) {
    reasons.push("state.can_finalize is not true");
  }

  if (reasons.length > 0) {
    return {
      decision: "block",
      reasons,
    };
  }

  return {
    decision: "allow",
    reasons: [],
  };
}

module.exports = {
  canFinalize,
};
