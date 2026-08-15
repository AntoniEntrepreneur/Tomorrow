# Construction page — decisions (issue #13)

**Status:** decided · **Winner:** mix — desk stamps for add, night rail for the running Plan

Primary source for the Session construction spec on [Night-before Session: local page spec](https://github.com/AntoniEntrepreneur/Tomorrow/issues/11). Prototype code at `prototype/construction-page/` on `wayfinder13`.

## Verdict

The running Plan is a **vertical day strip** (wake → sleep, proportional Gaps), the same shape as the morning Plan so Submit is not a visual translation. Adding a forgotten item is **type-first stamps** (Anchor / Flex / Draft), not a hunt for a Gap. Unplaced Flex stays **on screen** in a tray (or tools column) with Place / Shrink / Drop at any time. **Drop is Flex and Draft only**; an Anchor leaves by edit.

## Page structure

1. **Stamps** — always-visible Anchor / Flex / Draft. Direct add is first-class; Draft is optional. Forgotten items use this, even when the Plan already has items.
2. **Running Plan** — vertical rail: day bounds, Anchors, placed Flex, Gaps. Tap a block to edit. Click a Gap to Place an armed Flex (or add into that time).
3. **Unplaced Flex tray** — always on screen, not a modal. Place / Shrink / Drop on every unplaced Flex.
4. **Drafts** — chips or a short list; promote to Anchor or Flex, or Drop.

Domain jargon stays on this page (Anchor, Flex, Draft, Gap, Drop). The finished morning Plan does not.

## Add / edit / Drop

| Act | Choice |
|-----|--------|
| Forgotten item | Stamp the kind, then fill name / clock / duration. Not dump-everything-first. |
| Add into a Gap | Allowed as a shortcut (especially Place Flex), not the only add path |
| Edit | Tap the block (or Draft); inspector or sheet. Anchors included. |
| Drop Flex | Tray or the item — gone, no not-today list |
| Drop Draft | On the Draft — gone |
| Drop Anchor | **No.** Anchors leave by edit, not Drop |

## Variants (for comparison only)

| Key | Role |
|-----|------|
| `rail` | Donated the day strip and the unplaced tray |
| `desk` | Donated type-first stamps and the inspector |
| `log` | Name-first composer and insert-between rules — not adopted |

## Not in this decision

- Submit, resume, dates (issue #14)
- Session architecture (issue #15)
- Template, Checklists, weather, day-bounds editing (issue #16)
- Morning Plan HTML look (out of scope unless construction forced a show-change — it did not)

## Prototype reference

```bash
python3 prototype/construction-page/serve.py
# http://127.0.0.1:8767/index.html?variant=rail
```

Also: `?variant=desk`, `?variant=log`.

Grilled in chat 2026-08-15. All four recommendations accepted.
