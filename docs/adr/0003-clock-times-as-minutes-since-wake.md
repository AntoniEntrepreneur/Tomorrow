# Clock times are offsets from wake, not minutes-since-midnight

Day bounds, Anchors, Flex, and Gaps all resolve to minutes-since-wake — `(clock - wake) mod 1440` — everywhere ordering, overlap, or bounds-checking happens, in both `tomorrow/domain.py`/`tomorrow/plan.py` and the `session.html` JS. Midnight-crossing is not a separate code path: sleep at or before wake, or an Anchor with an early clock time, both land past the wake→wake+24h span naturally once expressed as an offset. Wake equal to sleep collapses the envelope to zero minutes and is rejected the same way other bounds problems are — as a finalize-time blocker, not eager validation in `edit_bounds`.

**Why:** the alternative (an explicit "this time is past midnight" flag per bound/Anchor) pushes a bookkeeping burden onto the user for something inferable from the data itself, and would need to be threaded through every place a clock time is entered or edited. Minutes-since-wake makes midnight-crossing a property of the arithmetic, not a case every call site has to remember to check.

**Considered:** an explicit next-day toggle on sleep/Anchor times; keeping `minutes_since_midnight` and special-casing comparisons where wraparound is possible.
