# PROTOTYPE — morning Plan HTML look

**Throwaway.** Answers issue #2: what should the morning Plan HTML look like?

Three structurally different layouts, switchable via `?variant=` and the floating bar at the bottom.

## Run

```bash
python prototype/plan-look/serve.py
```

Or from this directory:

```bash
python serve.py
```

Opens `http://127.0.0.1:8765/index.html`. Use arrow keys or the bottom bar to cycle variants.

## Variants

**Round 2 — timeline + bottom prep (full page scroll, nothing sticky):**

| Key | Layout |
|-----|--------|
| `tl-accordion` | Timeline rail + vertical accordion prep at bottom |
| `tl-tabs` | Timeline rail + pill-tab prep picker at bottom |
| `tl-cards` | Timeline rail + expandable prep cards (2-col on desktop) |

**Round 1 — legacy:**

| Key | Layout |
|-----|--------|
| `timeline` | Timeline-first day strip — checklists inline |
| `agenda` | Dense agenda sheet |
| `checklist` | Checklist-led morning board |

Do not merge to main. Capture the winning direction on issue #2, then fold that choice into the real Jinja render (#5).

**Decisions:** [`DECISIONS.md`](DECISIONS.md) — grilled spec + winner (`tl-accordion`). Issue #2 / #5 link here.
