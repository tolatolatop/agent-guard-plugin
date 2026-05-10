const fs = require("node:fs");
const { eventsPath } = require("./state");

function appendEvent(rootDir, event) {
  const enriched = {
    ts: new Date().toISOString(),
    ...event,
  };
  fs.appendFileSync(eventsPath(rootDir), `${JSON.stringify(enriched)}\n`);
  return enriched;
}

module.exports = {
  appendEvent,
};
