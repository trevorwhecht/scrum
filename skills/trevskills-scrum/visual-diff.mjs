#!/usr/bin/env node
// Check gate Visual diff (lanes/review.md): captures BASE vs HEAD of each path at 390 and 1440 px in one Chromium run,
// pixel-diffs each pair with odiff and writes side-by-side crops (sharp), <out>/results.json and <out>/../visual-diff.md.
// playwright, odiff-bin and sharp load from --project-dir; when one is missing it writes a `skipped` result and exits 0.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const WIDTHS = [390, 1440];
const MIN_DIFF_PIXELS = 10;
const PAIR_CAP = 6;
const THRESHOLD = 0.1;
const TRIES = 3;
const PAD = 40;
const MAX_CROP_H = 1600;
const HIDE_CSS = "nextjs-portal, [data-nextjs-dev-tools-button] { display: none !important; }\n"
  + "*, *::before, *::after { animation: none !important; transition: none !important; }";
const USAGE = "usage: node visual-diff.mjs --base <url> --head <url> --out <dir> --project-dir <dir> "
  + "[--storage-state <file>] [--mask <css selectors, comma-separated>] <path>...";

function parseArgs(argv) {
  const opts = { paths: [] };
  const flags = { "--base": "base", "--head": "head", "--out": "out", "--project-dir": "projectDir",
    "--storage-state": "storageState", "--mask": "mask" };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a in flags) {
      if (i + 1 >= argv.length) return null;
      opts[flags[a]] = argv[++i];
    } else if (a.startsWith("--")) {
      return null;
    } else {
      opts.paths.push(a);
    }
  }
  return opts.base && opts.head && opts.out && opts.projectDir && opts.paths.length ? opts : null;
}

// render.py's slug(): `root` for /, else the path with / turned into - and the leading - dropped.
const slug = (p) => (p === "/" ? "root" : p.replaceAll("/", "-").replace(/^-/, ""));

function writeOutputs(out, status, pairs, reason) {
  fs.mkdirSync(out, { recursive: true });
  const results = status === "skipped" ? { status, reason, pairs } : { status, pairs };
  fs.writeFileSync(path.join(out, "results.json"), JSON.stringify(results, null, 2) + "\n");
  let first = `VISUAL: skipped — ${reason}`;
  if (status !== "skipped") {
    const has = (s) => pairs.some((p) => p.status === s);
    first = `VISUAL: ${has("unscored") ? "unscored" : has("changed") ? "changed" : "same"}`;
  }
  const lines = [first, ...pairs.map((p) => `- ${p.path} ${p.width}: ${p.status}`
    + (p.why ? ` — ${p.why}` : "") + (p.crop ? ` — crop ${p.crop}` : ""))];
  fs.writeFileSync(path.join(path.dirname(out), "visual-diff.md"), lines.join("\n") + "\n");
}

function loadDeps(projectDir) {
  const req = createRequire(path.join(projectDir, "package.json"));
  const tryLoad = (name) => { try { return req(name); } catch { return null; } };
  const pw = tryLoad("playwright") || tryLoad("@playwright/test");
  if (!pw) return { missing: "playwright" };
  const odiff = tryLoad("odiff-bin");
  if (!odiff) return { missing: "odiff-bin" };
  const sharp = tryLoad("sharp");
  if (!sharp) return { missing: "sharp" };
  return { chromium: pw.chromium, compare: odiff.compare, sharp };
}

async function flat(sharp, buf) {
  const { channels } = await sharp(buf).stats();
  return channels.every((c) => c.min === c.max);
}

// One side's final screenshot as {buf, finalPath}, or {why} when it stayed an error, blank or still moving.
async function shoot(page, url, maskSelectors, sharp) {
  let why = "";
  for (let t = 0; t < TRIES; t++) {
    let resp;
    try {
      resp = await page.goto(url, { waitUntil: "load", timeout: 30000 });
    } catch (e) {
      why = `error: ${String(e.message || e).split("\n")[0]}`;
      continue;
    }
    if (resp && resp.status() >= 400) {
      why = `error: HTTP ${resp.status()}`;
      continue;
    }
    await page.waitForLoadState("networkidle", { timeout: 10000 }).catch(() => {});
    await page.evaluate(() => document.fonts.ready.then(() => true));
    await page.addStyleTag({ content: HIDE_CSS });
    const opts = { fullPage: true, animations: "disabled", caret: "hide",
      mask: maskSelectors.map((s) => page.locator(s)) };
    const a = await page.screenshot(opts);
    await page.waitForTimeout(500);
    const b = await page.screenshot(opts);
    if (!a.equals(b)) { why = "still moving"; continue; }
    if (await flat(sharp, b)) { why = "blank"; continue; }
    return { buf: b, finalPath: new URL(page.url()).pathname };
  }
  return { why };
}

