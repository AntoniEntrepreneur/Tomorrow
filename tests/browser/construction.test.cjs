const assert = require("node:assert/strict");
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const { after, before, test } = require("node:test");
const { chromium } = require("playwright");

const staticRoot = path.resolve(__dirname, "../../tomorrow/static");
let server;
let baseUrl;
let browser;

before(async () => {
  server = http.createServer((request, response) => {
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
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  baseUrl = `http://127.0.0.1:${server.address().port}`;
  browser = await chromium.launch({ headless: true });
});

after(async () => {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
});

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

test("Session interactions render wake-relative time, preserve checklist edits, and promote Draft suggestions over HTTP", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  let current = sessionView();
  const requests = [];
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postDataJSON() || {};
    requests.push({ path: url.pathname, body });
    if (request.method() === "GET" && url.pathname === "/api/session") {
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/promote") {
      assert.equal(body.kind, "anchor");
      assert.equal(body.start, "08:30");
      assert.equal(body.name, "Therapy");
      current = { ...current, drafts: [], anchors: [...current.anchors, { id: "promoted", name: body.name, start: body.start, duration_minutes: body.duration_minutes }] };
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/edit") {
      current = { ...current, anchors: current.anchors.map(item => item.id === body.id ? { ...item, checklist_items: body.checklist_items, checklist: null } : item) };
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.getByText("Late work", { exact: true }).waitFor();
  assert.equal(await page.locator('[data-id="anchor-2"] .time-tag').textContent(), "00:30 +1");
  assert.equal(await page.locator("#sleep-cap").textContent(), "02:00 +1 sleep ↓");

  await page.locator('[data-id="anchor-1"]').click();
  await page.locator('#edit-anchor textarea[name="checklist_items"]').fill("Keys\nWallet");
  const editRequest = page.waitForRequest(request => request.url().endsWith("/api/edit"));
  await page.locator('#edit-anchor button[type="submit"]').click();
  const edited = await editRequest;
  assert.deepEqual(edited.postDataJSON().checklist_items, ["Keys", "Wallet"]);
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  const draftEdit = page.locator('[data-promote="draft-1"]');
  assert.equal(await draftEdit.textContent(), "Edit");
  await draftEdit.click();
  assert.equal(await page.locator("#sheet h2").textContent(), "Edit Draft · Therapy 8:30");
  assert.equal(await page.locator('#promote-draft input[name="start"]').inputValue(), "08:30");
  const promoteRequest = page.waitForRequest(request => request.url().endsWith("/api/promote"));
  await page.locator('#promote-draft button[type="submit"]').click();
  await promoteRequest;
  await page.locator("#drafts .draft-chip").waitFor({ state: "detached" });
  assert.equal(await page.locator("#drafts").innerText(), "");
  assert.equal(requests.some(item => item.path === "/api/promote"), true);
  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Day Template mode loads and saves through its HTTP endpoint", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const requests = [];
  await page.route("**/api/template*", async route => {
    const request = route.request();
    requests.push({ method: request.method(), body: request.postDataJSON() || {} });
    if (request.method() === "GET") {
      await route.fulfill({ json: { template_id: "new", name: "Weekday", weekday: "Tuesday", bounds: { wake: "07:00", sleep: "22:00" }, anchors: [], flexes: [], checklists: [], activity_templates: [] } });
      return;
    }
    await route.fulfill({ json: { template_id: "weekday", name: "Weekday", weekday: "Tuesday", bounds: { wake: "07:00", sleep: "22:00" }, anchors: [], flexes: [], checklists: [], activity_templates: [] } });
  });
  await page.goto(`${baseUrl}/?template=new`);
  await page.locator("#template-editor").waitFor();
  assert.equal(await page.locator(".kicker").textContent(), "Day Template");
  await page.locator('#template-editor input[name="name"]').fill("Weekday plan");
  const saveRequest = page.waitForRequest(request => request.url().endsWith("/api/template"));
  await page.locator('#template-editor button[type="submit"]').click();
  const saved = await saveRequest;
  assert.equal(saved.postDataJSON().name, "Weekday plan");
  assert.deepEqual(pageErrors, []);
  assert.equal(requests.at(-1).body.name, "Weekday plan");
  await page.close();
});
