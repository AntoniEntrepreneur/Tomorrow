const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const { after, before } = require("node:test");
const { chromium } = require("playwright");

const DEFAULT_STATIC_ROOT = path.resolve(__dirname, "../../tomorrow/static");

function createStaticServer(staticRoot = DEFAULT_STATIC_ROOT) {
  return http.createServer((request, response) => {
    const urlPath = new URL(request.url, "http://localhost").pathname;
    const file = urlPath === "/" ? "session.html" : path.basename(urlPath);
    const filePath = path.join(staticRoot, file);
    if (!filePath.startsWith(staticRoot) || !fs.existsSync(filePath)) {
      response.writeHead(404).end();
      return;
    }
    response.setHeader("Content-Type", file.endsWith(".js") ? "text/javascript" : "text/html");
    response.end(fs.readFileSync(filePath));
  });
}

async function startServer(staticRoot = DEFAULT_STATIC_ROOT) {
  const server = createStaticServer(staticRoot);
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  const baseUrl = `http://127.0.0.1:${port}`;
  return { server, port, baseUrl };
}

async function stopServer(server) {
  if (server) {
    await new Promise(resolve => server.close(resolve));
  }
}

async function launchBrowser(options = {}) {
  return await chromium.launch({ headless: true, ...options });
}

function sessionView() {
  return {
    plan_date: "2026-10-20",
    plan_date_label: "Tuesday, October 20",
    bounds: { wake: "07:00", sleep: "02:00", sleep_is_next_day: true },
    template_offer: "declined",
    show_template_offer: false,
    drafts: [{ id: "draft-1", name: "Therapy 8:30", stripped_name: "Therapy", suggested_start: "08:30", suggested_duration_minutes: 45, default_kind: "anchor" }],
    anchors: [{ id: "anchor-1", name: "Late work", start: "23:00", duration_minutes: 60, checklist: "prep", checklist_items: [], checklist_kind: "reference" }, { id: "anchor-2", name: "Early walk", start: "00:30", duration_minutes: 30, checklist: null }],
    flexes: [],
    todos: [],
    gaps: [],
    blockers: [],
    can_undo: false,
    can_redo: false,
    checklists: [{ id: "prep", name: "Prep", items: ["Keys"] }],
    weather_name: null,
    weather_one_liner: null
  };
}

function createTempDir(prefix = "tomorrow-test-") {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

function cleanupTempDir(dir) {
  if (dir && fs.existsSync(dir)) {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

function setupBrowserTest() {
  const env = {
    server: null,
    baseUrl: null,
    browser: null,
  };

  before(async () => {
    const started = await startServer();
    env.server = started.server;
    env.baseUrl = started.baseUrl;
    env.browser = await launchBrowser();
  });

  after(async () => {
    if (env.browser) {
      await env.browser.close();
    }
    if (env.server) {
      await stopServer(env.server);
    }
  });

  return env;
}

module.exports = {
  createStaticServer,
  startServer,
  stopServer,
  launchBrowser,
  sessionView,
  createTempDir,
  cleanupTempDir,
  setupBrowserTest,
};
