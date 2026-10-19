# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

One person — the owner of this tool — booking his own and his dependents' appointments at Hindalco Hospital, Renukoot. He uses it on a phone in the minutes before a slot opens and on a desktop when he has time to prepare. Not a staff console: there is no queue, no second operator, no shared counter.

## Product Purpose

Registers an appointment in the hospital's Oracle APEX registration system faster and more reliably than doing it by hand. At 7:30:00 and 14:00:00 IST a slot opens against everyone else trying at the same second; the tool fires 30 parallel submissions of one prepared booking and reports which one landed. Success is a registered appointment with a token number visible in OPD Status, and a failed attempt that says exactly why.

## Positioning

The timing engine, not the form. The booking is prepared ahead of the slot, held armed, and released at the moment the hospital's registration window opens — with a server-side scheduler that can fire when the owner is asleep. A neighbouring booking site could copy the fields; it could not copy the readiness, the parallel release, or the truthful progress of it.

## Operating Context

- Upstream is an Oracle APEX app (hospital-registration-system-renukoot) reached over the public internet; login is by hospital credentials, then a dependent is chosen by MR number.
- Departments and doctors come from APEX dropdowns; doctor values are opaque codes plus display labels.
- Slots: morning 07:30 IST, afternoon 14:00 IST. Sunday closed; Saturday afternoon closed.
- The owner prepares the booking, then waits with the screen in hand. The phone is the common case at the moment of release; the desktop is where the booking gets prepared.
- Credentials are typed per session and never stored by the tool.

## Capabilities and Constraints

- Endpoints that must keep working unchanged: `/api/login`, `/api/opd_status`, `/api/departments`, `/api/doctors`, `/api/submit` (server-sent events: `progress`, `result`, `error`, `done`), `/api/schedule`, `/api/schedules`, `DELETE /api/schedule/<id>`.
- Submission is 30 parallel POSTs with a 0.25s stagger; progress is counted 1→30; success is a `redirectURL` in the APEX response, failure message is the first APEX error string.
- Schedules live server-side keyed by Flask session; the client polls every 5s and cancels by id.
- Stack is fixed: Flask + Jinja2 templates, one vanilla-JS page, no build step, no bundler, no framework. Must stay that way.
- No design tokens, DESIGN.md or component library exist yet.

## Brand Commitments

- The hospital's real name is used factually: Hindalco Hospital, Renukoot.
- The tool is a personal instrument, not an official hospital product; it must never dress itself as the hospital's own system or invent hospital branding, logos or claims.

## Evidence on Hand

- No logos, photography, testimonials or brand assets. Do not fabricate them.
- Real API shapes and error strings are the only ground truth available; demo data shown in any preview must be labelled as sample data.

## Product Principles

1. The clock is the instrument. Never make the owner compute the moment; show the moment.
2. One thumb at 7:29. Every control reachable and tappable on a phone, no hover-only affordance, no precision drag.
3. Show the machine working — attempts, timing, stream events — instead of claiming success.
4. Failure is information: surface the APEX error verbatim, never a cheerful paraphrase.
5. Preserve upstream truth: no invented doctors, tokens, departments or confirmation text.

## Accessibility & Inclusion

- Used one-handed, at 6 AM in poor light and midday in daylight: contrast and tap targets (44px+) matter more than density.
- Respect `prefers-reduced-motion`; the countdown and progress must remain legible without animation.
