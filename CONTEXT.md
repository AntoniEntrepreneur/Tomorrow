# Tomorrow

Personal next-day planner: the night before, produce a believable wake-to-sleep Plan for tomorrow.

## Language

**Plan**:
The schedule for one calendar day, produced the night before, spanning wake to sleep. A one-shot artifact — generate it, use it; mid-day reshuffling is out of scope. A Plan whose date is before today is deleted.
_Avoid_: Schedule, agenda, timeline (as the name of the object)

**Plan date**:
The calendar date the Plan is for — always the next wake, never a picker. If local time is before Defaults' wake, Plan date is today; otherwise tomorrow.
_Avoid_: Target date, schedule date

**Anchor**:
A Plan item locked to a clock start that other items must respect. It must occupy time: an end time, an explicit duration, a Template/library default duration, or a duration you give when asked. Anchors may not overlap each other or sit outside day bounds.
_Avoid_: Appointment, fixed commitment, hard event

**Flex**:
A Plan item with a known duration but no fixed start; it must be placed into a free gap on the Plan.
_Avoid_: Soft task, duration task, floating block

**Day bounds**:
The wake time and sleep time that define the Plan's temporal envelope for that day. Confirmed each Session, pre-filled from personal defaults.
_Avoid_: Availability, working hours

**Gap**:
A contiguous stretch of free time on the Plan between day bounds and Anchors, into which Flex can be placed.
_Avoid_: Slot, window, free block

**Draft**:
Something captured during the Session that is not yet an Anchor or Flex. A Plan is not finished while any Draft remains.
_Avoid_: Inbox item, untimed task, note

**Template**:
A reusable seed of Anchors and/or Flex for a weekday (or named routine), copied into tonight's Session as a starting point. It does not place Flex into Gaps. Entries may include which Checklist to attach.
_Avoid_: Default plan, preset schedule

**Checklist**:
A named reusable list of things to bring or do, attached to a Plan item and shown with that item on the finished Plan. On the finished Plan, rows can be checked off during the day. A Template entry may pre-attach a Checklist.
_Avoid_: Packing list, subtasks (unless they are literally checklist rows)

**Drop**:
An explicit decision to remove a Flex (or Draft) from tomorrow so the Plan can finish honestly. The item is gone — no not-today list, no note on the Plan.
_Avoid_: Defer, snooze, skip (unless we later define those)

**Defaults**:
Your usual day bounds (wake and sleep) used to pre-fill the Session.
_Avoid_: Settings, preferences (as the name of this concept)

**Session**:
The mutable night-before construction of one Plan date — day bounds, Drafts, Anchors, Flex. It is not the Plan. One Session per Plan date; it survives Submit and resumes until Plan date rolls.
_Avoid_: Wizard, draft plan, construction (as the name of the object)

**Submit**:
The act that writes a finished Plan from a clean Session. It does not end the Session; a later Submit the same night overwrites that Plan date's Plan.
_Avoid_: Save, generate, export, finish (as the name of this act)

**Reset**:
Blanks the Session for the current Plan date. It does not delete Plan HTML.
_Avoid_: Clear, new session, start over
