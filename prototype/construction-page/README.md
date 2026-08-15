# PROTOTYPE — construction page: running Plan you add to and edit

**Throwaway.** Answers [Construction page: running Plan you add to and edit](https://github.com/AntoniEntrepreneur/Tomorrow/issues/13).

How should the running Plan look on the local page, and how do you add, edit, and Drop an Anchor, a Flex, and a Draft — including adding a forgotten item after others already exist?

Three structurally different layouts, switchable via `?variant=` and the floating bar at the bottom. All three share one in-memory Session so you can flip variants without losing work. Place / Shrink / Drop Flex is available at any time. Direct add of Anchor or Flex is first-class; Draft is optional. Submit, Templates, Checklists, weather, and architecture are out of this prototype.

## Run

```bash
python prototype/construction-page/serve.py
```

Or from this directory:

```bash
python serve.py
```

Opens `http://127.0.0.1:8767/index.html`. Use arrow keys or the bottom bar to cycle variants.

## Variants

| Key | Layout | Primary affordance |
|-----|--------|--------------------|
| `rail` | Night rail — the day strip is the canvas | Click a Gap to add into that time; unplaced Flex chips sit in a tray |
| `desk` | Workbench — Plan on the left, stamps + inspector on the right | Always-visible + Anchor / + Flex / + Draft; forgotten item is a form |
| `log` | Composer log — write at the top, insert between rows | Type a name, pick a kind; "add here" rules between every item |

Seed starts mid-Session (some Anchors already on the Plan, one Flex placed, two unplaced, one Draft) so "I forgot something" is the first move, not an empty page.

**Status:** decided. **Verdict:** mix — desk stamps for add, night rail for the running Plan, unplaced Flex tray always on screen, Drop is Flex/Draft only. See [`DECISIONS.md`](DECISIONS.md).

Do not merge to main. The full set of variants stays on `wayfinder13` as the primary source.
