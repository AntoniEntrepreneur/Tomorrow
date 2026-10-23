// Pure wake-relative clock arithmetic and time formatting.
// Mirrors domain wake rules (ADR-0003) without DOM manipulation.

export function toMin(clock) {
  const [hours, minutes] = String(clock).split(":").map(Number);
  return hours * 60 + minutes;
}

export function toClock(minutesRaw) {
  const minutes = ((minutesRaw % 1440) + 1440) % 1440;
  const hours = Math.floor(minutes / 60);
  const mins = minutes % 60;
  return String(hours).padStart(2, "0") + ":" + String(mins).padStart(2, "0");
}

export function endClock(start, durationMin) {
  return toClock(toMin(start) + Number(durationMin));
}

// A clock earlier than wake is tomorrow morning, matching domain.minutes_since_wake.
export function toWakeMin(clock, wake) {
  return (((toMin(clock) - toMin(wake)) % 1440) + 1440) % 1440;
}

export function isNextDay(clock, wake) {
  return toMin(clock) < toMin(wake);
}

export function clockLabel(clock, wake) {
  return clock + (isNextDay(clock, wake) ? " +1" : "");
}

export function fmtDur(minutes) {
  const value = Number(minutes);
  if (value >= 60 && value % 60 === 0) return (value / 60) + "h";
  if (value >= 60) return Math.floor(value / 60) + "h " + (value % 60) + "m";
  return value + "m";
}
