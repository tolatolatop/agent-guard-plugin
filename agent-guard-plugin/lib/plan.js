const fs = require("node:fs");
const path = require("node:path");
const { AGENT_DIR } = require("./state");

function loadPlanSummary(rootDir) {
  const planPath = path.join(rootDir, AGENT_DIR, "plan.yaml");
  if (!fs.existsSync(planPath)) {
    return {
      exists: false,
      includesReview: false,
    };
  }

  const raw = fs.readFileSync(planPath, "utf8");
  return {
    exists: true,
    includesReview: /\bstage:\s*REVIEW\b/.test(raw),
  };
}

module.exports = {
  loadPlanSummary,
};
