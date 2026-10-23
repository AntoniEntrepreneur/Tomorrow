const assert = require("node:assert/strict");
const { test } = require("node:test");
const { setupBrowserTest, sessionView } = require("./helpers.cjs");

const env = setupBrowserTest();

test("Clicking weather summary pill toggles hourly weather drawer", async () => {
  const { browser, baseUrl } = env;
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
