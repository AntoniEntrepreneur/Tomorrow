# Plan HTML look — decisions (issue #2)

**Status:** decided · **Winner:** `tl-accordion` (timeline rail + bottom Pack & prep accordion)

Primary source for issue #5 (Jinja render). Prototype code at `prototype/plan-look/` on `main`.

## Verdict

Use the **timeline day strip** as the main read. **Checklist rows live only in Pack & prep** at the bottom — not inline on timeline blocks. Prep bundles use a **vertical accordion** (one open at a time; all collapsed on load).

## Page structure (top → bottom, full scroll)

Nothing sticky. The whole page scrolls.

1. **Header** — date, day bounds (wake/sleep), weather one-liner
2. **Timeline rail** — wake → sleep, proportional block heights, minimal Gap labels
3. **Pack & prep** — accordion section below the rail

Single column on phone and desktop (wider max-width on desktop; no side panel).

## Timeline rail

| Decision | Choice |
|----------|--------|
| Gap visualization | Proportional height + minimal dashed rule + `Gap · 45m` label |
| Anchor vs Flex | Visual only — solid left border (anchor) vs dashed (flex). No "Anchor"/"Flex" badges on finished Plan |
| Checklists on rail | **No** — schedule only (title + time range) |
| Time source of truth | Clock times only on timeline blocks |

## Pack & prep

| Decision | Choice |
|----------|--------|
| Placement | Bottom of page, after timeline |
| Bundle header | Parent item title + Checklist name (e.g. `Gym · Gym bag`). **No time in prep** |
| Scope | All attached Checklists for the day, ordered by parent item time |
| Layout | Vertical accordion — one bundle expanded at a time |
| Default on load | All bundles collapsed |
| Completed bundles | Move to collapsed **Done · N** section at bottom of prep |
| Tap bundle | No scroll-to-timeline |
| Checkoff | Working checkboxes; persist in `localStorage` keyed to plan/day (see issue #1) |

## Not in scope for this look

- Sticky header or sticky prep
- Domain jargon on the finished page
- Tap-to-jump from prep to timeline block

## Prototype reference

```bash
python prototype/plan-look/serve.py
# http://127.0.0.1:8765/index.html?variant=tl-accordion
```

Round 2 variants (for comparison only): `tl-tabs`, `tl-cards`. Round 1 legacy: `timeline`, `agenda`, `checklist`.

## Session log

Grilled in chat 2026-08-10. Initial round 1 picked sticky prep (later revised). Final rounds locked full-scroll layout and bottom prep. User chose accordion over tabs and cards.
