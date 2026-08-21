# Session is adapter JSON, not a domain type

An unfinished Session is a glossary/UI fact. It is not a type in `tomorrow/domain.py`. `Draft`, `Anchor`, `Flex`, and `finalize_plan` stay the finalization seam; ids never land on those types.

The adapter module `tomorrow/session.py` owns gitignored `data/session.json` (load/save, mint opaque ids, apply add/edit/Drop/Place/Change-Duration/Reset/Template/promote-Draft, unpack into domain types, call `finalize_plan`). HTTP only routes and serializes. Construction rules live in that module, not in the domain and not in `do_POST` branches.

**Why:** keeping the Python domain as the core means honesty checks (`finalize_plan`), not a second mutable aggregate that would shadow `FinalizedPlan`. A Session struct or Session operations in `domain.py` would expand that seam; stuffing the same rules into the HTTP handler would make the adapter fat. The file shape is the Session; Gaps and blockers stay derived.

**Considered:** a frozen `Session` in `domain.py`; `Session` plus mutation operations in `domain.py` (the standing “domain is the core” pull).
