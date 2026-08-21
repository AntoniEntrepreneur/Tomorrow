# Tomorrow

Personal next-day planner: the night before, produce a believable wake-to-sleep Plan for tomorrow.

## Language

**Plan**:
The schedule for one calendar day, produced the night before, spanning wake to sleep. A one-shot artifact — generate it, use it; mid-day reshuffling is out of scope. A Plan is what a Session becomes at Submit, not the Session itself.
_Avoid_: Schedule, agenda, timeline (as the name of the object)

**Session**:
The mutable night-before construction of a Plan: day bounds, Drafts, Anchors, and Flex, editable until Submit. Distinct from the finished Plan.
_Avoid_: Wizard, editor, draft (as the name of the whole)

**Submit**:
The act of finishing a Session into a Plan. Allowed only when no Draft remains, every Flex is placed, and no finalization blocker remains.
_Avoid_: Save, export, publish, write

The schedule for one calendar day, produced the night before from a Session, spanning wake to sleep. A one-shot artifact for that day — generate it, use it; mid-day reshuffling is out of scope. Distinct from the Session. A Plan whose date is before today is discarded so Plans do not accumulate.
_Avoid_: Schedule, agenda, timeline (as the name of the object)

**Plan date**:
The calendar day a Session is constructing a Plan for. If local time is before Defaults' wake, Plan date is today (the coming wake); otherwise it is tomorrow.
_Avoid_: Target date, session date, schedule date

**Session**:
The mutable night-before construction of a Plan for one Plan date: day bounds, Drafts, Anchors, and Flex. One Session per Plan date. Submit does not end it; Reset blanks it; when the Plan date rolls, an unfinished Session is gone.
_Avoid_: Wizard, editor, draft (as the name of the whole)

**Submit**:
Writing a Plan from the current Session. Allowed only when no Draft remains, every Flex is placed, and no finalization blocker remains. Does not end the Session; a later Submit overwrites that Plan date's Plan.
_Avoid_: Save, export, publish, write

**Reset**:
Discard the Session's contents to a blank Session for the same Plan date. Does not delete an existing Plan. Undoable.
_Avoid_: Start over, clear, new session, discard (as the name of this act)

**Undo**:
Restore the previous Session from a short stack of snapshots. Covers Session mutations including Drop and Reset. Does not touch Plan HTML.
_Avoid_: revert, history, revision

**Redo**:
Restore a Session snapshot that Undo pushed aside. Does not touch Plan HTML.
_Avoid_: unrevert, history, revision

**Anchor**:
A Plan item locked to a clock start that other items must respect. It must occupy time: an end time, an explicit duration, a Template/library default duration, or a duration you give when asked. Anchors may not overlap each other or sit outside day bounds.
_Avoid_: Appointment, fixed commitment, hard event

**Flex**:
A Plan item with a known duration but no fixed start; it must be placed into a free gap on the Plan.
_Avoid_: Soft task, duration task, floating block

**Day bounds**:
The wake time and sleep time that define the Plan's temporal envelope for that day. Pre-filled from Defaults when a Session starts; editable on the Session. Changing them does not rewrite Defaults. Sleep at or before wake (clock-time) is a same-day-name for a time that falls after midnight: the envelope always runs wake → wake+24h, never wake → midnight. Wake equal to sleep is invalid (zero-length day) and blocks Submit. An Anchor may likewise fall after midnight; its position is judged by the same wake-relative offset, not by raw clock time.
_Avoid_: Availability, working hours, confirmed bounds

**Gap**:
A contiguous stretch of free time on the Plan between day bounds and Anchors, into which Flex can be placed.
_Avoid_: Slot, window, free block

**Draft**:
Something captured during a Session that is not yet an Anchor or Flex. A Plan is not finished while any Draft remains.
_Avoid_: Inbox item, untimed task, note

**Day Template**:
A reusable seed of Anchors and/or Flex for a whole Plan date, copied into tonight's Session as a starting point. It does not place Flex into Gaps. A Day Template may be assigned as the default for one weekday (at most one Day Template per weekday) or left unassigned, reachable only by manually choosing it. Applying a Day Template — by weekday default or manual choice — is only possible on a blank Session; it seeds, it does not merge. Entries may define a Checklist to attach, or reference an Activity Template.
_Avoid_: Template (ambiguous with Activity Template), default plan, preset schedule, routine

**Activity Template**:
A single reusable Anchor-shaped or Flex-shaped Plan item — name, a fixed start or a duration, and an optional Checklist — that can be inserted into a Session on its own, independent of any Day Template. Reachable by browsing a picker, or by autocomplete: a typed Draft/Anchor/Flex name that matches an Activity Template suggests the whole bundle (start or duration, plus Checklist) and takes precedence over a bare Checklist name match.
_Avoid_: Routine, preset item, snippet

**Checklist**:
A named reusable list of things to bring or do, attached to a Plan item and shown with that item on the finished Plan. On the finished Plan, rows can be checked off during the day. A Day Template entry or an Activity Template may pre-attach a Checklist. Deleting a Checklist or Activity Template still referenced by a Day Template entry, or still attached to an item in an in-progress Session, is allowed — the reference goes stale rather than blocking the deletion.
_Avoid_: Packing list, subtasks (unless they are literally checklist rows)

**Drop**:
An explicit decision to remove a Flex (or Draft) from tomorrow so the Plan can finish honestly. The item is gone from the Plan — no not-today list, no note on the Plan. Undo can restore it until that step ages off the stack.
_Avoid_: Defer, snooze, skip (unless we later define those)

**Defaults**:
Your usual day bounds (wake and sleep) used to pre-fill the Session.
_Avoid_: Settings, preferences (as the name of this concept)
