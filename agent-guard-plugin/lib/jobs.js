const fs = require("node:fs");
const { jobsPath } = require("./state");

function loadJobs(rootDir) {
  return JSON.parse(fs.readFileSync(jobsPath(rootDir), "utf8"));
}

function checkJobPoll(rootDir, jobId) {
  const jobs = loadJobs(rootDir);
  const job = jobs.jobs.find((entry) => entry.id === jobId);
  if (!job) {
    return {
      decision: "block",
      reason: `Unknown job id: ${jobId}`,
    };
  }

  if (job.status !== "running") {
    return {
      decision: "allow",
      reason: `Job ${jobId} is already ${job.status}.`,
    };
  }

  const nextPollAfter = job.next_poll_after ? Date.parse(job.next_poll_after) : 0;
  const now = Date.now();
  if (now < nextPollAfter) {
    return {
      decision: "block",
      reason: `Job ${jobId} cannot be polled before ${job.next_poll_after}.`,
    };
  }

  if (typeof job.max_polls === "number" && job.poll_count >= job.max_polls) {
    return {
      decision: "block",
      reason: `Job ${jobId} exceeded max poll count and requires human review.`,
    };
  }

  return {
    decision: "allow",
    reason: `Job ${jobId} can be polled now.`,
  };
}

module.exports = {
  loadJobs,
  checkJobPoll,
};
