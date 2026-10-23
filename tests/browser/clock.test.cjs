const assert = require("node:assert/strict");
const { test } = require("node:test");

test("Client clock module mirrors Python domain time resolution across midnight (ADR-0003)", async () => {
  const clock = await import("../../tomorrow/static/clock.js");

  // toMin converts HH:MM string to minutes since midnight
  assert.equal(clock.toMin("00:00"), 0);
  assert.equal(clock.toMin("06:30"), 390);
  assert.equal(clock.toMin("07:00"), 420);
  assert.equal(clock.toMin("23:59"), 1439);

  // toClock converts minutes into zero-padded HH:MM string with wraparound
  assert.equal(clock.toClock(0), "00:00");
  assert.equal(clock.toClock(390), "06:30");
  assert.equal(clock.toClock(1439), "23:59");
  assert.equal(clock.toClock(1440), "00:00");
  assert.equal(clock.toClock(1500), "01:00");
  assert.equal(clock.toClock(-60), "23:00");
  assert.equal(clock.toClock(-390), "17:30");

  // endClock computes start + duration with midnight wrapping
  assert.equal(clock.endClock("09:00", 60), "10:00");
  assert.equal(clock.endClock("23:30", 45), "00:15");
  assert.equal(clock.endClock("23:00", 120), "01:00");

  // toWakeMin strictly mirrors domain.minutes_since_wake across midnight
  // Wake = 07:00
  assert.equal(clock.toWakeMin("07:00", "07:00"), 0);
  assert.equal(clock.toWakeMin("07:30", "07:00"), 30);
  assert.equal(clock.toWakeMin("23:00", "07:00"), 960);
  // 00:30 wraps past midnight into 17*60 + 30 = 1050
  assert.equal(clock.toWakeMin("00:30", "07:00"), 1050);
  assert.equal(clock.toWakeMin("01:00", "07:00"), 1080);
  // 06:59 wraps to wake + 24h - 1min = 1439
  assert.equal(clock.toWakeMin("06:59", "07:00"), 1439);

  // isNextDay returns true when clock time is earlier than wake
  assert.equal(clock.isNextDay("07:00", "07:00"), false);
  assert.equal(clock.isNextDay("23:00", "07:00"), false);
  assert.equal(clock.isNextDay("00:00", "07:00"), true);
  assert.equal(clock.isNextDay("00:30", "07:00"), true);
  assert.equal(clock.isNextDay("06:59", "07:00"), true);

  // clockLabel appends ' +1' to next-day clock times
  assert.equal(clock.clockLabel("07:00", "07:00"), "07:00");
  assert.equal(clock.clockLabel("23:00", "07:00"), "23:00");
  assert.equal(clock.clockLabel("00:30", "07:00"), "00:30 +1");
  assert.equal(clock.clockLabel("02:00", "07:00"), "02:00 +1");

  // fmtDur formats duration in minutes to compact human-readable string
  assert.equal(clock.fmtDur(0), "0m");
  assert.equal(clock.fmtDur(45), "45m");
  assert.equal(clock.fmtDur(60), "1h");
  assert.equal(clock.fmtDur(90), "1h 30m");
  assert.equal(clock.fmtDur(120), "2h");
  assert.equal(clock.fmtDur(135), "2h 15m");
});
