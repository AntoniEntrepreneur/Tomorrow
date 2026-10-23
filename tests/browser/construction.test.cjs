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
  page.on("console", msg => console.log("PAGE LOG:", msg.text()));
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
  await page.locator('#edit-activity textarea[name="checklist_items"]').fill("Keys\nWallet");
  const editRequest = page.waitForRequest(request => request.url().endsWith("/api/edit"));
  await page.locator('#edit-activity button[type="submit"]').click();
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
  page.on("console", msg => console.log("PAGE LOG:", msg.text()));
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
  page.on("console", msg => console.log("PAGE LOG:", msg.text()));
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
  page.on("console", msg => console.log("PAGE LOG:", msg.text()));
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

test("Clicking weather summary pill toggles hourly weather drawer", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  let current = {
    ...sessionView(),
    weather: {
      location_name: "Warsaw",
      low_c: 12,
      high_c: 20,
      weather_code: 61,
      condition: "rain",
      emoji: "🌧️",
      summary: "Warsaw · 12° / 20° · 🌧️ rain",
      hourly: [
        {
          hour: "07:00",
          temperature_c: 13,
          weather_code: 61,
          condition: "rain",
          emoji: "🌧️",
          precipitation_probability: 40,
        },
        {
          hour: "08:00",
          temperature_c: 14,
          weather_code: 2,
          condition: "partly cloudy",
          emoji: "⛅",
          precipitation_probability: 0,
        },
      ],
    },
  };

  await page.route("**/api/session", async route => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(current),
    });
  });

  await page.goto(baseUrl, { waitUntil: "networkidle" });

  const weatherToggle = page.locator("#weather-toggle");
  await weatherToggle.waitFor();
  assert.equal(await weatherToggle.getAttribute("aria-expanded"), "false");

  const hourlyStrip = page.locator("#weather-hourly-strip");
  assert.equal(await hourlyStrip.isHidden(), true);

  // Click to expand drawer
  await weatherToggle.click();
  assert.equal(await weatherToggle.getAttribute("aria-expanded"), "true");
  assert.equal(await hourlyStrip.isVisible(), true);
  assert.equal(await page.locator(".weather-card").count(), 2);
  assert.equal(await page.locator(".card-hour").first().textContent(), "07:00");
  assert.equal(await page.locator(".card-temp").first().textContent(), "13°");
  assert.equal(await page.locator(".card-precip").first().textContent(), "💧 40%");

  // Click to collapse drawer
  await weatherToggle.click();
  assert.equal(await weatherToggle.getAttribute("aria-expanded"), "false");
  assert.equal(await hourlyStrip.isHidden(), true);

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

