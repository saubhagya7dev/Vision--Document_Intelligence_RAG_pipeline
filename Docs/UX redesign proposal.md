# Vision UX redesign proposal

Preview stage: 8 November 2026. Application code has not been changed.

## Product model

Vision is a document assistant: add PDFs, choose what a question may use, ask,
inspect original cited pages, and save useful answers or comparisons. The default
screen should be a conversation. Users should not need to understand indexing,
embeddings, OCR or retrieval policies to complete that workflow.

Basis: Vision Build chat, current static HTML/JavaScript, the Phase 5 workspace
screenshot, Phase 6/7 guides, and the current feature matrix. The feature matrix
and Phase 7 closeout are newer than the opening scope paragraph in the
implementation checklist. Existing implementation does not mean every feature
has representative quality or deployment validation.

## What currently causes confusion

- Dashboard, Upload, Chat, Documents and Findings divide one task across pages.
- Saved conversations use a selector alongside New, Rename and Delete controls.
- A native multi-select exposes document scope; clearing it silently means all
  live documents. That meaning is difficult to discover and easy to misread.
- Upload processing and retrieval-index readiness are presented separately.
  A file being saved or an ingestion job finishing does not alone explain
  whether the intended document is available to the active search path.
- The composer has no upload entry point. Technical controls compete with
  asking questions, and the evidence pane reserves space before it is needed.
- Persistence, provisional output, reference checking and answer correctness
  appear as technical status text instead of contextual explanations.

## Proposed screens and component responsibilities

| Component | What the user does | Proposed behavior |
| --- | --- | --- |
| Chat sidebar | Start and revisit work | New chat and recent chats; rename/delete in each chat menu; clear selected state |
| Documents | Manage reusable PDFs | Searchable library with preparation state, page count and version; select for a chat, open original, inspect versions or delete |
| Compare reports | Compare explicit reports or versions | Guided selection of retained versions, a question and fields; cited table preserving units, currency, period and scope |
| Saved findings | Keep useful results | Reopen saved answers/comparisons, mark personally reviewed, export JSON, CSV or Markdown |
| Settings & data | Maintain this workspace | Data/history controls, appearance preference, service readiness and advanced search maintenance |
| Chat header | Understand the current conversation | Title, truthful save status, chat menu; no oversized workspace toolbar |
| Document selector | Know what the next question will use | Named chips and a Change action; searchable checkbox picker, up to six explicit documents |
| Composer | Write, attach and send | Multiline draft, Upload PDF / Choose documents menu, removable selection chips, send or Stop |
| Answer | Read and act | Readable text, inline citation buttons, compact source cards, copy/save actions |
| Source drawer | Check the original | Open on citation click; document, immutable version, original page number, page navigation, zoom and original PDF link |
| Processing card | Understand background work | In-chat persistent status with actual stage, known page counts and contextual retry/cancel actions |

No document picker selection means "Choose documents", with send disabled.
Searching all ready library documents must be an explicit labeled option. Resolve
that option to a visible source set when a question is submitted so later library
changes do not silently change a retry. A newly uploaded PDF is saved in the
library and selected for the current chat; tell the user both facts. Removing a
chip changes selection only and never deletes the library PDF.

## Upload and readiness

Proposed sequence: **Upload saved → Reading pages → Preparing search → Ready to ask**.
Use real job states and index membership to derive these labels. Do not invent
stage percentages or completion times. Show page counts only when known.

Readiness is document/version-specific. Verify that the selected version and
eligible pages are usable by the active retrieval path. An older active index
must not make a newly uploaded document appear ready. Refresh status after
replacement, reprocessing or index changes. Keep underlying technical states in
View details.

Automatically coordinating the existing preparation/index APIs is proposed work;
the current separate controls do not already provide this unified flow. Reuse
durable jobs, serialize/coalesce index builds, and preserve a working index while
an update is built. If this cannot proceed, expose a specific recovery action.

Users may draft questions while preparation runs. Sending waits until every
selected document is eligible. Offer an explicit "Use ready documents" action
when only part of the selection is ready; never silently omit selected sources.

## Asking, evidence and recovery

| State | Visible explanation and action |
| --- | --- |
| No sources selected | Add a PDF or choose documents; keep the composer draft editable |
| Uploading | Actual byte progress when available; actionable upload failure |
| Preparing | Current real stage and known page counts; explain why sending is waiting |
| Preparation failed | Say whether the original was saved; retry the correct job/build, view details, preserve draft |
| Searching | "Searching selected documents…" only while that event is true |
| Generating | "Writing answer…"; mark streamed text as a draft; show Stop |
| Completed | Final answer with its source set and clickable page references |
| Insufficient evidence | "I couldn't find this in the retrieved pages"; offer Find pages or change documents; do not assert the whole PDF lacks it |
| Provider unavailable | Preserve question and available evidence; retry, or use Find pages without an answer-provider call |
| Stopped/interrupted | Clear state, retained question, explicit retry; no automatic repeated paid attempts |
| Source unavailable | Explain missing source; preserve historical source identity rather than substituting a newer version |
| Disconnected | Distinguish connection loss from failed work; reconcile saved server state before offering another submission |
| Session expired | Explain sign-in requirement and preserve the unsent draft without persisting credentials |

