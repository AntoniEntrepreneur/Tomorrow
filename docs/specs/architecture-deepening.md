# Architecture deepening: Session HTTP, iCloud import, and construction page

## Problem Statement

Changes to Tomorrow’s construction flow cross protocol handling, Session rules, macOS calendar access, and a large browser script. This makes it harder to locate behavior, test changes at the highest useful seam, and understand how a change affects Plan construction. The current code already has seams worth preserving: Session owns construction rules, iCloud classification accepts plain records, and the browser communicates through HTTP.

## Solution

Deepen three existing module seams without changing planner behavior:

1. Isolate HTTP routing and JSON translation from Session operations.
2. Isolate macOS EventKit acquisition from platform-independent iCloud classification.
3. Split the construction page’s client logic into cohesive modules for state and HTTP calls, reusable timing/checklist behavior, and Session/template presentation.

Keep the user-visible construction flow, stored Session shape, Plan output, and import behavior stable.

## User Stories

1. As a planner user, I want construction requests to keep behaving the same after the HTTP adapter is separated, so that I can continue building and submitting my Plan without relearning the flow.
2. As a maintainer, I want HTTP routing, payload parsing, response serialization, and status mapping kept together, so that protocol changes have locality.
3. As a maintainer, I want Session mutations and construction rules to stay behind the Session module, so that browser protocol code does not become the owner of planner behavior.
4. As a maintainer, I want HTTP behavior testable through the browser-facing server, so that tests cover actual requests and responses rather than private dispatch helpers.
5. As a macOS planner user, I want calendar and reminder imports to retain their current results and permission flow, so that separating EventKit acquisition does not change what enters my Session.
6. As a maintainer, I want iCloud classification to operate on plain event and reminder records, so that classification remains independent of macOS frameworks.
7. As a maintainer, I want EventKit permissions, calendar enumeration, and record acquisition grouped in one adapter, so that platform-specific behavior has locality.
8. As a maintainer, I want iCloud import tests to use injected records and the public import seam, so that classification outcomes can be checked without EventKit access.
9. As a planner user, I want the construction page to retain its current Session, template, and Library interactions after client code is split, so that the refactor has no workflow changes.
10. As a planner user, I want wake-relative timing and after-midnight ordering to remain consistent across the page, so that displayed and submitted times agree.
11. As a planner user, I want name-derived time suggestions to appear only when promoting a Draft, so that an unattended parse never creates an Anchor.
12. As a maintainer, I want browser state and HTTP calls kept distinct from presentation and reusable timing/checklist behavior, so that a change in one concern has locality.
13. As a maintainer, I want browser tests to exercise visible construction interactions, so that they verify user-observable behavior rather than internal script organization.
14. As a maintainer, I want the new modules to have narrow interfaces that hide implementation details, so that each interface can serve as a durable test surface.

## Implementation Decisions

- The Session module remains the owner of Session persistence, mutation rules, view construction, and calls into Plan finalization. A separate HTTP adapter owns routing, JSON request/response handling, status codes, server binding, and HTTP process concerns.
- Preserve the existing browser-facing HTTP routes and their behavior. Keep error responses and successful response shapes stable unless an existing contract is demonstrably inconsistent; any such correction is outside this refactor.
- Keep pure iCloud classification independent of EventKit. A platform adapter acquires raw records and permissions, then hands plain records to classification. Preserve the public import behavior consumed by Session and the existing injection seam.
- Organize the construction page into cohesive client modules: state and HTTP interaction, shared timing/checklist behavior, and Session/template presentation. Keep the existing browser entry points and interaction flow stable; do not add a general-purpose frontend framework as part of this work.
- Preserve the existing data formats and user-facing behavior. No Session JSON migration, TOML migration, Plan HTML change, or new planner feature is part of this work.
- Respect ADR-0002: Session is adapter JSON rather than a new domain aggregate, and construction rules remain in the Session module.
- Respect ADR-0003: time ordering uses minutes since wake, including after-midnight times.
- Respect ADR-0004 and ADR-0005: Day Template seeding and Checklist detach/promotion semantics remain unchanged.
- Respect ADR-0006: name-derived times remain suggestions applied during Draft promotion.

## Testing Decisions

- Tests should assert externally visible behavior at the highest useful seam. Avoid tests coupled to private routing tables, module names, or script file layout.
- Exercise HTTP routes through the browser-facing server. Cover representative successful requests, invalid actions/payloads, blocked submission responses, and stable JSON/status behavior.
- Exercise iCloud import using injected raw event/reminder records at the public import/classification seam. Cover classification into Anchors and Drafts, clashes with existing Anchors, and behavior when platform acquisition is unavailable. Keep EventKit permission and fetch behavior isolated from pure classification tests.
- Exercise the construction page through browser-visible interactions for Session mutations, template behavior, timing across midnight, checklist edits, and Draft promotion suggestions. Assert rendered state and resulting HTTP behavior, not internal JavaScript function calls.
- Use existing test patterns in the HTTP/session tests, iCloud tests, and browser page interaction coverage as prior art. Add browser-level coverage where the current suite only verifies Python behavior.

## Out of Scope

- Changing Session domain ownership, introducing a mutable Session aggregate in the Plan domain, or moving construction rules into HTTP handlers.
- Changing iCloud classification policy, calendar/reminder selection, permission semantics, or item identity/deduplication behavior.
- Changing Plan finalization, time semantics, Draft promotion semantics, Checklist behavior, or Day Template seeding semantics.
- Changing page appearance, adding new planner features, changing stored formats, or adopting a frontend framework.
- Broad architectural cleanup outside the three named seams.

## Further Notes

- ADR-0002 already states that HTTP only routes and serializes while construction rules live in the Session module. Extracting the adapter should bring the implementation into clearer alignment with that decision, not reopen it.
- The project has no root `GLOSSARY.md`; use the domain terms in `CONTEXT.md`.
- The client-side timing implementation must be reviewed against the Python wake-relative timing rules to avoid subtle midnight divergence.
