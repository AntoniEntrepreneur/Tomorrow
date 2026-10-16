---
name: quiz
description: Feynman-style quiz on your personal dev glossary — recall a saved term from memory to promote it from introduced to known.
disable-model-invocation: true
---

Quiz mode for the glossary the `explain` skill maintains. Recall only — no multiple choice, no fill-in-the-blank: the user has to produce the explanation themselves.

Read `~/.claude/glossary/FORMAT.md` first — it defines the glossary file's location, layout, entry template, status semantics, and the "I already know this" promotion rule, shared with the `explain` skill.

## Step 1 — Pick a term

Read the glossary and select one entry currently at `introduced` status. If none exist, say so and stop — do not invent a term to quiz on.

Done when you've picked exactly one term and are ready to show only its name, withholding its definition, analogy, and example.

## Step 2 — Ask, then judge

Present the term and ask the user to explain it in their own words. Judge the reply as **solid** — it captures the term's actual meaning, even if phrased loosely or incompletely on minor points — or **shaky** — it misses, inverts, or hand-waves the core meaning.

If the user instead says "I already know this" rather than attempting a recall, apply the promotion-by-statement rule (`FORMAT.md`) instead of judging a recall.

## Step 3 — Apply the outcome

- **Solid** → promote the entry to `known`, set `Last reviewed` to today, tell the user they've got it.
- **Shaky** → leave status at `introduced`, set `Last reviewed` to today, then give a corrective explanation — definition, analogy, and a tiny example, the same shape `explain` produces (read `~/.claude/skills/explain/SKILL.md` Step 3 if unsure) — so they get another real pass at it.

Done when the glossary file's status and `Last reviewed` date for that term reflect the judged outcome.
