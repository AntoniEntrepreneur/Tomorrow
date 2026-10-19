---
name: explain
description: Explain a programming/CS term, or narrate a whole situation (error, code chunk, decision) in plain English, for a user new to software development, and log jargon to their personal dev glossary.
disable-model-invocation: false
---

Two modes, chosen by what the user hands you:

- **Term mode** — a bare term or phrase ("what does closure mean?"): full definition + analogy + example.
- **Situation mode** — a chunk (an error, a stack trace, code, a design decision, "explain that"): one connected narrative of what's going on, not a list of separate definitions.

Both modes only ever explain **jargon** — generic programming/CS vocabulary (closure, recursion, async, API endpoint, and the like). Project-specific domain or business vocabulary (a project's own concepts — its `CONTEXT.md` and domain glossary own those) is never explained or logged by this skill, in either mode, even when a situation is tangled up with it. If a term is ambiguous between the two, treat it as jargon only when its meaning would hold in any codebase.

Read `~/.claude/glossary/FORMAT.md` first — it defines the glossary file's location, layout, entry template, status semantics, and the "I already know this" promotion rule, shared with the `quiz` skill.

## Step 1 — Collect the term(s)

- **Term mode**: the user names one term directly. One term to resolve.
- **Situation mode**: the user points at a chunk. Read it and pull out every CS-jargon word or phrase it contains — these are the terms that will get individually resolved and (if new) logged as you narrate; domain vocabulary in the chunk is left alone.

Done when you have a concrete list of jargon terms to resolve.

## Step 2 — Resolve each term against the glossary

Look the term up in the glossary file (create it first per `FORMAT.md` if it doesn't exist yet). Three branches:

- **Not present, or `introduced`** → full treatment (Step 3), then write/update the entry as `introduced`, setting `Last reviewed` to today (and `Introduced` to today if new).
- **`known`** → in term mode, a compressed reminder only: the definition condensed to one clause, no analogy, no example. In situation mode, use the term **unmarked** in the narrative — no reminder at all. Either way, update `Last reviewed` to today; status stays `known`.
- **Promotion-by-statement** (`FORMAT.md`) applies here too.

Done when every term from Step 1 has been classified into one of these three branches and handled accordingly.

## Step 3 — Explain, and chase nested jargon

**Term mode**: write the definition, an analogy, and — where it clarifies rather than pads — a tiny example.

**Situation mode**: write one connected narrative of what's happening, weaving in each not-`known` term's explanation as it comes up (domain vocabulary stays unexplained — narrate around it). Reach for an analogy only where it genuinely clarifies — never force one. Prefer a single analogy that frames the whole situation when one holds together end to end; when it doesn't, use separate small analogies only where they help, and skip analogy entirely where none earns its place. An analogy is a tool, not a checklist item.

In both modes, notice any further jargon your own explanation leans on (e.g. explaining "async" pulls in "callback"). For each one found, re-run Step 2 on it before finishing — a nested term only gets defined inline if its own status isn't `known`.

Done when the explanation is free of jargon that hasn't itself been checked against the glossary.

## Step 4 — Commit the glossary writes

Apply every entry write/update decided in Steps 2–3 to `~/.claude/glossary/dev-glossary.md` in one pass, under the right category heading. This is the only place explanations get saved — there is no separate "save this" step for the user to remember.

## Step 5 — Ask one comprehension question

Close every explanation with exactly **one** question that checks whether it landed — the term's core idea in term mode, the situation's core idea in situation mode. Ask it as the last thing in your reply, after the glossary-write note.

- **One question, not a quiz.** Never a batch, never a numbered list.
- **It must be answerable only by someone who understood**, not by pattern-matching words from your explanation back at you. Prefer: applying the idea to a case you did not cover, predicting what breaks if a piece is removed or changed, spotting which of two variants is wrong and why, or deciding whether the concept even applies to a given case.
- **Aim it at the load-bearing idea** — the thing the user would get wrong in real code — not at trivia, spelling, or a definition they could re-read one paragraph up.
- **Ground it in their own repo** when the term or situation came from there; a question about code they actually have beats an abstract one.
- Keep it to a sentence or two. Do not supply the answer, hints, or multiple-choice options unless the user asks or answers wrong.

When the user answers:

- **Right** → confirm briefly and stop. Do not re-explain what they just proved they understood. **Do not promote the entry to `known`, and do not offer to** — a correct answer here is not evidence of durable understanding. Status only becomes `known` via the `quiz` skill or the user's own explicit statement (`FORMAT.md`).
- **Wrong or partly right** → do not simply give the answer. Name precisely which bit of the model is off, re-explain only that bit, and ask one narrower follow-up question. Keep the entry at `introduced`.
- **Declines to answer / ignores it** → let it go, no nagging, no repeat.

Done when the reply ends with one such question, and any answer the user gives has been responded to per the branches above.
