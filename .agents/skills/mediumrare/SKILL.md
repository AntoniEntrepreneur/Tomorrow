---
name: mediumrare
description: Unpack the grilling questions you're stuck on — plain English, every option kept, trade-offs spelled out.
argument-hint: "Which question numbers? (blank = all of them)"
disable-model-invocation: true
---

# Medium Rare

A grilling round is on screen and the user could not answer part of it. Your job is **translation**: the same round, rewritten in words they can act on. The round itself stays as it was — same questions, same options, same labels — and the turn ends with the user holding it, ready to answer.

Read the whole round from context before you start.

## Arguments

Every number in the argument names a question from the round. Ignore separators and a leading `Q`, so `3 7`, `3,7` and `Q3,Q7` are one input. **No argument means every question in the round.**

If a number has no matching question, say so in one line, name the range the round actually covered, and stop there.

## Step 1 — Record

The same prompt usually answers the other questions. Echo them back as one line before anything else, so a misreading surfaces now rather than three rounds later:

> **Recorded:** Q1 → (b) list of numbers. Q2 → (b) delegate to `/explain`. Q4 → their own wording, quoted short.

Under `/grill-with-docs`, `domain-modeling` still writes a resolved term into `GLOSSARY.md` inline. An ADR offer waits until the round is fully answered — it interrupts the one person who asked to be unblocked.

Done when every answer given in this prompt appears in the echo.

## Step 2 — Translate each flagged question

Work them in ascending order, each under a heading carrying its number and title:

`### Q3 — Where is the streak computed?`

### The scaffold

Write each part when it has real content, except **what breaks if you pick wrong**, which is always written.

- **What's being decided** — one plain sentence, naming the thing that will actually differ.
- **Why it's not obvious** — the pull in each direction, in a sentence.
- **Think of it like** — an analogy from outside software, used where one genuinely holds and skipped where none does.
- **The options** — grilling's options, reproduced with the same set, the same order and the same labels, because the label is what the user types back. Restate each one's consequence in plain English, its cost included. Every option grilling offered stays, presented on its own terms; the ranking is the user's to do.
- **What breaks if you pick wrong** — the concrete failure with a person in it: what someone sees, and what you have no way to fix afterwards.

Then two blank lines, then `➡️` with the recommendation and its one-line reason — far enough down the page that the user meets it after forming a view.

### Vocabulary

- **CS jargon** — call the Skill tool with `explain` and run its Steps 1–4: the definition lands inline, the glossary entry gets written, and the per-term comprehension question is held back for Step 3.
- **Project vocabulary** — the project's own domain terms belong to its `GLOSSARY.md`. Use each term the way the round used it, and let the sentence around it carry the sense.

A question holding neither CS jargon nor options still earns the framing half — what's being decided, why it's not obvious, the analogy, what breaks. Write those, and that question is done.

### Facts

Reuse what the grilling agent already surfaced in earlier rounds: its 🔎 lines are known, not re-derived. Beyond those, read `GLOSSARY.md`, the ADR in `docs/adr/` that the question bears on, and any file the question names. That is the whole search — those are the files that flip a recommendation, and the user is waiting. Mark anything left unverified with ⚠️.

Done when every flagged question carries a scaffold and a recommendation.

## Step 3 — Close

In this order:

1. **One comprehension question**, on the hardest idea in the whole run — one, across every question you translated. Aim it at what the user would get wrong in real code, and phrase it so only someone who understood can answer; applying the idea to a case you did not cover works well.
2. **The closing line**: no new questions this round, answer the flagged ones above, and grilling picks up from there.

When the answer comes back wrong, name the precise bit of the model that is off, re-explain that bit alone, and ask one narrower follow-up.

When the user says they are still lost, ask which part missed — the term, the trade-off, or which option to pick — and re-explain that part alone.

## Glyphs

🔎 a fact you looked up, ✏️ a rendered instance, ⚠️ unverified, ➡️ the recommendation — the meanings `grilling` gives them. Its ❓ and 📍 stay with `grilling`, so this reply reads as a translation rather than a new round.
