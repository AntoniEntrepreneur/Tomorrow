const assert = require("node:assert/strict");
const { test } = require("node:test");
const { setupBrowserTest } = require("./helpers.cjs");

const env = setupBrowserTest();

test("Unified activity edit modal displays Type selector, toggles fields dynamically, pre-populates defaults/template, cleans action buttons, and submits to /api/edit", async () => {
  const { browser, baseUrl } = env;
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
