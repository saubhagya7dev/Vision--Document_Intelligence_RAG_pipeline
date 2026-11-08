# Vision workspace redesign

Implemented 8 November 2026. The application now opens in chat, using the approved
ink black, cream and burnt orange palette, square corners, smaller typography
and quiet dividers. The original README is unchanged.

## Everyday workflow

1. Start a new chat or reopen one in the sidebar.
2. Upload a PDF beside the composer, or choose documents from the library.
   Uploading saves the PDF in the library and selects it for this chat.
3. Wait for the selected documents to become searchable. You can write while
   preparation runs. Active status uses Luminous Type; page counts show actual
   recorded work, and details/retry actions remain available.
4. Ask a question. Enter sends; Shift+Enter adds a line. Find pages in the mode
   menu searches locally without generating an answer. Stop requests cancellation
   at the next safe processing boundary.
5. Open inline citations or source rows to inspect original pages. Desktop uses
   a drawer; narrower screens use a separate sheet. Close returns to the chat.
6. Save useful answers as findings, or compare explicit reports/versions in
   Compare reports. Reopen and export results from Saved findings.

The next question's source selection is always explicit. Removing a document
chip changes that selection without deleting the PDF. Removing the last chip
blocks sending; it never silently changes the scope to the whole library.
Select ready documents chooses up to six explicit documents. Every submitted
question retains its own source set, and citations retain their original version.
Older chats with automatic scope remain readable but need explicit documents for
their next question.

Drafts are saved in this browser tab's session storage, separately per chat. An
accepted question is cleared from the composer only after the server saves it.
Failed selection saves keep the picker open. Upload errors distinguish failure
before saving from failure to select an already-saved PDF. The interface does not
automatically repeat provider calls or failed preparation jobs.

## Navigation and details

- Documents includes search readiness, Ask about this, original PDF access,
  version history, replacement, page processing and deletion.
- Compare reports uses labeled version checkboxes, two to four versions, and
  one to eight fields. Missing evidence remains distinct from a zero value.
- Saved findings supports personal review and JSON, CSV and Markdown exports.
  Page references being checked does not independently establish answer accuracy.
- Processing & search retains durable jobs, cancellation/retry and advanced index
  controls. The existing worker automatically prepares new search snapshots.
- Settings & data keeps history clearing, cache clearing and confirmed library
  reset separate. No real library data was cleared during this work.
- Workspace activity shows actual persisted metrics; chat is the default route.

Luminous Type uses a restrained moving highlight inside active status text.
Reduced-motion settings use static text, and forced-color mode retains readable
text. Keyboard focus is visible; the mobile navigation and chat source sheet keep
focus inside their active surface. Reading older answers is not interrupted by
the final publication of a newer answer; Jump to latest remains available.

## Verification

- 136 Python tests passed, including the new readiness regression for new PDFs,
  stale indexes, page revision changes and deletion.
- Four Node frontend tests passed for empty scope, readiness, failed selection
  recovery, busy-state protection and the six-document limit.
- Ruff lint/format, mypy (44 source files), Python compilation, JavaScript syntax
  and Git whitespace checks passed.
- Isolated browser fixtures exercised streaming, cited pages, cancellation,
  reload/draft recovery, empty selection, Find pages, direct chat upload and worker
  readiness, saved answers, comparison/save/reopen and an actual JSON download.
- Responsive checks used 1280px and 384px viewports. The 384px chat's content width
  was 384px, with the composer inside the viewport. The source sheet likewise
  stayed within the viewport. Citation-close focus restoration was observed.

All new browser inference used simulated providers/local models and generated
fictional PDFs in temporary libraries. No paid provider calls or real user
document uploads were used for verification. These checks establish workflow
behavior, not representative answer quality or production release approval.

Records: [verification](ux-verification.json), [desktop](ux-workspace-desktop.png),
[mobile chat](ux-chat-mobile.png), [mobile source](ux-source-mobile.png).

To run:

```powershell
.\.venv\Scripts\python.exe -m vision_rag.api.main
```

Restart an existing server so it loads the new readiness endpoint, then refresh
the browser. Static assets are content-versioned to avoid stale CSS/JavaScript.

Repeat isolated UI checks with:

```powershell
$env:PYTHONPATH='.;scripts;tests'
.\.venv\Scripts\python.exe -u tests/browser_ux_fixture.py
# Open http://127.0.0.1:18008
node --test tests/frontend_selection.test.mjs
```
