export const TIMING_FIELDS = ["start", "duration_minutes", "end"];
export const SUGGESTIBLE_FIELDS = ["checklist", "checklist_items", ...TIMING_FIELDS];

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

export function clockValue(input) {
  return String(input.value || "").slice(0, 5);
}

export function checklistPayload(form) {
  const value = form.checklist ? form.checklist.value : "";
  return value || null;
}

export function checklistItemsPayload(form) {
  const raw = form.checklist_items ? form.checklist_items.value : "";
  return raw.split("\n").map(line => line.trim()).filter(Boolean);
}

export function markTouched(form, fieldNames) {
  fieldNames.forEach(fieldName => {
    if (form[fieldName]) form[fieldName].dataset.touched = "1";
  });
}

export function isTouched(form, fieldName) {
  return Boolean(form[fieldName] && form[fieldName].dataset.touched === "1");
}

export function untouchedField(form, fieldName) {
  return form[fieldName] && !isTouched(form, fieldName) ? form[fieldName] : null;
}

export function autofill(form, fieldName, value) {
  const field = untouchedField(form, fieldName);
  if (!field) return;
  if (!("original" in field.dataset)) field.dataset.original = field.value;
  field.value = value;
}

export function restoreAutofilled(form, fieldNames) {
  fieldNames.forEach(fieldName => {
    const field = untouchedField(form, fieldName);
    if (!field || !("original" in field.dataset)) return;
    field.value = field.dataset.original;
    delete field.dataset.original;
  });
}
