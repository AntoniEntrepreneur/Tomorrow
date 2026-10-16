# Tunable Version

A **tunable version** is the winning variant with a floating panel of knobs over it. The user drags, picks and edits until it looks right, then pastes back the exact values. Variants settle structure; tuning settles the details on top of a structure the user already chose.

The panel is [tuner.js](tuner.js): a plain ES module, no framework. Each knob drives one CSS custom property, so the variant needs no wiring beyond reading `var(--tune-<name>, <default>)`.

## 1. Pick the knobs

At most 8. Each knob names a property the question left open: the ones the user hesitated over while flipping variants, or the ones the winner got roughly right. A knob nobody would argue about is noise in the panel.

| Type | Use for | Definition |
|---|---|---|
| `slider` | size, spacing, radius, font size, gap | `steps: [{ label, value }]`, `default` a step label |
| `color` | fill, text, border | `swatches: [{ label, value }]`, `default` a swatch label |
| `toggle` | show or hide an element, a shadow or border on or off | `on`, `off` CSS values, `default` true or false |
| `select` | weight, alignment, row or column, element order | `options: [{ label, value }]`, `default` an option label |
| `text` | copy, button labels | `selector` of the element; its current text is the default |

Position is a `select` (`order`, or `above / below`) plus spacing sliders, so every tuned value maps onto the layout system the real code uses.

Done when every knob traces to an open property and each has a `default` matching what the variant renders today.

## 2. Fill the scales from the project

Slider `steps` and colour `swatches` come from the project's own design scale: its Tailwind theme, CSS variables, or token file. Label each with the token name (`rounded-xl`, `emerald-600`) so the pasted result names tokens. A project with no colour tokens gets `swatches: []`, and the free picker carries the knob alone.

## 3. Wire it into the variant

Copy `tuner.js` next to the prototype. In the variant, replace each tuned value with its property: `border-radius: var(--tune-card-radius, 12px)`, or `rounded-[var(--tune-card-radius)]` in Tailwind. Mount the panel only outside production, the same gate as the variant switcher:

```tsx
// Next client component; adapt to the project's framework
useEffect(() => {
  if (process.env.NODE_ENV === "production") return;
  let unmount: (() => void) | undefined;
  import("./tuner.js").then(({ mountTuner }) => {
    unmount = mountTuner({ title: "VariantB on /settings", knobs });
  });
  return () => unmount?.();
}, []);
```

A plain HTML page mounts it from a `<script type="module">` instead.

## 4. Hand it over and fold the paste

Tell the user to tune, press **Copy changes**, and paste the block into chat:

```
Tuned: VariantB on /settings
  card radius: rounded-xl → rounded-2xl
  accent colour: indigo-600 → emerald-600
  hint box: on → off
```

Make each pasted value the knob's new `default` in the variant, so the page and the panel agree on the next round. Then offer another round. A free-picker hex with no swatch label folds in as the nearest token; name the rounding when you report back (`#16a34b → emerald-600`).

Done when every pasted line is the variant's default and the user has no further round to tune. The final pasted block travels with the verdict when the prototype is captured.
