// ==== Nowcast Quad notifier (paste whole file into Apps Script) ====
// After editing: Deploy → Manage deployments → ✏️ Edit → Version: New version
// → Deploy. The /exec URL stays the same.
const EMAIL = "you@example.com";   // <-- EDIT: address that receives the alerts
const SHEET_NAME = "runs";
const STALE_DAYS = 8;
const EMAIL_ON_SUCCESS = true;   // set false to only get failure/stale alerts

// new columns go on the END: existing rows keep their alignment
const HEADERS = ["timestamp","status","quarter","quad","quad_name",
                 "gdp_yoy","cpi_yoy","note","dfm_saar","gdpnow_saar","blend_saar",
                 "change_kind"];

function esc_(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function nv_(x) { return x == null ? "" : x; }  // keep legitimate zeros

function doPost(e) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sh = ss.getSheetByName(SHEET_NAME) || ss.insertSheet(SHEET_NAME);
  sh.getRange(1, 1, 1, HEADERS.length).setValues([HEADERS]); // idempotent header refresh
  const d = JSON.parse(e.postData.contents);
  // NOTE: the bulky/prose fields (chart_png_b64, report_html, report_file_b64,
  // commentary) are deliberately NOT logged to the sheet
  sh.appendRow([new Date(), d.status, nv_(d.quarter), nv_(d.quad), nv_(d.quad_name),
                nv_(d.gdp_yoy), nv_(d.cpi_yoy), nv_(d.note),
                nv_(d.dfm_saar), nv_(d.gdpnow_saar), nv_(d.blend_saar),
                nv_(d.change_kind)]);
  if (d.status !== "OK") {
    // ASCII subject + date: see sendOkEmail_ (mojibake, and Gmail threading)
    const tag = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "MMM d");
    MailApp.sendEmail(EMAIL, "Nowcast Quad: RUN FAILED - " + tag,
      "Run failed at " + new Date() + "\n\n" + (d.note||"") +
      "\n\nCheck output\\run.log on the PC.");
  } else if (EMAIL_ON_SUCCESS) {
    sendOkEmail_(d);
  }
  return ContentService.createTextOutput("ok");
}

