const assert = require("node:assert/strict");
const { test } = require("node:test");
const { setupBrowserTest, sessionView } = require("./helpers.cjs");

const env = setupBrowserTest();

test("Gap split-half placement dispatches place request at start or wake-relative end with midnight wrap and exact fit", async () => {
  const { browser, baseUrl } = env;
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
  const { browser, baseUrl } = env;
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
  const { browser, baseUrl } = env;
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
  const { browser, baseUrl } = env;
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
