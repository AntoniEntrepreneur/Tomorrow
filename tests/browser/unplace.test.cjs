const assert = require("node:assert/strict");
const { test } = require("node:test");
const { setupBrowserTest } = require("./helpers.cjs");

const env = setupBrowserTest();

test("Edit modal Unplace action, tray reappearance, and browser end-to-end flow", async () => {
  const { browser, baseUrl } = env;
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
