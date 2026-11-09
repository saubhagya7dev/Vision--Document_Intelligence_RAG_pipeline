# Current feature matrix

Implementation/validation snapshot: 6 November 2026. Implemented means code
exists; validation scope is separate. See the [current README](../README.md) and
[workspace guide](UX%20redesign%20guide.md) for the later interface redesign.

| Capability | State | Validation / limit |
| --- | --- | --- |
| CPU page rendering, caching, bounded GPU embedding | Implemented | Real RTX 4050 checks; rendering itself is CPU |
| Durable documents, immutable versions, worker jobs | Implemented | Disk/restart/failure tests; one local process |
| Native text, selective OCR and visual fallback | Implemented | English scan smoke; broad language quality unverified |
| BGE text + keyword retrieval | Implemented | Pinned model; routine and real subset checks |
| Original-token MaxSim, rank fusion, coarse reranking | Implemented | Exact scoring checks and measured retrieval subsets |
| Learned starting-tier router | Experimental, off by default | Synthetic training; cross-domain smoke; no proven cost win |
| Grounded claims, citation reference checks, abstention contract | Implemented | References checked; independent semantic support unverified |
| Conversations, ordered answer events, evidence pane | Implemented | Browser fixtures plus one real streaming-adapter check |
| Comparison, findings, JSON/CSV/Markdown exports | Implemented | Workflow/browser tests and fictional provider checks |
| Owner sessions and fixed workspace authorization | Implemented | HTTP tests and isolated browser sign-in/logout |
| Backup/restore to a new library | Implemented | Authenticated archive, real storage/search/history round trip |
| Wheel packaging | Implemented | Packaged import/static/API/session smoke |
| Frozen container recipe | Implemented, unverified runtime | No Docker executable available |
| Multi-user RBAC, invitations and tenant administration | Planned | Owner token represents one owner, not separate users |
| Shared TLS deployment | Unverified | No supported shared profile is claimed |
| Independent semantic-support evaluation | Unverified | Same-model estimates from Phase 4 are not independent |
| Representative answer correctness and abstention | Partial measurements | Small fictional samples; provider failures interrupt remaining checks |
| RTX 3050 / stronger desktop hardware comparison | Unmeasured | Only RTX 4050 Laptop available; no invented estimates |
| Calculated metrics, region QA, automated version diffs | Planned | Outside the completed evidence-comparison workflow |
| Retrieval similarity maps | Planned | No grounding/correctness claims from heatmaps |

See [Phase 7 guide](Phase%207%20guide.md), [benchmark](Phase%207%20benchmark.md),
and [release gates](phase7-release-gates.json). Unverified gates are not made green
by routine tests or mocked inference.
