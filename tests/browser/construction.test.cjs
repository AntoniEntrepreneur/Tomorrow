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
    if (request.method() === "POST" && url.pathname === "/api/suggest-activity") {
      await route.fulfill({ json: { suggestion: null } });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/undo") {
      current = { ...current, can_undo: false, can_redo: true };
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

test("Day Template mode follows daily plan timeline conventions, displays daily activities, and supports arm-and-click placement", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const requests = [];
  await page.route("**/api/template*", async route => {
    const request = route.request();
    requests.push({ method: request.method(), body: request.postDataJSON() || {} });
    if (request.method() === "GET") {
      await route.fulfill({
        json: {
          template_id: "friday",
          name: "Friday",
          weekday: "friday",
          bounds: { wake: "07:00", sleep: "23:00" },
          anchors: [{ name: "Afternoon Class", start: "14:00", duration: 90 }],
          flexes: [{ name: "Reading", duration: 45 }],
          daily_activities: [{ id: "morning-routine", name: "Morning Routine", duration_minutes: 60, checklist: null, daily: true }],
          checklists: [],
          activity_templates: []
        }
      });
      return;
    }
    await route.fulfill({ json: { ok: true, template_id: "friday" } });
  });

  await page.goto(`${baseUrl}/?template=friday`);
  await page.locator("#template-editor").waitFor();

  // Stamps: Anchor and Flex visible, Draft and To-do hidden
  assert.equal(await page.locator("#stamp-anchor").isVisible(), true);
  assert.equal(await page.locator("#stamp-flex").isVisible(), true);
  assert.equal(await page.locator("#stamp-draft").isVisible(), false);
  assert.equal(await page.locator("#stamp-todo").isVisible(), false);

  // Timeline rail has gap before 14:00
  const firstGap = page.locator('[data-template-gap="true"][data-start="07:00"]');
  await firstGap.waitFor();
  assert.equal(await firstGap.locator(".time-tag").textContent(), "07:00");
  assert.equal(await page.locator('[data-template-entry="anchor"] .block-title').textContent(), "Afternoon Class");

  // Tray has both flex and daily activity with daily badge
  const dailyChip = page.locator('[data-template-chip="true"][data-source="daily"]');
  await dailyChip.waitFor();
  assert.match(await dailyChip.locator(".name").innerText(), /Morning Routine.*🔁 daily/);

  // Arm daily activity and place into gap at 07:00
  await dailyChip.locator('[data-template-action="place"]').click();
  assert.equal(await dailyChip.evaluate(el => el.classList.contains("armed")), true);
  await firstGap.click();

  // Morning routine is now an anchor on the rail at 07:00
  const morningAnchor = page.locator('[data-template-entry="activity"]');
  await morningAnchor.waitFor();
  assert.equal(await morningAnchor.locator(".time-tag").textContent(), "07:00");
  assert.match(await morningAnchor.locator(".block-title").innerText(), /Morning Routine.*🔁 daily/);

  // Make Flex conversion: click Afternoon Class, demote it to flex
  await page.locator('[data-template-entry="anchor"]').click();
  await page.locator("#sheet h2").waitFor();
  await page.locator("#template-make-flex").click();

  // Afternoon Class is now in the tray
  await page.locator('[data-template-chip="true"] .name:has-text("Afternoon Class")').waitFor();

  // Save template and verify payload
  const saveRequest = page.waitForRequest(request => request.url().endsWith("/api/template"));
  await page.locator('#template-editor button[type="submit"]').click();
  const saved = await saveRequest;
  const body = saved.postDataJSON();
  assert.equal(body.anchors.some(a => a.activity === "morning-routine" && a.start === "07:00"), true);
  assert.equal(body.flexes.some(f => f.name === "Afternoon Class"), true);

  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Draft Edit applies Activity Template suggestions and keyboard undo", async () => {
  const page = await browser.newPage();
  let current = sessionView();
  current.can_undo = true;
  current.drafts = [{ id: "draft-gym", name: "Gym" }];
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
    if (request.method() === "POST" && url.pathname === "/api/suggest-activity") {
      assert.equal(body.name, "Gym");
      await route.fulfill({
        json: {
          suggestion: {
            kind: "activity",
            activity_id: "gym",
            name: "Gym",
            start: "18:00",
            duration_minutes: 60,
            checklist: "prep"
          }
        }
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/undo") {
      current = { ...current, can_undo: false, can_redo: true };
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.getByText("Late work", { exact: true }).waitFor();
  const undoRequest = page.waitForRequest(request => request.url().endsWith("/api/undo"));
  await page.keyboard.press("Control+z");
  await undoRequest;
  assert.equal(await page.locator("#stamp-draft").isEnabled(), true);
  assert.equal(requests.some(item => item.path === "/api/undo"), true);

  await page.locator("#stamp-draft").click();
  await page.locator("#add-draft").waitFor();
  await page.locator("#add-draft [data-close]").click();
  await page.locator('[data-promote="draft-gym"]').click();
  await page.waitForFunction(() => document.querySelector('#promote-draft input[name="start"]')?.value === "18:00");
  assert.equal(await page.locator('#promote-draft input[name="duration_minutes"]').inputValue(), "60");
  assert.equal(await page.locator('#promote-draft select[name="checklist"]').inputValue(), "prep");
  assert.equal(requests.some(item => item.path === "/api/suggest-activity"), true);
  await page.close();
});

test("Promoting or changing activity shape only displays fields relevant to that type", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const current = sessionView();

  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/session") {
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "GET" && url.pathname.startsWith("/api/template")) {
      await route.fulfill({
        json: {
          template_id: "test",
          name: "Test Template",
          weekday: "Monday",
          bounds: { wake: "07:00", sleep: "22:00" },
          anchors: [
            { activity: "act-1", shape: "flex", duration: 45 }
          ],
          flexes: [],
          checklists: [],
          activity_templates: [
            { id: "act-1", name: "Exercise", is_anchor_shaped: false, duration_minutes: 45 }
          ]
        }
      });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.getByText("Therapy 8:30").waitFor();
  await page.locator('[data-promote="draft-1"]').click();
  await page.locator("#promote-draft").waitFor();

  // Initially Anchor: start, duration, and end should be visible
  assert.equal(await page.locator("#promote-start-label").isVisible(), true);
  assert.equal(await page.locator("#duration-label").isVisible(), true);
  assert.equal(await page.locator("#end-label").isVisible(), true);

  // Switch to Flex: start and end should NOT be visible, only duration
  await page.locator('#promote-draft select[name="kind"]').selectOption("flex");
  assert.equal(await page.locator("#promote-start-label").isVisible(), false);
  assert.equal(await page.locator("#end-label").isVisible(), false);
  assert.equal(await page.locator("#duration-label").isVisible(), true);

  // Switch to To-do: neither timing nor duration should be visible
  await page.locator('#promote-draft select[name="kind"]').selectOption("todo");
  assert.equal(await page.locator("#promote-start-label").isVisible(), false);
  assert.equal(await page.locator("#end-label").isVisible(), false);
  assert.equal(await page.locator("#duration-label").isVisible(), false);
  assert.equal(await page.locator("#promote-todo-hint").isVisible(), true);

  // Switch back to Anchor: all three visible again
  await page.locator('#promote-draft select[name="kind"]').selectOption("anchor");
  assert.equal(await page.locator("#promote-start-label").isVisible(), true);
  assert.equal(await page.locator("#duration-label").isVisible(), true);
  assert.equal(await page.locator("#end-label").isVisible(), true);

  // Close sheet
  await page.locator("#promote-draft [data-close]").click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // Now test Day Template activity entry form
  await page.goto(`${baseUrl}/?template=test`);
  await page.locator("#template-editor").waitFor();
  await page.locator('[data-template-entry="activity"]').click();
  await page.locator("#template-activity-entry").waitFor();

  // Flex shape: start override and end override should NOT be visible
  assert.equal(await page.locator("#activity-start-label").isVisible(), false);
  assert.equal(await page.locator("#activity-end-label").isVisible(), false);
  assert.equal(await page.locator("#activity-duration-label").isVisible(), true);

  // Switch shape to Anchor: start override and end override should be visible
  await page.locator('#template-activity-entry select[name="shape"]').selectOption("anchor");
  assert.equal(await page.locator("#activity-start-label").isVisible(), true);
  assert.equal(await page.locator("#activity-end-label").isVisible(), true);
  assert.equal(await page.locator("#activity-duration-label").isVisible(), true);

  // Switch shape back to Flex: start and end override should be hidden again
  await page.locator('#template-activity-entry select[name="shape"]').selectOption("flex");
  assert.equal(await page.locator("#activity-start-label").isVisible(), false);
  assert.equal(await page.locator("#activity-end-label").isVisible(), false);
  assert.equal(await page.locator("#activity-duration-label").isVisible(), true);

  // Switch to Anchor again, then test resetting shape
  await page.locator('#template-activity-entry select[name="shape"]').selectOption("anchor");
  assert.equal(await page.locator("#activity-start-label").isVisible(), true);
  await page.locator('#template-activity-entry button[data-reset-field="shape"]').click();
  assert.equal(await page.locator('#template-activity-entry select[name="shape"]').inputValue(), "flex");
  assert.equal(await page.locator("#activity-start-label").isVisible(), false);
  assert.equal(await page.locator("#activity-end-label").isVisible(), false);

  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Gap split-half placement dispatches place request at start or wake-relative end with midnight wrap and exact fit", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const requests = [];
  let current = {
    ...sessionView(),
    bounds: { wake: "07:00", sleep: "02:00", sleep_is_next_day: true },
    anchors: [
      { id: "anchor-1", name: "Morning Standup", start: "09:00", duration_minutes: 60, checklist: null },
      { id: "anchor-2", name: "Late Walk", start: "00:30", duration_minutes: 30, checklist: null }
    ],
    flexes: [
      { id: "flex-1", name: "Deep Work", duration_minutes: 60, start: null },
      { id: "flex-fit", name: "Exact Two Hours", duration_minutes: 120, start: null }
    ]
  };

  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postDataJSON() || {};
    if (request.method() === "GET" && url.pathname === "/api/session") {
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/place") {
      requests.push({ path: url.pathname, body });
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.getByText("Morning Standup", { exact: true }).waitFor();

  // Gap 1 is 07:00 to 09:00 (120 min)
  // Gap 2 is 10:00 to 00:30 (crosses midnight, ends at 00:30, duration 870 min)
  const morningGap = page.locator('[data-kind="gap"][data-start="07:00"]');
  const midnightGap = page.locator('[data-kind="gap"][data-start="10:00"]');
  await morningGap.waitFor();
  await midnightGap.waitFor();

  // 1. Click upper half (< 50% height) with armed flex -> start equals gap.start ("07:00")
  await page.locator('[data-arm="flex-1"] .name').click();
  assert.equal(await page.locator('[data-arm="flex-1"]').evaluate(el => el.classList.contains("armed")), true);
  const morningBox = await morningGap.boundingBox();
  const placeReq1 = page.waitForRequest(req => req.url().endsWith("/api/place"));
  await morningGap.click({ position: { x: morningBox.width / 2, y: morningBox.height * 0.25 } });
  const req1 = await placeReq1;
  assert.deepEqual(req1.postDataJSON(), { id: "flex-1", start: "07:00" });

  // 2. Click lower half (>= 50% height) with armed flex across midnight -> flush against gap.end (00:30 - 60 min = 23:30)
  await page.locator('[data-arm="flex-1"] .name').click();
  assert.equal(await page.locator('[data-arm="flex-1"]').evaluate(el => el.classList.contains("armed")), true);
  const midnightBox = await midnightGap.boundingBox();
  const placeReq2 = page.waitForRequest(req => req.url().endsWith("/api/place"));
  await midnightGap.click({ position: { x: midnightBox.width / 2, y: midnightBox.height * 0.75 } });
  const req2 = await placeReq2;
  assert.deepEqual(req2.postDataJSON(), { id: "flex-1", start: "23:30" });

  // 3. Exact fit (flex.duration == gap.duration, 120 min) places identically at gap.start
  // Test lower half on morningGap (07:00 to 09:00, 120 min, flex-fit is 120 min -> 09:00 - 120 min = 07:00)
  await page.locator('[data-arm="flex-fit"] .name').click();
  assert.equal(await page.locator('[data-arm="flex-fit"]').evaluate(el => el.classList.contains("armed")), true);
  const placeReq3 = page.waitForRequest(req => req.url().endsWith("/api/place"));
  await morningGap.click({ position: { x: morningBox.width / 2, y: morningBox.height * 0.75 } });
  const req3 = await placeReq3;
  assert.deepEqual(req3.postDataJSON(), { id: "flex-fit", start: "07:00" });

  // Test upper half on morningGap with flex-fit
  await page.locator('[data-arm="flex-fit"] .name').click();
  assert.equal(await page.locator('[data-arm="flex-fit"]').evaluate(el => el.classList.contains("armed")), true);
  const placeReq4 = page.waitForRequest(req => req.url().endsWith("/api/place"));
  await morningGap.click({ position: { x: morningBox.width / 2, y: morningBox.height * 0.25 } });
  const req4 = await placeReq4;
  assert.deepEqual(req4.postDataJSON(), { id: "flex-fit", start: "07:00" });

  assert.deepEqual(pageErrors, []);
  await page.close();
});
