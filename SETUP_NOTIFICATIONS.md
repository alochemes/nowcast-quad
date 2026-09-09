# Notification Setup (email via Google Sheets/Apps Script + Slack)

The pipeline already pushes a status payload after every run (`nowcast/notify_remote.py`).
Two one-time account-side steps activate delivery. Both keys go in
`private/config.yaml`:

```yaml
notify:
  webapp_url: https://script.google.com/macros/s/XXXX/exec
  slack_webhook: https://hooks.slack.com/services/T000/B000/XXXX
```

Either can be omitted — each channel is independent and best-effort.

## A. Email + run-history sheet (Google Apps Script) — ~5 minutes

1. Create a new Google Sheet (any name, e.g. "Nowcast Quad Runs") while logged
   in as the Google account that should receive the emails. Set `EMAIL` at the
   top of `nowcast_notifier.gs` to that same address.
2. Extensions → Apps Script. Delete the stub and paste ALL of
   **`nowcast_notifier.gs`** (repo root — the single source of truth for this
   code).
3. Deploy → New deployment → type **Web app** → Execute as **Me**, access
   **Anyone with the link** → Deploy. Authorize when prompted. Copy the
   `.../exec` URL into `webapp_url` in `private/config.yaml`.
4. In the Apps Script editor: Triggers (clock icon) → Add Trigger →
   function `dailyStalenessCheck`, event source **Time-driven**, **Day timer**,
   9am–10am. This is the off-machine dead-man switch: it emails you even if
   the PC is off or the task was deleted — something the local watchdog
   cannot do.
5. Test from the PC:
   `.venv\Scripts\python.exe -c "from nowcast import notify_remote; notify_remote.push_status({'status':'OK','quarter':'TEST','quad':3,'quad_name':'Stagflation','gdp_yoy':2.1,'cpi_yoy':3.8,'note':'setup test'})"`
   → you should get the email and see a new sheet row within seconds.

### Updating the Apps Script code later

Editing the script alone does **not** change the live web app — Apps Script
serves the deployed *version*. After pasting new code from
`nowcast_notifier.gs`: **Deploy → Manage deployments → ✏️ (Edit) → Version:
New version → Deploy.** The `/exec` URL stays the same, so no config change
is needed on the PC.

### Subject lines are ASCII, and are built on the PC

The subject arrives ready-made in the payload's `subject` field
(`notify_remote.build_subject`); the Apps Script only falls back to composing
one if that field is missing. Two reasons:

- **ASCII only.** The old subject carried `⚠️`, `→` and `—` as literals in the
  `.gs` source and they were delivered as mojibake (2026-08-03). Mail headers
  need RFC 2047 encoding to survive non-ASCII, and that is not a thing worth
  gambling on for a status email — the whole line is now 7-bit.
- **No redeploy to reword it.** Subject changes now ship with an ordinary
  `git pull` on the PC instead of a manual paste-and-redeploy in the browser.

Shapes, all ending in the run date so each run opens a fresh Gmail thread:

```
Nowcast Quad: 3Q26E Quad 1 Goldilocks - Aug 3
Nowcast Quad: 3Q26E Quad 1 Goldilocks (new quarter) - Aug 3
Nowcast Quad CHANGE: 3Q26E Quad 2 -> 1 Goldilocks - Aug 3
Nowcast Quad: RUN FAILED - Aug 3
```

`CHANGE` fires only when **the same quarter** moved quad since the last run.
A calendar roll — 3Q26 taking over from 2Q26 as the current quarter — is
reported in the body as housekeeping, not flagged in the subject. Before this,
a roll compared last run's 2Q26 against this run's 3Q26 and sent a false alarm.

### What the OK email contains

- Headline: quarter, quad, GDP/CPI YoY.
- **Changes since last run** — quad flips, GDP/CPI YoY deltas in bps, and
  DFM/GDPNow/blend component moves. Computed on the PC from
  `output/notify_state.json` (previous successful run) and sent as the
  `commentary` field, with a `change_kind` of `quad_change` / `roll` / `none`
  / `first_run` that the subject line and the sheet both record.
- The quad map chart (`output/quad_map.png`), inlined via the
  `chart_png_b64` payload field.
- **The history ribbon** (`output/quad_ribbon.png` via `ribbon_png_b64`) —
  one strip per quarter, colored by the quad being called on each date.
- The ensemble note (DFM/GDPNow blend arithmetic).
- **The report itself** (added 2026-07-29) — quad assignment by quarter with
  Δbps, levels and QoQ SAAR, and the run-details block, rendered into the body
  from the `report_html` field. `nowcast/report.py:email_report_html` builds
  it separately from `render_html`: Gmail drops `<style>` blocks, so every
  rule is an inline style, and quarters run down the rows instead of across 12
  columns so it reads on a phone.
- **`report.html` attached** (`report_file_b64` / `report_filename`), which
  adds the sections the body leaves out: CPI monthly nowcast detail, CPI model
  parameters, and both data-vintage tables.

Size discipline: Gmail clips a message body past ~102 KB. The body's tables
run ~23 KB, the chart travels as an inline image (attachments do not count
toward that limit), and the whole POST is ~670 KB — well inside what the web
app accepts. `MAX_REPORT_BYTES` in `notify_remote.py` (6 MB) skips the
attachment rather than sending an oversized mail; the skip is logged to
`run.log`.

The sheet logs the numeric fields (incl. `dfm_saar`, `gdpnow_saar`,
`blend_saar`) but not the commentary text, the chart, or the report.

## B. Slack — ~5 minutes

1. https://api.slack.com/apps → Create New App → From scratch → pick your
   workspace.
2. Features → Incoming Webhooks → toggle ON → Add New Webhook to Workspace →
   choose a channel (e.g. #nowcast) → copy the webhook URL into
   `slack_webhook` in `private/config.yaml`.
3. Test with the same one-liner as step A5 — the summary should appear in the
   channel (and on your phone via the Slack app).

**Optional — Claude agent in Slack:** if you also want to *ask questions*
about the nowcast from Slack (not just receive alerts), install Claude for
Slack (`/install-slack-app` from Claude Code, or the Slack App Directory) and
point it at this repo's outputs. The webhook above is independent of that and
works today.

## What fires when

| Event | Local toast | Email | Slack | Sheet row |
|---|---|---|---|---|
| Weekly run OK | ✓ (quad summary) | ✓ (if EMAIL_ON_SUCCESS) — summary + report + attachment | ✓ | ✓ |
| Run FAILED | ✓ red | ✓ "RUN FAILED" | ✓ 🚨 | ✓ |
| Second trigger the same day | — | — | — | — (skipped by `--skip-if-fresh 20`, logged to `run.log`) |
| No run >8 days (PC on) | watchdog toast | — | — | — |
| No run >8 days (even PC off) | — | ✓ "STALE" via Apps Script timer | — | — |

Slack still gets the one-line summary only — the report goes to email.