Each submitted question retains its own source selection. Citations open the
version/page used by that answer, even after the library PDF is replaced. Keep
the question's source context visible without repeating large technical blocks.

"Page references checked" describes identifier/page validation, not independent
verification of meaning or numerical correctness. Personal review is separate.
Do not show a generic "Verified answer" badge. No unsupported confidence scores.

Find pages is an explicit composer mode: searches selected documents using local
retrieval and returns pages without generating an answer. It still requires local
models and search readiness. Compare reports opens a guided workflow; do not
silently interpret every multi-document chat as a structured comparison.

## Versions, comparisons and data controls

Document details contain replacement/version history, original download and
advanced per-page processing. Replacing a PDF must explain which version becomes
current and retain access to historical cited evidence where supported. Deleting
a document requires a clear impact statement about related chats/findings.

Comparisons use explicit versions and fields. Preserve missing/conflicting cell
states, provenance and differing currencies/periods/scopes. "Not found in
retrieved evidence" must not become zero. No implicit arithmetic, currency
conversion or automated version-diff promises. Historical versions require an
eligible retained index. Explain ineligibility before submission.

Save finding retains the server-owned result. Exports are JSON, CSV and Markdown;
PDF export is not currently implemented. Export source links require access to
this workspace and are not public sharing links.

Settings keeps distinct Clear history, Clear page cache and Start fresh actions.
Describe the actual retained/deleted data, including saved findings. Keep the
explicit destructive confirmation for Start fresh. Backup/restore currently uses
an offline command workflow; do not imply an existing browser backup feature.

## Responsive and accessible behavior

- Wide desktop: sidebar, chat, optional source drawer; chat gets the full
  remaining width when the drawer is closed.
- Tablet: collapsible sidebar; source drawer opens over the workspace.
- Phone: chat first, navigation in a sheet, sources in a full-screen view with
  an obvious Back to chat action; composer remains above the keyboard.
- Keyboard-operable pickers and menus, visible focus, named icon buttons,
  sufficient contrast and text labels alongside status colors.
- Announce meaningful stage changes without repeatedly reading every streamed
  token. Focus returns to the initiating citation when the source viewer closes.
- Follow new messages while at the bottom; preserve position while reading
  earlier answers and offer Jump to latest.
- Latest visual direction: Ink Black #111111 backgrounds, Cream #F3EEE3 text
  and Burnt Orange #D9541E accents, using the user's uploaded palette. This
  supersedes the earlier charcoal/emerald previews. Elevated surfaces may use
  #181817 and #20201d with legible warm-gray secondary text.
- All panels, buttons, inputs, document tags and selection states have square
  90-degree corners (border-radius: 0); no pills, circular action buttons or
  rounded message bubbles. Use thin rules, generous spacing, bold grotesk
  headings and restrained uppercase monospace metadata. Keep metadata small
  enough to support the content, without sacrificing readability.
- Visual reference: https://getartcraft.com/apps — studied for bold typography,
  ruled structure, square controls and spacing. Vision keeps its own layout,
  identity and assets. Do not reproduce ArtCraft branding or app illustrations.
- Original PDF pages retain their actual appearance; the cream report shown in
  the new previews is fictional sample content, not a proposed PDF recoloring.
- Verify burnt-orange text contrast on dark surfaces and button-label contrast
  during implementation. Color never provides the only status cue.

### Scale, borders and Luminous Type refinement

The user found the first orange previews too zoomed and heavily framed. Use a
normal desktop scale: approximately 21px logo, 22px chat heading, 30–32px new-chat
heading, 14–16px body text, 11–12px secondary labels and 34–38px controls. These
are layout targets, not a browser zoom setting; preserve readable scaling and
accessible pointer targets. Center the conversation within a 680–720px measure.
Use flexible space around content rather than stretching controls across it.

