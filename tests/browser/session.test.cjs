const assert = require("node:assert/strict");
const { test } = require("node:test");
const { setupBrowserTest, sessionView } = require("./helpers.cjs");

const env = setupBrowserTest();

test("Session interactions render wake-relative time, preserve checklist edits, and promote Draft suggestions over HTTP", async () => {
  const { browser, baseUrl } = env;
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
