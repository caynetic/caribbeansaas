---
name: caribbeansaas-weekly-review
description: "Run a guarded weekly discovery, deduplication, public-surface audit, human-review, and optional public-data publication workflow for CaribbeanSaaS candidates. Use when researching Caribbean-connected online software, preparing a local weekly review packet, reconciling new leads against the catalog, or publishing validated public-safe unlisted additions without making them active listings."
---

# CaribbeanSaaS Weekly Review

Run this workflow as a local, evidence-based curation aid. It discovers
Caribbean-connected online software and prepares a human review queue; it does
not decide what becomes an active CaribbeanSaaS listing.

## Non-negotiable boundary

- Treat every third-party product as read-only. Do not sign up, log in, submit
  forms, start trials, install software, accept terms, make payments, send
  messages, or contact an operator.
- Do not conduct a penetration test, vulnerability scan, port scan, fuzzing,
  credential test, password-reset check, or any other interaction that could
  affect a third-party system.
- Workers must not commit, push, deploy, create a pull request, or perform any
  repository action. The coordinator may use only the guarded publication
  sequence below to commit and push a proven append-only
  `data/products.json` projection. Never set a record's `visibility` to
  `listed`, force-push, resolve a conflict automatically, or deploy through a
  separate direct-upload path.
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

1. Generate a unique run ID. For a scheduled publication run, first require a
   clean `main` checkout aligned with `origin/main`, then call
   `review_ledger.py begin-run --run-id <run-id> --publish-unlisted`. This
   performs the local-storage and repository preflight, holds the stable ledger
   operation mutex through initialization and lifecycle writes, atomically
   acquires the private run lock, snapshots `data/products.json`, and records
   the immutable Git/catalog starting state. A dirty, non-main, or diverged
   checkout may continue private-only but cannot publish. Stop before network
   research if lock or storage validation fails.
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
   protected worker/research side-effect attestation explicitly `false`.
   Coordinator Git preflight/publication facts are recorded separately and do
   not change those worker attestations. Empty successful runs still ingest
   `candidates: []`. Every candidate uses the same
   private `leadKey` as exactly one Auditor result; the ledger reconciles its
   canonical name and URL, public operator against both identity observations,
   aliases, official app-store IDs, product kind, tier, full source references,
   evidence A/B against the Verifier's matching recommended-tier evidence,
   recommendation, and any worker hold before it can be review-ready. Run any
   permitted unlisted projection, then generate and validate the private
   packet.
7. For a publication-enabled run, call `prepare-publication` with the matching
   run and unique attempt ID. It must write a private plan before any Git
   action and independently prove an append-only catalog delta containing
   exactly this run's sanitized unlisted additions, with no other worktree,
   branch, base, schema, or lifecycle drift. A zero-addition run records a
   terminal no-change result. Any failed proof stops publication.
8. Call `review_ledger.py finish-run --run-id <run-id>` to release the matching
   run lock. On a handled research failure, write a failure/partial packet and
   release the matching lock; never delete or bypass an unknown lock.
9. Only for a prepared publication plan, run the full repository checks, stage
   only `data/products.json`, re-prove the staged path and catalog digest,
   create a normal commit whose parent is the planned base, and push that exact
   commit to `origin/main` without force. Let the connected Cloudflare Pages
   project deploy the GitHub commit; do not upload a separate bundle. Verify
   the live JSON contains the planned IDs as unlisted, the Open Data explorer
   exposes them, and the homepage/structured data still exclude them. Record
   the terminal Git, deployment-source commit, live-catalog digest, and
   live-verification result with `record-publication` in the private receipt.
   A conflict, timeout, failed check, mismatched SHA, or unknown deployment
   state is a recorded stop for human recovery, not an automatic retry.

The ledger persists a fail-closed review lifecycle and, when enabled, a
separate idempotent publication attempt. `finish-run` is not an emergency
unlock: it refuses to release the run lock unless a contract-valid ingest
(including an explicitly empty run), final packet, successful current
ledger/catalog validation, and a resolved publication plan have completed. A
later ingest or unlisted sync invalidates the packet and validation
checkpoints.

## Public-safe projection gate

The scheduled task may run its public-safe unlisted projection only after the
contract's immutable clean/aligned-start proof, a fresh exact-worktree check,
and all three `complete` worker results pass. A partial or stopped run still
produces a private packet but cannot project or publish. The projection is a
public-data record, not a listing: it must use `visibility: "unlisted"` and
remain absent from the homepage directory and product structured data, which
render `visibility: "listed"` only. Publication is limited to the exact
append-only projection proved in the private receipt.

## Completion standard

Complete only after the coordinator has validated the private event ledger and
written both Markdown and JSON weekly review packets, resolved the publication
plan, released its matching run lock, and recorded any attempted Git/Cloudflare
outcome. State the exact coverage, fallbacks, holds, publication status, and
gaps. Never call the outcome a product-quality, security, legal-compliance, or
availability certification.