Remove most container outlines and internal separators. Where needed, borders
are 1 CSS pixel in low-contrast warm gray (#292825 or similar), never broad cream
frames. Reserve stronger contrast for keyboard focus and active interactions.
Use subtle surface changes to separate areas while retaining square corners.

Use **Luminous Type** for active preparation/search/generation status: a narrow
cream highlight moves slowly through warm-gray letters, with restrained orange
warmth. The effect stays inside the glyphs, with minimal bloom. No flashing,
large neon halo, glowing panel, or luminous headings. Treat this as the chosen
visual treatment, not a dependency on an identified third-party component.
Keep the base text legible across the entire animation. Proposed sweep cycle:
2–3 seconds with a calm pause; switch to static readable text under reduced
motion. Announce only meaningful state changes to assistive technology.

Status words follow real events: Preparing search, Searching selected documents,
Writing answer. Actual known page counts remain separate, static text. Shimmer
indicates activity, not measured completion. Failure and completed states stop
the effect. View details retains access to the full processing stages. Keep
actual determinate progress in details when available; avoid a decorative bar
in the primary conversational experience.

## Image previews

Created with the built-in image generation tool, using fictional data. These are
design mockups, not screenshots of a running redesigned app.

1. Workspace: `C:/Users/Saubhagya/.codex/generated_images/01a1b8e7-32c5-73d0-8d76-8cef03fad2e7/exec-d6849dee-b78e-4dc9-920a-7aab605a6ce1.png`
2. Upload/readiness/recovery: `C:/Users/Saubhagya/.codex/generated_images/01a1b8e7-32c5-73d0-8d76-8cef03fad2e7/exec-884f9cce-f715-49ec-a13a-d5ebcaef7d1b.png`

The initial light previews above are superseded by the dark revisions requested
on 8 November 2026. Dark workspace preview:
`C:/Users/Saubhagya/.codex/generated_images/01a1b8e7-32c5-73d0-8d76-8cef03fad2e7/exec-972b0927-1231-45e1-9e28-8c4b038b9b07.png`.
Dark workflow preview:
`C:/Users/Saubhagya/.codex/generated_images/01a1b8e7-32c5-73d0-8d76-8cef03fad2e7/exec-cc211d15-5943-480a-a966-74785f87c005.png`.

Latest square-corner palette previews, superseding all earlier visual treatments:

1. Chat and source viewer:
   `C:/Users/Saubhagya/.codex/generated_images/01a1b8e7-32c5-73d0-8d76-8cef03fad2e7/exec-71143edd-f1ba-4193-b2c4-fe121a7e1e26.png`
2. New conversation and document preparation:
   `C:/Users/Saubhagya/.codex/generated_images/01a1b8e7-32c5-73d0-8d76-8cef03fad2e7/exec-c21e07c5-d440-47a2-9235-069a9a93bb76.png`

Refined desktop-scale chat preview (supersedes the heavier orange treatment):
`C:/Users/Saubhagya/.codex/generated_images/01a1b8e7-32c5-73d0-8d76-8cef03fad2e7/exec-96e91f07-82da-4b20-95e7-12d2d1825c90.png`.
Generated with the built-in image tool; edit prompt: retain palette and square
corners, reduce type/control scale by roughly one third, remove most outlines,
use low-contrast hairlines and whitespace, show Luminous Type on true active
status. Static previews depict a frame of the proposed animation.
Matching refined new-chat/preparation preview:
`C:/Users/Saubhagya/.codex/generated_images/01a1b8e7-32c5-73d0-8d76-8cef03fad2e7/exec-58083c63-1c60-49ce-a56d-e6f26d9e39a9.png`.
Prompt direction: match the refined chat scale, centered restrained heading,
borderless preparation row, luminous active status and a single subtle composer
outline; preserve the palette, square corners and editable question draft.

Generated using the built-in image tool with the uploaded palette as a color
reference. Prompt direction: original editorial document workspace, ink-black
surfaces, cream typography, burnt-orange actions, square geometry, thin rules,
clear source selection and preparation status; no rounded corners, copied
branding, decorative charts or unsupported verification claims. The second
preview uses the first as a visual-system reference. The generated second screen
retains a highlighted recent-chat row; implementation should clear that highlight
for a genuinely new, unsaved conversation.

The sample report's green revenue row is illustrative PDF content, not a promise
of implemented region highlighting. The workflow board groups successive answer
states for explanation; implementation must display the actual current stage.
Sample counts and values are demonstration data, not the user's library.

## Implementation and verification after preview review

1. App shell, default chat route, recent chats and responsive navigation.
2. Explicit source picker and composer, preserving per-question scope and drafts.
3. Upload from chat, coordinated preparation and truthful readiness/recovery.
4. Message presentation, contextual source drawer and answer progress.
5. Library/version details, guided comparisons and saved findings.
6. Settings/data explanations, accessibility and responsive verification.

Make focused commits by logical change. Preserve original README and existing
backend evidence guarantees. Verify with an isolated fictional library and
simulated inference first; do not alter real documents or consume provider quota
for routine UI checks. Exercise new/reopened chats, explicit source selection,
upload/ready/failure, retry/Stop, old-version citations, comparison/export,
authentication, keyboard navigation and mobile layouts. Backend readiness and
scope changes need targeted regression tests as well as browser checks.

Review criteria: at every step users can tell what they selected, what is
happening, whether they can ask, where the answer came from, what was saved,
and what action resolves a failure.
