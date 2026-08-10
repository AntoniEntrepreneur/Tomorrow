# PROTOTYPE — Checklist checkoff on the Plan

**Throwaway.** Answers issue #3: how should Checklist checkoff feel on the morning Plan?

**Status:** decided · **Verdict:** none of the three new treatments below beat the existing
`tl-accordion` checkoff from issue #2 — bottom "Pack & prep" section, one bundle expanded at a
time, tap the bundle header to open/close. That treatment is confirmed as the answer for #3
too; no new checkoff pattern is being adopted from this prototype. See
[`../plan-look/DECISIONS.md`](../plan-look/DECISIONS.md) for the full spec.

Built on the winning Plan look from issue #2 (`tl-accordion`'s timeline rail, full-page
scroll, nothing sticky). Three structurally different Checklist treatments, switchable via
`?variant=` and the floating bar at the bottom.

## Run

```bash
python prototype/checklist-checkoff/serve.py
```

Or from this directory:

```bash
python serve.py
```

Opens `http://127.0.0.1:8766/index.html`. Use arrow keys or the bottom bar to cycle variants.

## Variants

| Key | Treatment |
|-----|-----------|
| `inline-expand` | Checklists live only on the timeline rail. Blocks with a checklist show a `🎒 done/total` badge; tapping the block expands it in place (rail reflows), revealing checkboxes right there. No separate bottom section. |
| `side-panel` | Timeline (left) + a checklist panel (right) listing every bundle at once, no accordion inside it. On phone the panel drops below the timeline. Tapping a timeline item scrolls to / highlights its checklist in the panel. |
| `packing-sheet` | Timeline (schedule only) + one always-expanded sheet at the bottom, grouped by bundle heading, nothing collapses. |

Sample data seeds mixed progress on first load (one bundle done, one partial, one untouched)
so all three treatments are judgeable without clicking first. Checkoff state persists in
`localStorage` keyed to this Plan's date, same mechanism as issue #2's prototype.

Do not merge to main as-is beyond capturing the decision. Capture the winning treatment (and
why) on issue #3, then fold that choice into the real Jinja render.

**Related:** [`../plan-look/DECISIONS.md`](../plan-look/DECISIONS.md) — the Plan look this
builds on.