test("Fit validation displays in-app toast for oversized Flex and keeps Flex armed without placing", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  const requests = [];
  const flexName = "Gym Session";
  const flexDuration = 180; // 3h
  const gapDuration = 60; // 1h
  const current = {
    ...sessionView(),
    bounds: { wake: "07:00", sleep: "23:00", sleep_is_next_day: false },
    anchors: [
      { id: "anchor-1", name: "Morning Meeting", start: "08:00", duration_minutes: 60, checklist: null }
    ],
    flexes: [
      { id: "flex-oversized", name: flexName, duration_minutes: flexDuration, start: null }
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
  await page.getByText("Morning Meeting", { exact: true }).waitFor();

  // Gap is 07:00 to 08:00 (60m)
  const smallGap = page.locator('[data-kind="gap"][data-start="07:00"]');
  await smallGap.waitFor();

  // Arm the oversized Flex (180m)
  const flexChip = page.locator('[data-arm="flex-oversized"]');
  await flexChip.locator(".name").click();
  assert.equal(await flexChip.evaluate(el => el.classList.contains("armed")), true);

  const toast = page.locator("#toast");

  // 1. Click upper half of gap: should NOT dispatch POST /api/place, should show toast, and Flex remains armed
  const gapBox = await smallGap.boundingBox();
  await smallGap.click({ position: { x: gapBox.width / 2, y: gapBox.height * 0.25 } });

  assert.equal(requests.filter(r => r.path === "/api/place").length, 0);
  assert.equal(await flexChip.evaluate(el => el.classList.contains("armed")), true);
  await toast.waitFor({ state: "visible" });
  assert.equal(await toast.textContent(), "Gym Session (3h) does not fit in this gap (1h)");

  // 2. Test toast dismiss on click
  await toast.click();
  await toast.waitFor({ state: "hidden" });
  assert.equal(await toast.isVisible(), false);
  // Flex remains armed after dismiss
  assert.equal(await flexChip.evaluate(el => el.classList.contains("armed")), true);

  // 3. Click lower half of gap: should also NOT dispatch POST /api/place, should show toast, and Flex remains armed
  await smallGap.click({ position: { x: gapBox.width / 2, y: gapBox.height * 0.75 } });
  assert.equal(requests.filter(r => r.path === "/api/place").length, 0);
  assert.equal(await flexChip.evaluate(el => el.classList.contains("armed")), true);
  await toast.waitFor({ state: "visible" });
  assert.equal(await toast.textContent(), "Gym Session (3h) does not fit in this gap (1h)");

  // 4. Test toast auto-dismiss after timeout (~3s)
  await toast.waitFor({ state: "hidden", timeout: 4500 });
  assert.equal(await toast.isVisible(), false);
  assert.equal(await flexChip.evaluate(el => el.classList.contains("armed")), true);
  assert.equal(requests.filter(r => r.path === "/api/place").length, 0);

  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Armed Gap hover indicators and dynamic CTA text toggle between start, end, and reset on mouseleave", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  let current = {
    ...sessionView(),
    bounds: { wake: "07:00", sleep: "02:00", sleep_is_next_day: true },
    anchors: [
      { id: "anchor-1", name: "Morning Standup", start: "09:00", duration_minutes: 60, checklist: null }
    ],
    flexes: [
      { id: "flex-1", name: "Deep Work", duration_minutes: 60, start: null }
    ]
  };

  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/session") {
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.getByText("Morning Standup", { exact: true }).waitFor();

  const morningGap = page.locator('[data-kind="gap"][data-start="07:00"]');
  const morningCta = morningGap.locator(".cta");
  await morningGap.waitFor();
  const morningBox = await morningGap.boundingBox();

  // 1. Unarmed state: hovering over upper or lower half does NOT apply hover-start/hover-end and retains "Place Flex"
  assert.equal(await morningCta.textContent(), "Place Flex");
  await morningGap.hover({ position: { x: morningBox.width / 2, y: morningBox.height * 0.25 } });
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-start")), false);
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-end")), false);
  assert.equal(await morningCta.textContent(), "Place Flex");

  await morningGap.hover({ position: { x: morningBox.width / 2, y: morningBox.height * 0.75 } });
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-start")), false);
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-end")), false);
  assert.equal(await morningCta.textContent(), "Place Flex");

  await page.mouse.move(0, 0);

  // 2. Arm flex-1
  await page.locator('[data-arm="flex-1"] .name').click();
  assert.equal(await page.locator('[data-arm="flex-1"]').evaluate(el => el.classList.contains("armed")), true);
  assert.equal(await morningCta.textContent(), "Place here");

  // 3. Hover upper half (< 50% height) with armed flex -> hover-start class and "Place at start" CTA
  await morningGap.hover({ position: { x: morningBox.width / 2, y: morningBox.height * 0.25 } });
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-start")), true);
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-end")), false);
  assert.equal(await morningCta.textContent(), "Place at start");

  // 4. Hover lower half (>= 50% height) with armed flex -> hover-end class and "Place at end" CTA
  await morningGap.hover({ position: { x: morningBox.width / 2, y: morningBox.height * 0.75 } });
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-start")), false);
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-end")), true);
  assert.equal(await morningCta.textContent(), "Place at end");

  // 5. Mouseleave removes hover styling and reverts CTA to "Place here"
  await page.mouse.move(0, 0);
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-start")), false);
  assert.equal(await morningGap.evaluate(el => el.classList.contains("hover-end")), false);
  assert.equal(await morningCta.textContent(), "Place here");

  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Place into this Gap sheet offers At start and At end actions and prioritizes based on clicked half", async () => {
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
      { id: "flex-2", name: "Short Break", duration_minutes: 30, start: null }
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

  const morningGap = page.locator('[data-kind="gap"][data-start="07:00"]');
  const midnightGap = page.locator('[data-kind="gap"][data-start="10:00"]');
  await morningGap.waitFor();
  await midnightGap.waitFor();

  // Ensure flex is not armed
  assert.equal(await page.locator('.tray-card.armed').count(), 0);

  // 1. Click upper half (< 50% height) of unarmed Gap -> opens sheet with "At start" prioritized/pre-focused
  const morningBox = await morningGap.boundingBox();
  await morningGap.click({ position: { x: morningBox.width / 2, y: morningBox.height * 0.25 } });

  const sheet = page.locator("#sheet");
  await sheet.waitFor();
  assert.equal(await page.locator("#sheet h2").textContent(), "Place into this Gap");

  // Verify both "At start" and "At end" action buttons exist for flex-1
  const startBtn1 = page.locator('#sheet [data-place-at="flex-1"][data-placement="start"]');
  const endBtn1 = page.locator('#sheet [data-place-at="flex-1"][data-placement="end"]');
  await startBtn1.waitFor();
  await endBtn1.waitFor();

  assert.equal(await startBtn1.textContent(), "At start");
  assert.equal(await endBtn1.textContent(), "At end");

  // "At start" should be prioritized: styled as primary and pre-focused
  assert.equal(await startBtn1.evaluate(el => el.classList.contains("primary")), true);
  assert.equal(await endBtn1.evaluate(el => el.classList.contains("ghost")), true);
  assert.equal(await startBtn1.evaluate(el => document.activeElement === el), true);

  // Clicking "At start" dispatches POST /api/place with gap.start ("07:00")
  const placeReq1 = page.waitForRequest(req => req.url().endsWith("/api/place"));
  await startBtn1.click();
  const req1 = await placeReq1;
  assert.deepEqual(req1.postDataJSON(), { id: "flex-1", start: "07:00" });

  // 2. Click lower half (>= 50% height) of unarmed Gap -> opens sheet with "At end" prioritized/pre-focused
  await morningGap.click({ position: { x: morningBox.width / 2, y: morningBox.height * 0.75 } });
  await sheet.waitFor();

  const startBtn2 = page.locator('#sheet [data-place-at="flex-1"][data-placement="start"]');
  const endBtn2 = page.locator('#sheet [data-place-at="flex-1"][data-placement="end"]');
  await startBtn2.waitFor();
  await endBtn2.waitFor();

  // "At end" should be prioritized: styled as primary and pre-focused
  assert.equal(await endBtn2.evaluate(el => el.classList.contains("primary")), true);
  assert.equal(await startBtn2.evaluate(el => el.classList.contains("ghost")), true);
  assert.equal(await endBtn2.evaluate(el => document.activeElement === el), true);

  // Clicking "At end" dispatches POST /api/place with flush time: gap.end (09:00) - flex.duration (60m) = "08:00"
  const placeReq2 = page.waitForRequest(req => req.url().endsWith("/api/place"));
  await endBtn2.click();
  const req2 = await placeReq2;
  assert.deepEqual(req2.postDataJSON(), { id: "flex-1", start: "08:00" });

  // 3. Lower half click on midnightGap (crosses midnight: 10:00 to 00:30, flex-1 duration 60m -> 23:30)
  const midnightBox = await midnightGap.boundingBox();
  await midnightGap.click({ position: { x: midnightBox.width / 2, y: midnightBox.height * 0.75 } });
  await sheet.waitFor();

  const midnightEndBtn = page.locator('#sheet [data-place-at="flex-1"][data-placement="end"]');
  await midnightEndBtn.waitFor();
  assert.equal(await midnightEndBtn.evaluate(el => el.classList.contains("primary")), true);
  assert.equal(await midnightEndBtn.evaluate(el => document.activeElement === el), true);

  const placeReq3 = page.waitForRequest(req => req.url().endsWith("/api/place"));
  await midnightEndBtn.click();
  const req3 = await placeReq3;
  assert.deepEqual(req3.postDataJSON(), { id: "flex-1", start: "23:30" });

  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Unified activity edit modal displays Type selector, toggles fields dynamically, pre-populates defaults/template, cleans action buttons, and submits to /api/edit", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));

  let current = {
    plan_date: "2026-10-20",
    plan_date_label: "Tuesday, October 20",
    bounds: { wake: "07:00", sleep: "22:00", sleep_is_next_day: false },
    template_offer: "declined",
    show_template_offer: false,
    drafts: [],
    anchors: [
      {
        id: "anchor-1",
        name: "Dentist",
        start: "10:00",
        duration_minutes: 45,
        checklist: "prep",
        checklist_items: ["X-Ray"],
        checklist_kind: "literal"
      }
    ],
    flexes: [
      {
        id: "flex-1",
        name: "Read book",
        start: null,
        duration_minutes: 60,
        checklist: null,
        checklist_items: [],
        checklist_kind: "none"
      }
    ],
    todos: [
      {
        id: "todo-1",
        name: "Buy milk",
        note: "Oat milk please"
      },
      {
        id: "todo-2",
        name: "Workout",
        note: "Leg day"
      }
    ],
    gaps: [],
    blockers: [],
    can_undo: false,
    can_redo: false,
    checklists: [{ id: "prep", name: "Prep", items: ["Keys"] }],
    weather_name: null,
    weather_one_liner: null
  };

  const requests = [];
  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postDataJSON() || {};
    requests.push({ method: request.method(), path: url.pathname, body });

    if (request.method() === "GET" && url.pathname === "/api/session") {
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/suggest-activity") {
      if (body.name === "Workout") {
        await route.fulfill({
          json: {
            suggestion: {
              kind: "activity",
              activity_id: "act-workout",
              name: "Workout",
              duration_minutes: 50,
              start: "08:00",
              checklist: ""
            }
          }
        });
        return;
      }
      await route.fulfill({ json: { suggestion: null } });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/edit") {
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.getByText("Dentist").waitFor();

  // Verify tray buttons cleanup (no Make Flex, Make Anchor, Make To-do, Change Duration on chips)
  assert.equal(await page.locator('#tray button:has-text("Change Duration")').count(), 0);
  assert.equal(await page.locator('#tray button:has-text("Make To-do")').count(), 0);
  assert.equal(await page.locator('#tray [data-edit-flex="flex-1"]').isVisible(), true);
  assert.equal(await page.locator('#todos-tray button:has-text("Make Flex")').count(), 0);
  assert.equal(await page.locator('#todos-tray button:has-text("Make Anchor")').count(), 0);
  assert.equal(await page.locator('#todos-tray [data-edit-todo="todo-1"]').count() > 0, true);

  // 1. Open Anchor edit modal
  await page.locator('[data-id="anchor-1"]').click();
  await page.locator("#edit-activity").waitFor();

  // Check Type dropdown initialized to "anchor"
  assert.equal(await page.locator('#edit-activity select[name="kind"]').inputValue(), "anchor");

  // Check fields visibility for Anchor
  assert.equal(await page.locator('#edit-activity input[name="name"]').inputValue(), "Dentist");
  assert.equal(await page.locator("#edit-start-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity input[name="start"]').inputValue(), "10:00");
  assert.equal(await page.locator("#duration-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity input[name="duration_minutes"]').inputValue(), "45");
  assert.equal(await page.locator("#end-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity select[name="checklist"]').isVisible(), true);
  assert.equal(await page.locator('#edit-activity textarea[name="checklist_items"]').isVisible(), true);
  assert.equal(await page.locator("#edit-note-label").isVisible(), false);

  // Check Action buttons: strictly Update, Cancel, Drop, and Save to Library
  assert.equal(await page.locator('#edit-activity button[type="submit"]').textContent(), "Update");
  assert.equal(await page.locator('#edit-activity button[data-close]').textContent(), "Cancel");
  assert.equal(await page.locator('#edit-activity button.danger').textContent(), "Drop");
  assert.equal(await page.locator('#edit-activity button[data-promote-checklist]').isVisible(), true);
  // Redundant buttons must NOT exist in the modal
  assert.equal(await page.locator('#edit-activity button:has-text("Make Flex")').count(), 0);
  assert.equal(await page.locator('#edit-activity button:has-text("Make Anchor")').count(), 0);
  assert.equal(await page.locator('#edit-activity button:has-text("Make To-do")').count(), 0);
  assert.equal(await page.locator('#edit-activity button:has-text("Change Duration")').count(), 0);
  assert.equal(await page.locator('#edit-activity button:has-text("Place")').count(), 0);

  // Dynamically switch Type to Flex
  await page.locator('#edit-activity select[name="kind"]').selectOption("flex");
  assert.equal(await page.locator("#edit-start-label").isVisible(), false);
  assert.equal(await page.locator("#end-label").isVisible(), false);
  assert.equal(await page.locator("#duration-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity select[name="checklist"]').isVisible(), true);
  assert.equal(await page.locator('#edit-activity textarea[name="checklist_items"]').isVisible(), true);
  assert.equal(await page.locator("#edit-note-label").isVisible(), false);

  // Dynamically switch Type to To-do
  await page.locator('#edit-activity select[name="kind"]').selectOption("todo");
  assert.equal(await page.locator("#edit-start-label").isVisible(), false);
  assert.equal(await page.locator("#end-label").isVisible(), false);
  assert.equal(await page.locator("#duration-label").isVisible(), false);
  assert.equal(await page.locator('#edit-activity select[name="checklist"]').isVisible(), false);
  assert.equal(await page.locator('#edit-activity textarea[name="checklist_items"]').isVisible(), false);
  assert.equal(await page.locator("#edit-note-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity button[data-promote-checklist]').isVisible(), false);

  // Switch back to Anchor and submit
  await page.locator('#edit-activity select[name="kind"]').selectOption("anchor");
  assert.equal(await page.locator("#edit-start-label").isVisible(), true);
  assert.equal(await page.locator("#duration-label").isVisible(), true);
  assert.equal(await page.locator("#edit-note-label").isVisible(), false);

  const editAnchorReq = page.waitForRequest(req => req.url().endsWith("/api/edit"));
  await page.locator('#edit-activity button[type="submit"]').click();
  const anchorReq = await editAnchorReq;
  assert.deepEqual(anchorReq.postDataJSON(), {
    kind: "anchor",
    id: "anchor-1",
    name: "Dentist",
    start: "10:00",
    duration_minutes: 45,
    checklist: "prep",
    checklist_items: ["X-Ray"]
  });
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // 2. Open unplaced Flex edit modal
  await page.locator('[data-edit-flex="flex-1"]').click();
  await page.locator("#edit-activity").waitFor();

  assert.equal(await page.locator('#edit-activity select[name="kind"]').inputValue(), "flex");
  assert.equal(await page.locator("#edit-start-label").isVisible(), false);
  assert.equal(await page.locator("#duration-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity input[name="duration_minutes"]').inputValue(), "60");

  // Converting unplaced Flex to Anchor pre-fills start to 09:00 and keeps duration 60
  await page.locator('#edit-activity select[name="kind"]').selectOption("anchor");
  assert.equal(await page.locator("#edit-start-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity input[name="start"]').inputValue(), "09:00");
  assert.equal(await page.locator('#edit-activity input[name="duration_minutes"]').inputValue(), "60");

  await page.locator('#edit-activity button[data-close]').click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // 3. Open To-do without template ("Buy milk")
  await page.locator('[data-edit-todo="todo-1"]').first().click();
  await page.locator("#edit-activity").waitFor();

  assert.equal(await page.locator('#edit-activity select[name="kind"]').inputValue(), "todo");
  assert.equal(await page.locator("#edit-note-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity textarea[name="note"]').inputValue(), "Oat milk please");
  assert.equal(await page.locator("#duration-label").isVisible(), false);
  assert.equal(await page.locator("#edit-start-label").isVisible(), false);

  // Switch to Flex: pre-fills duration with 30m default
  await page.locator('#edit-activity select[name="kind"]').selectOption("flex");
  assert.equal(await page.locator("#duration-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity input[name="duration_minutes"]').inputValue(), "30");
  assert.equal(await page.locator("#edit-start-label").isVisible(), false);

  // Switch to Anchor: pre-fills start with 09:00 default
  await page.locator('#edit-activity select[name="kind"]').selectOption("anchor");
  assert.equal(await page.locator("#edit-start-label").isVisible(), true);
  assert.equal(await page.locator('#edit-activity input[name="start"]').inputValue(), "09:00");
  assert.equal(await page.locator('#edit-activity input[name="duration_minutes"]').inputValue(), "30");

  await page.locator('#edit-activity button[data-close]').click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // 4. Open To-do with matching template ("Workout")
  await page.locator('[data-edit-todo="todo-2"]').first().click();
  await page.locator("#edit-activity").waitFor();

  // Wait for suggestion prefetch to populate
  await page.waitForTimeout(100);

  // Switch to Flex: pre-fills template duration (50 min)
  await page.locator('#edit-activity select[name="kind"]').selectOption("flex");
  assert.equal(await page.locator('#edit-activity input[name="duration_minutes"]').inputValue(), "50");

  // Switch to Anchor: pre-fills template start (08:00) and duration (50 min)
  await page.locator('#edit-activity select[name="kind"]').selectOption("anchor");
  assert.equal(await page.locator('#edit-activity input[name="start"]').inputValue(), "08:00");
  assert.equal(await page.locator('#edit-activity input[name="duration_minutes"]').inputValue(), "50");

  // Submit conversion of To-do to Anchor via POST /api/edit
  const convertReq = page.waitForRequest(req => req.url().endsWith("/api/edit"));
  await page.locator('#edit-activity button[type="submit"]').click();
  const converted = await convertReq;
  assert.deepEqual(converted.postDataJSON(), {
    kind: "anchor",
    id: "todo-2",
    name: "Workout",
    start: "08:00",
    duration_minutes: 50,
    checklist: null,
    checklist_items: []
  });
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // 5. Test Drop action button in edit modal
  await page.locator('[data-edit-flex="flex-1"]').click();
  await page.locator("#edit-activity").waitFor();
  const dropReq = page.waitForRequest(req => req.url().endsWith("/api/edit"));
  await page.locator('#edit-activity button.danger').click();
  const dropped = await dropReq;
  assert.deepEqual(dropped.postDataJSON(), {
    kind: "flex",
    id: "flex-1",
    remove: true
  });
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Overdue draft chip renders .overdue-tag badge with warm amber color alongside iCloud tag", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));

  let current = {
    ...sessionView(),
    drafts: [
      {
        id: "draft-overdue",
        name: "Tax return",
        source: "icloud",
        overdue: true,
        note: "Send W2",
      },
      {
        id: "draft-today",
        name: "Doctor appointment",
        source: "icloud",
        overdue: false,
      },
      {
        id: "draft-manual",
        name: "Quick idea",
        overdue: false,
      },
    ],
  };

  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/session") {
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.locator("#drafts").waitFor();

  // Find the overdue draft chip
  const overdueChip = page.locator(".draft-chip", { hasText: "Tax return" });
  await overdueChip.waitFor();

  const overdueTag = overdueChip.locator(".overdue-tag");
  assert.equal(await overdueTag.textContent(), "Overdue");

  const icloudTag = overdueChip.locator(".icloud-tag");
  assert.equal(await icloudTag.textContent(), "📅 iCloud");

  // Verify computed color is amber rgb(224, 168, 74) (from var(--wick))
  const overdueColor = await overdueTag.evaluate(el => window.getComputedStyle(el).color);
  assert.equal(overdueColor, "rgb(224, 168, 74)");

  // Today iCloud draft should have .icloud-tag but NOT .overdue-tag
  const todayChip = page.locator(".draft-chip", { hasText: "Doctor appointment" });
  await todayChip.waitFor();
  assert.equal(await todayChip.locator(".icloud-tag").textContent(), "📅 iCloud");
  assert.equal(await todayChip.locator(".overdue-tag").count(), 0);

  // Manual draft should have neither
  const manualChip = page.locator(".draft-chip", { hasText: "Quick idea" });
  await manualChip.waitFor();
  assert.equal(await manualChip.locator(".icloud-tag").count(), 0);
  assert.equal(await manualChip.locator(".overdue-tag").count(), 0);

  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Overdue draft promotion to To-do, Anchor, and Flex produces clean items without .overdue-tag, and dropping removes chip", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));

  let current = {
    ...sessionView(),
    drafts: [
      {
        id: "draft-todo",
        name: "Tax return",
        source: "icloud",
        overdue: true,
        note: "Send W2 to accountant",
      },
      {
        id: "draft-anchor",
        name: "Dentist appointment",
        source: "icloud",
        overdue: true,
      },
      {
        id: "draft-flex",
        name: "Gym workout",
        source: "icloud",
        overdue: true,
      },
      {
        id: "draft-drop",
        name: "Old newsletter",
        source: "icloud",
        overdue: true,
      },
    ],
    anchors: [],
    flexes: [],
    todos: [],
  };

  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postDataJSON() || {};
    if (request.method() === "GET" && url.pathname === "/api/session") {
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/promote") {
      const draft = current.drafts.find(d => d.id === body.id);
      current = {
        ...current,
        drafts: current.drafts.filter(d => d.id !== body.id),
      };
      if (body.kind === "todo") {
        current.todos = [
          ...current.todos,
          { id: "todo-1", name: body.name, note: draft ? draft.note : "" },
        ];
      } else if (body.kind === "anchor") {
        current.anchors = [
          ...current.anchors,
          {
            id: "anchor-1",
            name: body.name,
            start: body.start || "09:00",
            duration_minutes: body.duration_minutes || 30,
            source: draft ? draft.source : undefined,
          },
        ];
      } else if (body.kind === "flex") {
        current.flexes = [
          ...current.flexes,
          {
            id: "flex-1",
            name: body.name,
            duration_minutes: body.duration_minutes || 30,
            source: draft ? draft.source : undefined,
          },
        ];
      }
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && (url.pathname === "/api/drop" || url.pathname === "/api/drop-draft")) {
      current = {
        ...current,
        drafts: current.drafts.filter(d => d.id !== body.id),
      };
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/suggest-activity") {
      await route.fulfill({ json: { suggestion: null } });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.locator("#drafts").waitFor();

  // 1. Promote overdue draft to To-do: note transfers and chip removed without .overdue-tag on To-do
  await page.locator('[data-promote="draft-todo"]').click();
  await page.locator("#promote-draft").waitFor();
  await page.locator('#promote-draft select[name="kind"]').selectOption("todo");
  await page.locator('#promote-draft button[type="submit"]').click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  assert.equal(await page.locator('.draft-chip', { hasText: "Tax return" }).count(), 0);
  const todoChip = page.locator("#todos-tray .todo-chip", { hasText: "Tax return" });
  await todoChip.waitFor();
  assert.equal(await todoChip.locator(".note").textContent(), "Send W2 to accountant");
  assert.equal(await todoChip.locator(".overdue-tag").count(), 0);

  // 2. Promote overdue draft to Anchor: placed without .overdue-tag
  await page.locator('[data-promote="draft-anchor"]').click();
  await page.locator("#promote-draft").waitFor();
  await page.locator('#promote-draft button[type="submit"]').click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  assert.equal(await page.locator('.draft-chip', { hasText: "Dentist appointment" }).count(), 0);
  const anchorBlock = page.locator('#rail .block.anchor', { hasText: "Dentist appointment" });
  await anchorBlock.waitFor();
  assert.equal(await anchorBlock.locator(".icloud-tag").textContent(), "📅 iCloud");
  assert.equal(await anchorBlock.locator(".overdue-tag").count(), 0);

  // 3. Promote overdue draft to Flex: placed in tray without .overdue-tag
  await page.locator('[data-promote="draft-flex"]').click();
  await page.locator("#promote-draft").waitFor();
  await page.locator('#promote-draft select[name="kind"]').selectOption("flex");
  await page.locator('#promote-draft button[type="submit"]').click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  assert.equal(await page.locator('.draft-chip', { hasText: "Gym workout" }).count(), 0);
  const flexChip = page.locator('#tray .flex-chip', { hasText: "Gym workout" });
  await flexChip.waitFor();
  assert.equal(await flexChip.locator(".overdue-tag").count(), 0);

  // 4. Drop overdue draft: removes the chip
  const dropChip = page.locator('.draft-chip', { hasText: "Old newsletter" });
  await dropChip.waitFor();
  assert.equal(await dropChip.locator(".overdue-tag").textContent(), "Overdue");
  await dropChip.locator('[data-drop-draft="draft-drop"]').click();
  await dropChip.waitFor({ state: "detached" });
  assert.equal(await page.locator('.draft-chip', { hasText: "Old newsletter" }).count(), 0);

  assert.deepEqual(pageErrors, []);
  await page.close();
});

test("Edit modal Unplace action, tray reappearance, and browser end-to-end flow", async () => {
  const page = await browser.newPage();
  const pageErrors = [];
  page.on("pageerror", error => pageErrors.push(error.message));
  page.on("console", msg => console.log("PAGE LOG:", msg.text()));

  const initialSession = {
    plan_date: "2026-10-20",
    plan_date_label: "Tuesday, October 20",
    bounds: { wake: "07:00", sleep: "22:00", sleep_is_next_day: false },
    template_offer: "declined",
    show_template_offer: false,
    drafts: [],
    anchors: [
      { id: "anchor-1", name: "Standup", start: "08:00", duration_minutes: 30, checklist: null, checklist_items: [] }
    ],
    flexes: [
      { id: "flex-placed", name: "Deep Work", start: "10:00", duration_minutes: 60, checklist: null, checklist_items: [] },
      { id: "flex-unplaced", name: "Gym", start: null, duration_minutes: 45, checklist: null, checklist_items: [] }
    ],
    todos: [
      { id: "todo-1", name: "Call Mom", note: "Weekly call" }
    ],
    gaps: [],
    blockers: [],
    can_undo: false,
    can_redo: false,
    checklists: [],
    weather_name: null,
    weather_one_liner: null
  };

  let current = JSON.parse(JSON.stringify(initialSession));
  const requests = [];

  await page.route("**/api/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const body = request.postDataJSON() || {};
    requests.push({ method: request.method(), path: url.pathname, body });

    if (request.method() === "GET" && url.pathname === "/api/session") {
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/suggest-activity") {
      await route.fulfill({ json: { suggestion: null } });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/unplace") {
      assert.equal(body.id, "flex-placed");
      current = {
        ...current,
        flexes: current.flexes.map(f => f.id === body.id ? { ...f, start: null } : f),
        can_undo: true
      };
      await route.fulfill({ json: current });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/undo") {
      current = JSON.parse(JSON.stringify(initialSession));
      current.can_undo = false;
      await route.fulfill({ json: current });
      return;
    }
    await route.fulfill({ json: current });
  });

  await page.goto(baseUrl);
  await page.locator('#rail [data-id="anchor-1"]').waitFor();

  // 1. Check edit modal on anchor: "Unplace" button does not exist
  await page.locator('#rail [data-id="anchor-1"]').click();
  await page.locator("#edit-activity").waitFor();
  assert.equal(await page.locator('#edit-activity [data-unplace-activity]').count(), 0);
  await page.locator('#edit-activity button[data-close]').click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // 2. Check edit modal on unplaced flex in tray: "Unplace" button does not exist
  await page.locator('[data-edit-flex="flex-unplaced"]').click();
  await page.locator("#edit-activity").waitFor();
  assert.equal(await page.locator('#edit-activity [data-unplace-activity]').count(), 0);
  await page.locator('#edit-activity button[data-close]').click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // 3. Check edit modal on To-do in tray: "Unplace" button does not exist
  await page.locator('[data-edit-todo="todo-1"]').first().click();
  await page.locator("#edit-activity").waitFor();
  assert.equal(await page.locator('#edit-activity [data-unplace-activity]').count(), 0);
  await page.locator('#edit-activity button[data-close]').click();
  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // 4. Click placed flex on the timeline rail: edit modal opens, "Unplace" button exists and is visible
  await page.locator('#rail [data-id="flex-placed"]').click();
  await page.locator("#edit-activity").waitFor();
  const unplaceButton = page.locator('#edit-activity [data-unplace-activity="flex-placed"]');
  assert.equal(await unplaceButton.count(), 1);
  assert.equal(await unplaceButton.isVisible(), true);

  // Dynamic type switching: switching to Anchor hides Unplace button, switching back shows it
  await page.locator('#edit-activity select[name="kind"]').selectOption("anchor");
  assert.equal(await unplaceButton.isVisible(), false);
  await page.locator('#edit-activity select[name="kind"]').selectOption("todo");
  assert.equal(await unplaceButton.isVisible(), false);
  await page.locator('#edit-activity select[name="kind"]').selectOption("flex");
  assert.equal(await unplaceButton.isVisible(), true);

  // 5. Click "Unplace": verifies POST /api/unplace with {"id": "flex-placed"}, modal closes,
  // placed flex block is removed from the timeline rail, gap updates, flex appears in unplaced tray unarmed
  const unplaceReq = page.waitForRequest(req => req.url().endsWith("/api/unplace"));
  await unplaceButton.click();
  const receivedUnplace = await unplaceReq;
  assert.deepEqual(receivedUnplace.postDataJSON(), { id: "flex-placed" });

  await page.locator("#sheet-backdrop.open").waitFor({ state: "detached" });

  // Timeline rail removed the placed flex block
  await page.locator('#rail [data-id="flex-placed"]').waitFor({ state: "detached" });
  assert.equal(await page.locator('#rail [data-id="flex-placed"]').count(), 0);

  // The rail now has the updated gap from 08:30 to 22:00
  assert.equal(await page.locator('#rail [data-kind="gap"]').count(), 2);

  // Flex appears in tray unarmed
  const flexChip = page.locator('#tray [data-arm="flex-placed"]');
  await flexChip.waitFor();
  assert.equal(await flexChip.isVisible(), true);
  const chipClass = await flexChip.getAttribute("class");
  assert.equal(chipClass.includes("armed"), false);

  // Can subsequently be armed from tray
  await flexChip.click();
  assert.equal((await flexChip.getAttribute("class")).includes("armed"), true);
  await flexChip.click();
  assert.equal((await flexChip.getAttribute("class")).includes("armed"), false);

  // 6. Click Undo: verifies POST /api/undo, flex returns to placed position on the timeline rail
  const undoReq = page.waitForRequest(req => req.url().endsWith("/api/undo"));
  await page.locator("#undo").click();
  const receivedUndo = await undoReq;
  assert.deepEqual(receivedUndo.postDataJSON(), {});

  await page.locator('#rail [data-id="flex-placed"]').waitFor();
  assert.equal(await page.locator('#rail [data-id="flex-placed"]').isVisible(), true);
  assert.equal(await page.locator('#tray [data-arm="flex-placed"]').count(), 0);

  assert.deepEqual(pageErrors, []);
  await page.close();
});
