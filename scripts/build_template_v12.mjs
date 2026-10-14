// Compatibility wrapper for callers that still invoke the historical .mjs name.
// The implementation lives in Python so clean installs do not depend on the
// Codex-only @oai/artifact-tool package.
import { spawnSync } from "node:child_process";
import process from "node:process";
import { fileURLToPath } from "node:url";
import path from "node:path";

const script = path.join(path.dirname(fileURLToPath(import.meta.url)), "build_template_v12.py");
const python = process.env.AGENTE_JIRA_PYTHON || (process.platform === "win32" ? "python" : "python3");
const result = spawnSync(python, [script, ...process.argv.slice(2)], { stdio: "inherit" });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
