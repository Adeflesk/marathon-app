# Strength logging: review

Scope: a single-user app that gets one runner to the Barcelona Marathon (14 Mar 2027). Advice aimed at a
public product (accounts, i18n, SEO, PWA, new branding) is out of scope.

## Status

Tasks 1–7 of `docs/superpowers/plans/2026-10-19-strength-logging.md` are built, committed and merged, and the
test suite passes (194 tests). The phone-screen check at 390 px in light and dark modes covered the strength,
snack, morning-check and test cards.

| Area | Where |
|---|---|
| Storage (logs, snacks, tests, checks) | `app/db.py` |
| Routines and prescriptions | `app/strength.py` |
| Weight and rep suggestions | `app/progression.py` |
| Ankle flag, hop and balance stages, test weeks | `app/ankle.py` |
| Routes and view wiring | `app/main.py` |
| Cards | `app/templates/_strength.html` |

## Open items

1. **Deploy check.** Task 8 Step 4: `fly deploy --ha=false`, wake the app, run the `fly ssh console` page
   check. Expected `[200, 200, 200, 200]`. Not confirmed yet.
2. **Back up the data.** Logs, snacks, ankle tests and equipment live on one Fly volume (`/data`). Add a
   simple export or a `fly ssh sftp get` backup so a lost volume does not lose the training history.
3. **Optional CI.** Run `pytest` on push.
4. **Tap targets and contrast** on the Easy/Right/Hard buttons, since they are used between sets.
5. **Housekeeping.** Untracked `PROJECT_REVIEW.md`, `research_notes/` and `samples/` need committing,
   ignoring or removing.

## Out of scope

OAuth and accounts, i18n, SEO, PWA/offline, analytics dashboard, a help modal, new fonts or glassmorphism
(the plan says to reuse existing design tokens), and tests for the scratch preview server.
