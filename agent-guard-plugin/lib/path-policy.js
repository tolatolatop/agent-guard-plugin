const path = require("node:path");

const SENSITIVE_PATTERNS = [
  ".github/**",
  "infra/**",
  "migrations/**",
  "package-lock.json",
  "pnpm-lock.yaml",
  "yarn.lock",
  "poetry.lock",
  "Cargo.lock",
];

function normalizePath(targetPath) {
  return targetPath.split(path.sep).join("/").replace(/^\.\//, "");
}

function globToRegExp(pattern) {
  const normalized = normalizePath(pattern);
  const doublePlaceholder = "__DOUBLE_WILDCARD__";
  const singlePlaceholder = "__SINGLE_WILDCARD__";
  const escaped = normalized
    .replace(/\*\*/g, doublePlaceholder)
    .replace(/\*/g, singlePlaceholder)
    .replace(/[.+^${}()|[\]\\]/g, "\\$&");
  const regexSource = escaped
    .replaceAll(doublePlaceholder, ".*")
    .replaceAll(singlePlaceholder, "[^/]*");
  return new RegExp(`^${regexSource}$`);
}

function matchesAny(targetPath, patterns = []) {
  const normalized = normalizePath(targetPath);
  return patterns.some((pattern) => globToRegExp(pattern).test(normalized));
}

function isSensitivePath(targetPath) {
  return matchesAny(targetPath, SENSITIVE_PATTERNS);
}

function blocked(reason) {
  return { decision: "block", reason };
}

function allowed(reason) {
  return { decision: "allow", reason };
}

function decideWrite(state, targetPath) {
  const normalized = normalizePath(targetPath);

  if (state.stage === "READY_TO_SUMMARIZE") {
    return blocked("Current stage is READY_TO_SUMMARIZE. Further code changes are not allowed.");
  }

  if (state.stage === "RED_TEST" && normalized.startsWith("src/")) {
    return blocked("Current stage is RED_TEST. src/** is forbidden. Write tests/** first.");
  }

  if (matchesAny(normalized, state.forbidden_paths)) {
    return blocked(`Path ${normalized} matches forbidden path policy for stage ${state.stage}.`);
  }

  if (isSensitivePath(normalized)) {
    return blocked(`Path ${normalized} is sensitive and requires human approval or an explicit plan allowance.`);
  }

  if (state.allowed_paths.length > 0 && !matchesAny(normalized, state.allowed_paths)) {
    return blocked(`Path ${normalized} is outside allowed paths for stage ${state.stage}.`);
  }

  return allowed(`Path ${normalized} is allowed during ${state.stage}.`);
}

module.exports = {
  SENSITIVE_PATTERNS,
  normalizePath,
  matchesAny,
  isSensitivePath,
  decideWrite,
};