function sendOkEmail_(d) {
  // change_kind is set by nowcast/notify_remote.py and compares a quarter with
  // its OWN previous reading, so a calendar roll no longer reads as a quad
  // change. Older payloads without the field fall back to sniffing the text.
  const kind = d.change_kind ||
    ((d.commentary || "").indexOf("QUAD CHANGE") >= 0 ? "quad_change" : "none");
  const quadChanged = kind === "quad_change";
  // Subject is built in Python (ASCII only — the emoji/arrow literals that
  // used to live here arrived as mojibake) and carries the run date so every
  // run starts a NEW Gmail thread: self-sent mail with a repeated subject
  // joins the old conversation and never surfaces in the Inbox (2026-07-20).
  const dateTag = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "MMM d");
  const subject = d.subject ||
    ("Nowcast Quad: " + d.quarter + " Quad " + d.quad + " " + d.quad_name +
     (quadChanged ? " [CHANGE]" : "") + " - " + dateTag);

  const plain = "GDP " + d.gdp_yoy + "% | CPI " + d.cpi_yoy + "%\n" + (d.note||"")
    + (d.commentary ? "\n\n" + d.commentary : "")
    + (d.report_file_b64 ? "\n\nFull report attached." : "")
    + "\n\nAlso on the PC desktop: 'Quad Nowcast Report'.";

  let html = "<div style='font-family:Arial,Helvetica,sans-serif;font-size:14px;" +
             "color:#222;max-width:720px'>" +
    "<h2 style='margin:0 0 4px'>" + esc_(d.quarter) + ": Quad " + esc_(d.quad) +
    " — " + esc_(d.quad_name) + "</h2>" +
    "<p style='margin:0 0 12px;font-size:16px'><b>GDP " + esc_(d.gdp_yoy) +
    "%</b> YoY &nbsp;|&nbsp; <b>CPI " + esc_(d.cpi_yoy) + "%</b> YoY</p>";
  if (d.commentary) {
    html += "<div style='background:#f4f6f8;border-left:4px solid " +
      (quadChanged ? "#c0392b" : "#2e86c1") + ";padding:10px 12px;margin:0 0 12px;" +
      "white-space:pre-wrap;font-family:Consolas,Menlo,monospace;font-size:13px'>" +
      esc_(d.commentary) + "</div>";
  }
  if (d.note) {
    html += "<p style='color:#555;font-size:12px;margin:0 0 12px'>Ensemble: " +
      esc_(d.note) + "</p>";
  }
  const opts = {};
  opts.inlineImages = {};
  if (d.chart_png_b64) {
    opts.inlineImages.chart = Utilities.newBlob(
      Utilities.base64Decode(d.chart_png_b64), "image/png", "quad_map.png");
    html += "<img src='cid:chart' alt='Quad map' style='max-width:100%;" +
      "border:1px solid #ddd'>";
  }
  // History ribbon: one strip per quarter, colored by the quad being called on
  // each date. Inline images do not count toward Gmail's ~102 KB body clip.
  if (d.ribbon_png_b64) {
    opts.inlineImages.ribbon = Utilities.newBlob(
      Utilities.base64Decode(d.ribbon_png_b64), "image/png", "quad_ribbon.png");
    html += "<h3 style='font-size:14px;margin:18px 0 2px'>How the reading has " +
      "moved</h3><p style='margin:0 0 6px;color:#555;font-size:12px'>Each strip " +
      "is one quarter, read left to right as the model reran. Pale = still an " +
      "estimate, solid = GDP released.</p>" +
      "<img src='cid:ribbon' alt='Quad history' style='max-width:100%;" +
      "border:1px solid #ddd'>";
  }
  // The report itself. report_html is pre-rendered with inline styles by
  // nowcast/report.py:email_report_html — Gmail strips <style> blocks, so it
  // must not be re-wrapped in one. Gmail also clips bodies past ~102 KB; the
  // tables are a few KB, and the chart rides along as an inline image (which
  // does not count toward that limit) rather than as a data: URI.
  if (d.report_html) {
    html += "<hr style='border:none;border-top:1px solid #e5e7eb;margin:18px 0'>" +
      "<h2 style='margin:0 0 2px;font-size:16px'>Nowcast report</h2>" +
      d.report_html;
  }
  if (d.report_file_b64) {
    const name = d.report_filename || "nowcast_report.html";
    opts.attachments = [Utilities.newBlob(
      Utilities.base64Decode(d.report_file_b64), "text/html", name)];
    html += "<p style='color:#888;font-size:12px'>Attached: <b>" + esc_(name) +
      "</b> — the full report (adds the CPI monthly detail, model parameters " +
      "and data-vintage sections). Also on the PC desktop: " +
      "'Quad Nowcast Report'.</p>";
  } else {
    html += "<p style='color:#888;font-size:12px'>Full report: open " +
      "'Quad Nowcast Report' on the PC desktop.</p>";
  }
  html += "</div>";
  opts.htmlBody = html;
  MailApp.sendEmail(EMAIL, subject, plain, opts);
}

// Install a daily time-driven trigger on this function (step 4).
function dailyStalenessCheck() {
  const sh = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sh || sh.getLastRow() < 2) return;
  const last = sh.getRange(sh.getLastRow(), 1).getValue();
  const days = (Date.now() - new Date(last).getTime()) / 864e5;
  if (days > STALE_DAYS) {
    MailApp.sendEmail(EMAIL,
      "Nowcast Quad: STALE - no run for " + Math.floor(days) + " days",
      "No run recorded for " + Math.floor(days) + " days. " +
      "The PC may be off, or the NowcastQuad task disabled.");
  }
}
