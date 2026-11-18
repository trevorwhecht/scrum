// Playwright config wrapper for a machine without Playwright's own Chromium (the shop Mac). From the repo root,
//   SCRUM_PW_CHANNEL=chrome npx playwright test --config "$HOME/.claude/skills/trevskills-e2e/channel.config.mjs"
// runs the repo's own playwright.config.* with use.channel set on its chromium projects. Playwright resolves a config's
// relative paths against the config file's folder (this one), so each of them is pinned to the repo here instead.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const repo = process.cwd();
const file = ["ts", "js", "mts", "mjs", "cts", "cjs"].map((ext) => path.join(repo, `playwright.config.${ext}`))
  .find((f) => fs.existsSync(f));
if (!file) throw new Error(`channel.config.mjs: no playwright.config.* in ${repo}`);
const mod = await import(pathToFileURL(file).href);
let config = mod.default ?? mod;
if (config.__esModule && config.default) config = config.default; // CommonJS `exports.default`, as a .ts transpiles to
const channel = (process.env.SCRUM_PW_CHANNEL ?? "").trim();
const at = (p) => (typeof p === "string" && p ? path.resolve(repo, p) : p);
const projects = Array.isArray(config.projects) ? config.projects : [];

for (const o of [config, ...projects]) {
  for (const key of ["testDir", "outputDir", "snapshotDir"]) if (o[key]) o[key] = at(o[key]);
}
if (!config.testDir) {
  // Playwright skips gitignored files only when no testDir is set; keep that now testDir is the repo.
  // A project-level value would beat a top-level one, so a repo's own top-level respectGitIgnore is left alone.
  if (config.respectGitIgnore === undefined) {
    for (const o of projects.length ? projects : [config]) if (!o.testDir) o.respectGitIgnore ??= true;
  }
  config.testDir = repo;
}
config.outputDir ||= path.join(repo, "test-results");
for (const key of ["globalSetup", "globalTeardown"]) {
  if (config[key]) config[key] = Array.isArray(config[key]) ? config[key].map(at) : at(config[key]);
}
if (config.tsconfig) config.tsconfig = at(config.tsconfig);
for (const server of [config.webServer ?? []].flat()) server.cwd = server.cwd ? at(server.cwd) : repo;
const builtinReporters = ["list", "line", "dot", "json", "junit", "null", "github", "html", "blob"];
// Playwright resolves a custom reporter id from this file's folder; resolve it from the repo instead.
const reporterId = (name) => {
  if (typeof name !== "string" || builtinReporters.includes(name)) return name;
  if (name.startsWith(".")) return at(name);
  try { return createRequire(path.join(repo, "package.json")).resolve(name); } catch { return name; }
};
if (config.reporter) {
  config.reporter = (typeof config.reporter === "string" ? [[config.reporter]] : config.reporter).map(([name, opts]) => {
    const o = { ...opts };
    for (const key of ["outputFolder", "outputFile"]) if (o[key]) o[key] = at(o[key]);
    if (name === "html") o.outputFolder ??= path.join(repo, "playwright-report");
    return [reporterId(name), o];
  });
}

if (channel) {
  // Playwright's own order: use is the top-level use under the project's, and browserName defaults to
  // defaultBrowserType, which defaults to chromium.
  const top = config.use ?? {};
  const browser = (use = {}) =>
    use.browserName ?? top.browserName ?? use.defaultBrowserType ?? top.defaultBrowserType ?? "chromium";
  if (config.projects) {
    for (const p of projects) if (browser(p.use) === "chromium") p.use = { ...p.use, channel };
  } else if (browser() === "chromium") {
    config.use = { ...top, channel };
  }
}

export default config;
