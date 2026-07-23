---
name: caribbeansaas-weekly-review
description: "Run a guarded weekly discovery, deduplication, public-surface audit, and human-review workflow for CaribbeanSaaS candidates. Use when researching Caribbean-connected online software, preparing a local weekly review packet, or reconciling new leads against the catalog without publishing, contacting, signing up, or changing a deployment."
---

# CaribbeanSaaS Weekly Review

Run this workflow as a local, evidence-based curation aid. It discovers
Caribbean-connected online software and prepares a human review queue; it does
not decide what CaribbeanSaaS publishes.

## Non-negotiable boundary

- Treat every third-party product as read-only. Do not sign up, log in, submit
  forms, start trials, install software, accept terms, make payments, send
  messages, or contact an operator.
- Do not conduct a penetration test, vulnerability scan, port scan, fuzzing,
  credential test, password-reset check, or any other interaction that could
  affect a third-party system.
- Do not commit, push, deploy, create a pull request, or set a record's
  `visibility` to `listed`.
- Store audit evidence, private notes, and review decisions only in the
  machine-local private ledger. Do not store credentials, browser state,
  sensitive personal data, or unnecessary contact information.

## Read the contract first

Read [result-contract.md](references/result-contract.md) before starting a
run. It defines the coordinator's write boundary, clean-catalog gate,
unlisted-projection rule, product-kind enum, evidence tiers, hold rules, and
the exact JSON every worker returns.

## Role routing

The coordinator is the only process allowed to write the private ledger or an
explicitly enabled public-safe projection. Every delegated worker is
read-only.

| Role | Custom agent | Model and effort | Scope |
| --- | --- | --- | --- |
| Discovery | `caribbean_scout` | `gpt-5.6-luna`, `low` | Broad public lead discovery only. |
| Verification | `caribbean_verifier` | `gpt-5.6-terra`, `medium` | Identity, canonical URL, deduplication, and Caribbean-evidence checks. |
| Audit | `caribbean_auditor` | `gpt-5.6-sol`, `high` | Bounded public-surface audit and evidence synthesis. |

If Luna is unavailable in the current Codex surface, use Terra at `low` for
the discovery role and record `modelFallback: "gpt-5.6-terra-low"` in the
packet. Do not silently substitute a model or reasoning level.

## Coordinator sequence

1. Generate a unique run ID and call `review_ledger.py begin-run --run-id
   <run-id>`. This performs the local-storage preflight, holds the stable ledger
   operation mutex through initialization and lifecycle writes, atomically
   acquires the private run lock, snapshots `data/products.json`, and records
   whether the catalog was clean at run start. Stop before network work if it
   fails.
2. Call `review_ledger.py inventory` only after the run lock is acquired. Use
   its full public/private identity inventory (names, aliases, canonical
   domains, and official app-store IDs) as the minimum deduplication set before
   dispatching workers.
3. Give scouts only configured country/territory, language, sector, and source
   slices. Let them return candidate leads, not catalog decisions.
4. Give Terra each distinct lead plus read-only catalog and ledger context.
   It must resolve known duplicates before a public-surface audit begins.
5. Give Sol only candidates that Terra labels `new_candidate` with an official
   source and a coherent identity. Sol returns observations and conservative
   holds; it does not make an inclusion decision.
6. Include the three raw `workerResults` envelopes so the ledger independently
   validates every worker's contract version, role, agent, model, effort,
   status, source references, role payload, and exact all-false side-effect
   attestation. Then ingest the contract-versioned normalized envelope with
   `workerContractsValidated: true`, the same run ID, exact worker provenance,
   coverage, resolved sources, aliases, official app-store IDs, and every
   protected run-level side-effect attestation explicitly `false`. Empty
   successful runs still ingest `candidates: []`. Every candidate uses the same
   private `leadKey` as exactly one Auditor result; the ledger reconciles its
   canonical name and URL, public operator against both identity observations,
   aliases, official app-store IDs, product kind, tier, full source references,
   evidence A/B against the Verifier's matching recommended-tier evidence,
   recommendation, and any worker hold before it can be review-ready. Run any
   permitted unlisted projection, then generate the final packet.
7. Validate the ledger and catalog, call `review_ledger.py finish-run --run-id
   <run-id>` to release the lock, then return the packet location and a concise
   list of human decisions. On a handled failure, write a failure/partial
   packet and release the matching lock; never delete or bypass an unknown
   lock. Do not perform a promotion, outreach, or deployment action.

The ledger persists the fail-closed lifecycle `started → ingested → packeted →
validated → finished`. `finish-run` is not an emergency unlock: it refuses to
release the run lock unless a contract-valid ingest (including an explicitly
empty run), final packet, and successful current ledger/catalog validation have
all completed. A later ingest or unlisted sync invalidates the packet and
validation checkpoints.

## Public-safe projection gate

The scheduled task may run its public-safe unlisted projection only after both
the contract's persisted clean-at-start gate and a fresh current-catalog Git
cleanliness check pass and all three worker statuses are `complete`. A partial
or stopped run still produces a private packet but cannot project. The
projection is a data projection, not a listing: it must use
`visibility: "unlisted"`, remain absent from the visible directory (which
renders `visibility: "listed"` only), and remain uncommitted and undeployed.

## Completion standard

Complete only after the coordinator has validated the private event ledger and
written both Markdown and JSON weekly review packets and released its matching
run lock. State the exact coverage, fallbacks, holds, and gaps. Never call the
outcome a product-quality, security, legal-compliance, or availability
certification.
