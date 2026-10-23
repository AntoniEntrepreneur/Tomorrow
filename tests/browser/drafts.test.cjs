const assert = require("node:assert/strict");
const { test } = require("node:test");
const { setupBrowserTest, sessionView } = require("./helpers.cjs");

const env = setupBrowserTest();

test("Draft Edit applies Activity Template suggestions and keyboard undo", async () => {
  const { browser, baseUrl } = env;
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
  const { browser, baseUrl } = env;
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
