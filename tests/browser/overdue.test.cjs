const assert = require("node:assert/strict");
const { test } = require("node:test");
const { setupBrowserTest, sessionView } = require("./helpers.cjs");

const env = setupBrowserTest();

test("Overdue draft chip renders .overdue-tag badge with warm amber color alongside iCloud tag", async () => {
  const { browser, baseUrl } = env;
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
  const { browser, baseUrl } = env;
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
