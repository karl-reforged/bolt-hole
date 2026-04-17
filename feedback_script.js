/**
 * Google Apps Script — Feedback endpoint for Bolt Hole shortlist.
 *
 * Receives GET requests from the shortlist page and logs to a Google Sheet.
 * Deploy as: Web App → Execute as Me → Anyone can access.
 *
 * Setup:
 *   1. Go to script.google.com → New Project
 *   2. Paste this entire file
 *   3. Click Deploy → New Deployment → Web App
 *   4. Set "Execute as" = Me, "Who has access" = Anyone
 *   5. Copy the deployment URL
 *   6. Add to .env: FEEDBACK_SCRIPT_URL=https://script.google.com/macros/s/XXXX/exec
 *   7. Re-run shortlist.py to embed the URL
 *
 * Sheet structure (auto-created on first request):
 *   Column A: Timestamp
 *   Column B: Property ID
 *   Column C: Action (feedback / comment / favourite)
 *   Column D: Reaction (love / interesting / pass) or Value (1 / 0 for favourite)
 *   Column E: Comment text
 */

function doGet(e) {
  var params = e.parameter;
  var action = params.action || "feedback";
  var propertyId = params.property_id || "unknown";
  var reaction = params.reaction || params.value || "";
  var comment = params.comment || "";

  // Open or create the Sheet
  var ss = SpreadsheetApp.getActive();
  if (!ss) {
    // Running standalone — create a new spreadsheet
    ss = SpreadsheetApp.create("Bolt Hole — Feedback");
  }

  var sheet = ss.getSheetByName("Feedback");
  if (!sheet) {
    sheet = ss.insertSheet("Feedback");
    sheet.appendRow(["Timestamp", "Property ID", "Action", "Reaction", "Comment"]);
    sheet.getRange(1, 1, 1, 5).setFontWeight("bold");
  }

  // Log the feedback
  sheet.appendRow([
    new Date(),
    propertyId,
    action,
    reaction,
    comment
  ]);

  // Return a simple response (the page uses no-cors so this rarely displays)
  return ContentService
    .createTextOutput("OK")
    .setMimeType(ContentService.MimeType.TEXT);
}
