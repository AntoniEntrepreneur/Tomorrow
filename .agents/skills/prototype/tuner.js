// Prototype tuner: a floating panel of knobs over one UI variant.
// Each knob drives a CSS custom property (or, for `text`, an element's copy),
// so the variant reads `var(--tune-<name>, <default>)` and needs no wiring.
// "Copy changes" puts the changed knobs on the clipboard as `default → new`.
//
// mountTuner({ title, knobs, target? })
//   title:  names the variant in the copied block, e.g. "VariantB on /settings"
//   target: element the custom properties are set on (default: <html>)
//   knobs:  [{ name, label, type, ... }], where type is one of
//     slider  steps: [{ label, value }], default: a step label
//     color   swatches: [{ label, value }], default: a swatch label or a hex
//     toggle  on, off: CSS values, default: true | false
//     select  options: [{ label, value }], default: an option label
//     text    selector: CSS selector of the element whose copy is edited

export function mountTuner({ title, knobs, target = document.documentElement }) {
  const storageKey = `prototype-tuner:${title}`;
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(storageKey) || "{}"); } catch {}
  const state = {};
  const textDefaults = {};

  const find = (list, label) => list.find((x) => x.label === label);
  const persist = () => { try { localStorage.setItem(storageKey, JSON.stringify(state)); } catch {} };

  function cssValue(knob, v) {
    if (knob.type === "slider") return find(knob.steps, v)?.value;
    if (knob.type === "color") return find(knob.swatches, v)?.value ?? v;
    if (knob.type === "toggle") return v ? knob.on : knob.off;
    if (knob.type === "select") return find(knob.options, v)?.value;
  }

  function apply(knob) {
    const v = state[knob.name];
    if (knob.type === "text") {
      const el = document.querySelector(knob.selector);
      if (el && el.innerText !== v) el.innerText = v;
      return;
    }
    target.style.setProperty(`--tune-${knob.name}`, cssValue(knob, v));
  }

  const panel = document.createElement("div");
  panel.style.cssText =
    "position:fixed;top:12px;right:12px;z-index:2147483647;width:260px;max-height:80vh;overflow:auto;" +
    "background:#111;color:#eee;font:12px/1.4 system-ui,sans-serif;border-radius:10px;padding:10px;" +
    "box-shadow:0 6px 24px rgba(0,0,0,.4)";
  const head = document.createElement("div");
  head.style.cssText = "display:flex;gap:6px;align-items:center;margin-bottom:8px";
  head.innerHTML = `<b style="flex:1">Tuner</b>`;
  const btn = (label, onClick) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.style.cssText = "background:#333;color:#eee;border:0;border-radius:6px;padding:3px 7px;cursor:pointer;font:inherit";
    b.onclick = onClick;
    return b;
  };
  const body = document.createElement("div");
  head.append(
    btn("Copy changes", () => navigator.clipboard.writeText(changes())),
    btn("Reset all", () => knobs.forEach(reset)),
    btn("–", () => { body.hidden = !body.hidden; }),
  );
  panel.append(head, body);

  const rows = {};
  function render(knob) {
    const row = rows[knob.name];
    row.innerHTML = "";
    const top = document.createElement("div");
    top.style.cssText = "display:flex;justify-content:space-between;margin-top:6px";
    const changed = state[knob.name] !== knob.default;
    top.innerHTML = `<span>${knob.label}${changed ? " •" : ""}</span>`;
    top.append(btn("↺", () => reset(knob)));
    row.append(top);
    const set = (v) => { state[knob.name] = v; apply(knob); persist(); render(knob); };
    const v = state[knob.name];

    if (knob.type === "slider") {
      const i = knob.steps.findIndex((s) => s.label === v);
      const input = Object.assign(document.createElement("input"),
        { type: "range", min: 0, max: knob.steps.length - 1, step: 1, value: i });
      input.style.width = "100%";
      input.oninput = () => set(knob.steps[input.value].label);
      row.append(input, document.createTextNode(v));
    } else if (knob.type === "color") {
      const wrap = document.createElement("div");
      wrap.style.cssText = "display:flex;flex-wrap:wrap;gap:4px;align-items:center";
      for (const s of knob.swatches) {
        const sw = document.createElement("button");
        sw.title = s.label;
        sw.style.cssText = `width:18px;height:18px;border-radius:4px;cursor:pointer;background:${s.value};` +
          `border:2px solid ${s.label === v ? "#fff" : "transparent"}`;
        sw.onclick = () => set(s.label);
        wrap.append(sw);
      }
      const free = Object.assign(document.createElement("input"), { type: "color", value: cssValue(knob, v) });
      free.oninput = () => set(free.value);
      wrap.append(free, document.createTextNode(" " + v));
      row.append(wrap);
    } else if (knob.type === "toggle") {
      const input = Object.assign(document.createElement("input"), { type: "checkbox", checked: v });
      input.onchange = () => set(input.checked);
      row.append(input, document.createTextNode(v ? " on" : " off"));
    } else if (knob.type === "select") {
      const sel = document.createElement("select");
      for (const o of knob.options) sel.append(new Option(o.label, o.label, false, o.label === v));
      sel.onchange = () => set(sel.value);
      row.append(sel);
    } else if (knob.type === "text") {
      row.append(document.createTextNode(`edit on the page: "${v}"`));
    }
  }

  function reset(knob) {
    state[knob.name] = knob.default;
    apply(knob);
    persist();
    render(knob);
  }

  for (const knob of knobs) {
    if (knob.type === "text") {
      const el = document.querySelector(knob.selector);
      knob.default = el ? el.innerText : "";
      if (el) {
        el.contentEditable = "true";
        el.style.outline = "1px dashed #f0f";
        el.addEventListener("input", () => { state[knob.name] = el.innerText; persist(); render(knob); });
      }
    }
    state[knob.name] = knob.name in saved ? saved[knob.name] : knob.default;
    rows[knob.name] = document.createElement("div");
    body.append(rows[knob.name]);
    apply(knob);
    render(knob);
  }

  function changes() {
    const show = (k, v) => (k.type === "toggle" ? (v ? "on" : "off") : k.type === "text" ? `"${v}"` : v);
    const lines = knobs
      .filter((k) => state[k.name] !== k.default)
      .map((k) => `  ${k.label}: ${show(k, k.default)} → ${show(k, state[k.name])}`);
    return [`Tuned: ${title}`, ...(lines.length ? lines : ["  (no changes)"])].join("\n");
  }

  document.body.append(panel);
  return () => panel.remove();
}