async function sideBySide(sharp, basePng, headPng, box, dest) {
  const crop = async (png) => {
    const m = await sharp(png).metadata();
    const left = Math.min(box.left, m.width - 1), top = Math.min(box.top, m.height - 1);
    const width = Math.max(1, Math.min(box.width, m.width - left)), height = Math.max(1, Math.min(box.height, m.height - top));
    return { buf: await sharp(png).extract({ left, top, width, height }).png().toBuffer(), width, height };
  };
  const l = await crop(basePng), r = await crop(headPng);
  const gap = 8;
  await sharp({ create: { width: l.width + gap + r.width, height: Math.max(l.height, r.height), channels: 4,
    background: { r: 255, g: 0, b: 255, alpha: 1 } } })
    .composite([{ input: l.buf, left: 0, top: 0 }, { input: r.buf, left: l.width + gap, top: 0 }])
    .png().toFile(dest);
}

// The padded diff box, capped at MAX_CROP_H tall; `truncated` when the cap cut part of the change off.
function boundingBox(res, w, h) {
  if (!res.diffLines?.length || !res.diffCols?.length) {
    return { left: 0, top: 0, width: w, height: Math.min(h, MAX_CROP_H), truncated: h > MAX_CROP_H };
  }
  const top = Math.max(0, res.diffLines[0] - PAD), bottom = Math.min(h, res.diffLines.at(-1) + 1 + PAD);
  const left = Math.max(0, res.diffCols[0] - PAD), right = Math.min(w, res.diffCols.at(-1) + 1 + PAD);
  return { left, top, width: right - left, height: Math.min(bottom - top, MAX_CROP_H),
    truncated: bottom - top > MAX_CROP_H };
}

async function run(opts, deps) {
  const out = path.resolve(opts.out);
  const shots = path.join(out, "shots");
  fs.mkdirSync(shots, { recursive: true });
  const masks = (opts.mask || "").split(",").map((s) => s.trim()).filter(Boolean);
  const browser = await deps.chromium.launch();
  const pairs = [];
  let changed = 0;
  try {
    const context = await browser.newContext(opts.storageState ? { storageState: opts.storageState } : {});
    const page = await context.newPage();
    for (const p of opts.paths) {
      for (const width of WIDTHS) {
        await page.setViewportSize({ width, height: 900 });
        const want = new URL(p, opts.head).pathname;
        const pair = { path: p, width, status: "unscored", why: null, diff_pixels: null, crop: null };
        pairs.push(pair);
        const base = await shoot(page, new URL(p, opts.base).href, masks, deps.sharp);
        const head = await shoot(page, new URL(p, opts.head).href, masks, deps.sharp);
        if (base.why || head.why) {
          pair.why = [base.why && `base ${base.why}`, head.why && `head ${head.why}`].filter(Boolean).join("; ");
          continue;
        }
        const moved = [["base", base], ["head", head]].find(([, s]) => s.finalPath !== want);
        if (moved) {
          pair.why = `${moved[0]} redirected to ${moved[1].finalPath}`;
          continue;
        }
        const stem = path.join(shots, `${slug(p)}-${width}`);
        fs.writeFileSync(`${stem}-base.png`, base.buf);
        fs.writeFileSync(`${stem}-head.png`, head.buf);
        const res = await deps.compare(`${stem}-base.png`, `${stem}-head.png`, `${stem}-diff.png`,
          { threshold: THRESHOLD, antialiasing: true, captureDiffLines: true, captureDiffCols: true });
        if (res.match || (res.reason === "pixel-diff" && res.diffCount < MIN_DIFF_PIXELS)) {
          pair.status = "same";
          pair.diff_pixels = res.diffCount ?? 0;
          continue;
        }
        if (res.reason !== "pixel-diff" && res.reason !== "layout-diff") {
          pair.why = `odiff ${res.reason}`;
          continue;
        }
        pair.status = "changed";
        pair.diff_pixels = res.diffCount ?? null;
        if (res.reason === "layout-diff") pair.why = "layout-diff";
        if (++changed > PAIR_CAP) {
          pair.why = pair.why ? `${pair.why} — over cap` : "over cap";
          continue;
        }
        const m = await deps.sharp(base.buf).metadata();
        const tallest = Math.max(m.height, (await deps.sharp(head.buf).metadata()).height);
        const box = res.reason === "layout-diff"
          ? { left: 0, top: 0, width: 100000, height: MAX_CROP_H, truncated: tallest > MAX_CROP_H }
          : boundingBox(res, m.width, m.height);
        // A cut-off crop never stands in for the page: reviewers render a `crop truncated` pair themselves.
        if (box.truncated) pair.why = pair.why ? `${pair.why} — crop truncated` : "crop truncated";
        pair.crop = path.join(out, `${slug(p)}-${width}.png`);
        await sideBySide(deps.sharp, base.buf, head.buf, box, pair.crop);
      }
    }
  } finally {
    await browser.close();
  }
  writeOutputs(out, "ok", pairs);
}

const opts = parseArgs(process.argv.slice(2));
if (!opts) {
  console.error(USAGE);
  process.exit(2);
}
try {
  const deps = loadDeps(path.resolve(opts.projectDir));
  if (deps.missing) {
    writeOutputs(path.resolve(opts.out), "skipped", [], `${deps.missing} not installed in ${opts.projectDir}`);
  } else {
    await run(opts, deps);
  }
} catch (e) {
  console.error(e && e.stack ? e.stack : String(e));
  process.exit(1);
}
