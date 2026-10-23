const assert = require("node:assert/strict");
const { test } = require("node:test");
const { setupBrowserTest } = require("./helpers.cjs");

const env = setupBrowserTest();

test("Day Template mode loads and saves through its HTTP endpoint", async () => {
  const { browser, baseUrl } = env;
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
  const { browser, baseUrl } = env;
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
