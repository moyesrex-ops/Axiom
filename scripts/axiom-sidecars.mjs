import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const scriptPath = fileURLToPath(import.meta.url);
const repoRoot = path.resolve(path.dirname(scriptPath), "..");
const runtimePath = path.join(repoRoot, "config", "runtime.json");
const localRuntimePath = path.join(repoRoot, "config", "runtime.local.json");

function readJson(filePath) {
  if (!fs.existsSync(filePath)) {
    return {};
  }
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function mergeConfig(baseConfig, overlayConfig) {
  const merged = { ...baseConfig };
  for (const [key, value] of Object.entries(overlayConfig)) {
    if (isPlainObject(value) && isPlainObject(merged[key])) {
      merged[key] = mergeConfig(merged[key], value);
      continue;
    }
    merged[key] = value;
  }
  return merged;
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return "";
}

function yesNo(value) {
  return value ? "yes" : "no";
}

function printRow(name, configured, detail) {
  const paddedName = name.padEnd(18, " ");
  console.log(`${paddedName} configured=${configured.padEnd(3, " ")}  ${detail}`);
}

const mergedConfig = mergeConfig(readJson(runtimePath), readJson(localRuntimePath));
const telegram = mergedConfig.channels?.telegram ?? {};
const skillLibrary = mergedConfig.skill_library ?? {};
const agentLibrary = mergedConfig.agent_library ?? {};

console.log("AXIOM sidecar and catalog configuration");
console.log("=".repeat(72));
console.log(`repo root           ${repoRoot}`);
console.log(`runtime.json        ${fs.existsSync(runtimePath) ? "present" : "missing"}`);
console.log(`runtime.local.json  ${fs.existsSync(localRuntimePath) ? "present" : "missing"}`);
console.log("");

printRow(
  "telegram",
  yesNo(Boolean(telegram.enabled)),
  `mode=${telegram.plain_message_mode ?? "smart"} allowed_chat_ids=${Array.isArray(telegram.allowed_chat_ids) ? telegram.allowed_chat_ids.length : 0}`
);
printRow(
  "deerflow",
  yesNo(Boolean(mergedConfig.integrations?.deerflow_path || mergedConfig.deerflow?.repo_path)),
  firstNonEmpty(mergedConfig.deerflow?.repo_path, mergedConfig.integrations?.deerflow_path, "repo path not set")
);
printRow(
  "paperclip",
  yesNo(Boolean(mergedConfig.paperclip?.repo_path)),
  firstNonEmpty(mergedConfig.paperclip?.repo_path, skillLibrary.paperclip_path, agentLibrary.paperclip_path, "repo path not set")
);
printRow(
  "openfang",
  yesNo(Boolean(mergedConfig.openfang?.repo_path)),
  firstNonEmpty(mergedConfig.openfang?.repo_path, skillLibrary.openfang_path, agentLibrary.openfang_path, "repo path not set")
);
printRow(
  "symphony",
  yesNo(Boolean(mergedConfig.symphony?.repo_path || agentLibrary.symphony_path)),
  firstNonEmpty(mergedConfig.symphony?.repo_path, agentLibrary.symphony_path, "repo path not set")
);
printRow(
  "lossless_claw",
  yesNo(Boolean(mergedConfig.lossless_claw?.repo_path || agentLibrary.lossless_claw_path)),
  firstNonEmpty(mergedConfig.lossless_claw?.repo_path, agentLibrary.lossless_claw_path, "repo path not set")
);
printRow(
  "impeccable",
  yesNo(Boolean(skillLibrary.impeccable_path)),
  firstNonEmpty(skillLibrary.impeccable_path, "repo path not set")
);
printRow(
  "gstack",
  yesNo(Boolean(skillLibrary.gstack_path)),
  firstNonEmpty(skillLibrary.gstack_path, "repo path not set")
);
printRow(
  "cli_anything",
  yesNo(Boolean(skillLibrary.cli_anything_path)),
  firstNonEmpty(skillLibrary.cli_anything_path, "repo path not set")
);
printRow(
  "uncodixfy",
  yesNo(Boolean(skillLibrary.uncodixfy_path)),
  firstNonEmpty(skillLibrary.uncodixfy_path, "repo path not set")
);
printRow(
  "tradingagents",
  yesNo(Boolean(mergedConfig.tradingagents?.repo_path || agentLibrary.tradingagents_path)),
  firstNonEmpty(mergedConfig.tradingagents?.repo_path, agentLibrary.tradingagents_path, "repo path not set")
);
printRow(
  "autoresearch",
  yesNo(Boolean(mergedConfig.research_repos?.autoresearch_path)),
  firstNonEmpty(mergedConfig.research_repos?.autoresearch_path, "repo path not set")
);

if (process.argv.includes("--json")) {
  console.log("");
  console.log(JSON.stringify(mergedConfig, null, 2));
}
