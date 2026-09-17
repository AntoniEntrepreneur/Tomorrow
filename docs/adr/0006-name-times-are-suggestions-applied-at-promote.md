# A time parsed from a name is a suggestion, applied at promote time

A time read out of an item's name (e.g. `Tutoring 16:30`) is a **suggestion only**. It pre-fills fields a person can overwrite; it never creates an Anchor on its own. Detection happens when a Draft is promoted in the Promote sheet / `session_view`, not during iCloud classification.

**Why:** promotion is the moment a person is already looking at the item and choosing what it becomes. Pre-filling a time there saves typing while leaving the honesty check intact — the person still confirms or overrides before an Anchor exists. iCloud classification runs unattended; trusting a guess parsed from a string at that point would let a misread name (`Room 16:30-B`, a phone number, a date) silently become a scheduled commitment with no one looking. That bypasses the honesty the Draft tray exists to provide: everything unclear lands as a Draft for a person to resolve, not as something the system decided on their behalf.

**Considered:** teaching iCloud classification to read the name so a timed reminder lands directly as an Anchor (e.g. `Tutoring 16:30` classifies straight to a 30-minute Anchor at 16:30). Rejected: it trusts an unattended guess from a string, and it removes the person's chance to catch a bad parse before it becomes a real commitment on the Plan.
