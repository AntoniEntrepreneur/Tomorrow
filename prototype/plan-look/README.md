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

| Key | Layout |
|-----|--------|
| `timeline` | Timeline-first day strip — proportional vertical rail |
| `agenda` | Dense agenda sheet — compact rows, scan the whole day |
| `checklist` | Checklist-led morning board — action bundles first |

Do not merge to main. Capture the winning direction on issue #2, then fold that choice into the real Jinja render (#5).
