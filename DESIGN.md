# Design system

The visual record for `templates/index.html`. Product truth lives in [PRODUCT.md](PRODUCT.md); this file records what the interface actually is, so later changes extend it instead of drifting.

## Direction

A light, flat, single-column product surface. One job per screen: read the window, arm it, watch the dispatch, check OPD. No cards, no panels — sections are separated by hairlines and space, and the countdown is the page's spine. The world is deliberately quiet; the only loud element is the number that matters.

## Color

| Token | Value | Job |
|---|---|---|
| `--paper` | `#F4F5F1` | page ground |
| `--surface` | `#FFFFFF` | controls, result strips |
| `--ink` | `#12161A` | primary text, countdown |
| `--ink-2` | `#3C454B` | secondary text, table meta |
| `--muted` | `#5A666C` | labels, captions, disabled copy (≥4.5:1 on paper) |
| `--line` | `#DDE0DA` | hairlines and table rules |
| `--line-2` | `#C7CCC4` | control borders, meter ticks |
| `--accent` | `#2440E8` | primary action, active step, open window |
| `--ok` | `#0B7A46` | accepted token, registered result |
| `--bad` | `#C0321F` | failed attempts, refusals |
| `--warn` | `#9A5B00` | wrong-credentials and missing-input toasts |

Restrained strategy: neutrals carry the page, cobalt marks the action and the live state, green and red appear only as meaning (never as decoration). Tinted result strips use `#F2F9F4` / `#FDF4F2` at 1px borders — the only filled blocks in the page.

## Type

One family: `Segoe UI Variable Display` → `Segoe UI` → system stack. No webfont is loaded; the page must render the same offline.

| Role | Size / weight | Notes |
|---|---|---|
| Countdown | `clamp(62px, 10.6vw, 112px)` / 250 | `tabular-nums`, tracking `-.035em`, line-height 1.02 |
| Section title | 15px / 600 | tracking `-.01em` |
| Body | 15px / 400 | line-height 1.55 |
| Control text | 13.5–14px / 500–600 | |
| Label / caption | 11px / 600 | uppercase, tracking `.06–.1em`, `--muted` |
| Step number | 11px / 600 | `tabular-nums`, accent when active |

The 11px floor is a hard rule: nothing functional sits below it.

## Spacing and layout

- Page column: `max-width: 900px`, centered, `24px` gutters (`16px` under 720px).
- Section rhythm: `44px` above, `18px` inside, hairline `1px` on top (`34px` on mobile).
- Step rows: `168px` label column + flexible control column, chip under the label; `16px` vertical padding, hairline between rows.
- Radii: `10px` controls, `8px` inputs and small buttons, `2px` tally bars. Never pill-shaped.
- Depth: hairlines only. The two exceptions are the sticky bar's blur and toast elevation.

## Components

- **Window switch** — two-up segmented control; selected option is white on `--line` with a 1px shadow, the other is transparent.
- **Meter** — 2px hairline track, cobalt fill, tick every 10%, scale labels `60 MIN OUT / 30 / window`. Fills to 100% across the final hour; turns green when the window is open.
- **Buttons** — `44px` tall (`34px` for `btn-sm`), 600 weight; primary is solid cobalt, secondary is white with a hairline; disabled goes `#F0F1ED` with `#656E73` text.
- **Steps** — a ruled list, never cards. State is carried by the chip under the title (`Required` / `Locked` / `Connected` / `Selected`), the step number turning cobalt, and green for completion.
- **Tally** — 30 cells, `34px` tall (26px on mobile), 3px gaps: unlit `#E7E9E4`, sent `#9FA9F2`, accepted `--ok`, closed `#D7DAD3`, failed `--bad`. On mobile it wraps to two rows of fifteen.
- **Result strip** — icon + title + message inside a tinted hairline box; green for registered, red for refused.
- **OPD table** — 13.5px rows, `tabular-nums` for patient/visit/employee numbers, token as a green chip; under 720px the doctor moves under the patient name and visit/employee are dropped.
- **Toasts** — bottom-right stack (full width under 720px), hairline card, tone-tinted icon only.
- **Remember row** — a checked-by-default checkbox under the session controls: "Keep username and password on this device". It writes `hil.credentials.v1` to `localStorage` on a successful connect; unticking deletes the entry.
- **Install button** — in the top bar, cobalt on white, hidden until `beforeinstallprompt` fires. Text plus a download glyph on desktop; a 32px icon-only square under 720px so the bar still fits a 360px phone.

## States

Every control has hover, focus (`2px` cobalt outline, `3px` offset), disabled, and busy (label swaps to `Loading…`/`Connecting…`, `aria-busy`). Empty states are written as instructions, not apologies: "Nothing armed. Arm a window and the server fires at 07:30 or 14:00 IST — this screen can be closed."

Motion is limited to a 170ms control transition, a 200–300ms rise on the dispatch panel and toasts, and the 600ms meter fill. `prefers-reduced-motion` removes all of it.

## Browser surfaces

Selection is cobalt with white text; the caret is cobalt; scrollbars are 10px with a hairline thumb; focus rings are cobalt; `tabular-nums` is applied wherever numbers change in place (countdown, attempts, times, IDs).

## App shell

The page installs as a standalone Chrome app (Android and desktop):

- `static/manifest.webmanifest` — name "Hindalco Hospital Registration", short name "Registration", `display: standalone`, `start_url: /`, paper theme and background so the splash does not flash white-on-white.
- `static/icon-192.png`, `icon-512.png`, `icon-maskable-512.png`, `apple-touch-icon-180.png` — a cobalt ground with a white clock at 7:30, the window the tool exists for. The maskable variant keeps the mark inside the safe zone.
- `static/sw.js`, served from `/sw.js` so its scope is the whole app. The shell is precached and served network-first; **no `/api/` request is ever cached** — a stale OPD table would be worse than an error.

## Session and credentials

A reload always lands signed out. The page fills the username and password from what the browser remembers, and then waits: connecting is a deliberate tap, never automatic. There is no session-restore call and no silent re-login.

That is a product rule, not an oversight. The tool fires 30 registrations the moment it is armed; it should not come back from a refresh already holding a live APEX session that the owner has not looked at.

Credentials live in `localStorage` under `hil.credentials.v1` in plain text, by the owner's choice; unticking the box deletes them. Never send them anywhere else, and never sync them.

## Rules for future work

1. No cards. If a block needs grouping, use a hairline and space.
2. Never below 11px for anything a person must read or tap.
3. The countdown is the largest element on the page and must stay so.
4. One accent. Green and red are state, never decoration.
5. Keep the single column: this tool has one task at a time.
6. Everything must work with the network failing — every fetch error surfaces as a toast with the underlying message.
