#!/usr/bin/env node
/*
  SpecForge validator launcher.
  Core alpha intentionally keeps the first executable validator simple.
  This wrapper delegates YAML parsing to the Python validator to avoid
  silently implementing an incomplete YAML parser in JavaScript.
*/
const { spawnSync } = require("child_process");
const path = require("path");

const validator = path.join(__dirname, "validate-specforge.py");
const target = process.argv[2] || process.cwd();

let result = spawnSync("python", [validator, target], { stdio: "inherit" });

if (result.error || result.status === null) {
  result = spawnSync("python3", [validator, target], { stdio: "inherit" });
}

if (result.error) {
  console.error("Unable to launch Python validator:", result.error.message);
  process.exit(2);
}

process.exit(result.status);
