# Documentation

Start with the guide that matches the task. Historical phase guides and duplicate
research versions were merged on 9 November 2026; the old files were removed.

| Document | Purpose |
| --- | --- |
| [Upgrade history](Upgrade%20history.md) | Original vs current version, pictures, all phases and implementation changes |
| [Usage](Usage.md) | Setup/CUDA, chat, comparisons, data controls, backup and migration |
| [Architecture](Architecture.md) | Storage, jobs, extraction, retrieval, grounding and design decisions |
| [Validation](Validation.md) | Recorded results, tests, release commands and known limits |
| [Research](Research.md) | Merged previous research, original baseline and deferred ideas |

## Current status

Updated **12 November 2026**. The current project includes the charcoal public
landing and animated architecture map, a dashboard backed by saved library data,
and a compact research desk with permanent searchable history, browser-local pins,
a resizable evidence reader and stable pending/completed turn alignment. Answers
use full responses by default with bounded automatic provider recovery.

[Upgrade history](Upgrade%20history.md) shows old/current screenshots and the
latest implementation milestones. [Validation](Validation.md#recorded-checks)
distinguishes the last recorded full Python suite from later targeted checks.

The local phases and later chat-first workspace are implemented. The verified
profile is one owner/process with SQLite and persistent embedded Qdrant. Learned
routing remains experimental/off by default; optional calculations, region QA,
automatic diffs and similarity maps are not shipped analytical features.

Production/shared readiness remains unverified. Provider checkpoints are partial,
the recorded audit has an unresolved advisory, and independent semantic support,
broader answer quality and other hardware/deployment validation are incomplete.
See [feature status](Validation.md#feature-status) and [release gates](Validation.md#release-gates-and-security-limits).

## Supporting files

- `assets/`: only the screenshots and plots used by these guides.
- `evidence/`: benchmark/router/checkpoint inputs and release records needed by scripts.
- [Historical evidence](evidence/history.json): older JSON payloads merged unchanged,
  keyed by their former filenames, including the November workspace verification.
- The original October screenshots remain in the repository's `Screenshots/` folder.

The evidence files describe recorded runs and can be stale; moving them is not a
new verification run. The project [README](../README.md) remains the setup entry point.
