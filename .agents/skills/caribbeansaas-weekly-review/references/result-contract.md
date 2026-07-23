# Weekly review contract

## Coordinator rules

The coordinator alone may write. All workers are read-only and return their
results to the coordinator; they never edit a ledger, catalog, packet,
repository, deployment, or third-party system.

| Item | Path | Access |
| --- | --- | --- |
| Public catalog | `data/products.json` | Read-only until the scheduled projection stage. |
| Private ledger | `private/reviews/` | Coordinator only; must be Git-ignored. |
| Operation mutex | `private/reviews/ledger.lock` | Stable CLI process mutex; never delete it. |
| Active run lock | `private/reviews/run.lock` | Coordinator only; one run at a time. |
| Catalog snapshots | `private/reviews/snapshots/products-<sha256>.json` | Coordinator only; must be Git-ignored. |
| Review packet | `private/reviews/review-packets/review-<run-id>.{md,json}` | Coordinator only; must be Git-ignored. |

Before any source lookup, the coordinator must:

1. Confirm every private path is Git-ignored, outside `dist/`, `data/`, and
   `assets/`, and excluded from the public build.
2. Generate a unique run ID and call `review_ledger.py begin-run --run-id
   <run-id>`. The CLI holds the stable `ledger.lock` mutex through
   initialization and lifecycle writes, atomically acquires `run.lock`,
   snapshots the catalog, and persists the catalog digest and clean/dirty state
   at run start.
3. If another lock exists, stop. Never delete, overwrite, reuse, or bypass an
   unknown lock. Do not use `--allow-dirty-catalog` outside an isolated test
   fixture.
4. Call `review_ledger.py inventory` and load its complete public/private
   identity inventory before dispatching any worker. A dirty-at-start catalog
   disables public projection for the whole run even if its Git state later
   changes, but private work continues.

If `begin-run` fails a storage or lock check, stop without fetching, ingesting,
syncing, committing, pushing, deploying, or writing a substitute file
elsewhere.
If the catalog is dirty, record `catalog_dirty_at_start`, continue private-only,
and skip only `sync-unlisted`.

Run in this order: scout public leads; verifier identity, canonical URL, and
deduplication; auditor public-surface observations; then coordinator-only
validation, ledger ingest, any permitted scheduled unlisted projection, final
private packet creation, and ledger/catalog validation. An exact official-
domain or official-app-store-ID duplicate is not a new candidate. An existing
`visibility: "unlisted"` record is still known history and suppresses
accidental reuse.

The weekly task enables the projection stage only after both the persisted
clean-catalog-at-start gate and a fresh current-catalog Git cleanliness check
pass and all three required workers have status `complete`. A partial or
stopped run remains private. The ledger adds only sanitized records with
`visibility: "unlisted"`; the visible directory renders exactly
`visibility: "listed"`. The task must never write `visibility: "listed"`,
modify an existing catalog record, commit, push, deploy, or contact anyone.

Use one unique run ID throughout the stateful run. `ingest` reads it from the
normalized envelope, while `validate` derives the active run from the lock:

```text
review_ledger.py begin-run --run-id <run-id>
review_ledger.py inventory
review_ledger.py ingest <normalized-run.json>
review_ledger.py sync-unlisted --run-id <run-id>  # only if both clean gates pass
review_ledger.py queue --run-id <run-id>
review_ledger.py validate
review_ledger.py finish-run --run-id <run-id>
```

The coordinator must ingest an envelope with `candidates: []` for a successful
run with no new candidates so provenance and coverage are still recorded. On a
handled failure after `begin-run`, record the partial/failure envelope, write
the packet when safe, validate, and release only the matching lock with
`finish-run`. An abrupt failure intentionally leaves the lock in place for
human inspection before any later run.

The private ledger records `started → ingested → packeted → validated →
finished` as an authoritative fail-closed lifecycle. `finish-run` rechecks the
matching packet and current ledger/catalog validation before releasing the
lock. Re-ingest or `sync-unlisted` returns the run to `ingested`, requiring a
fresh packet and validation. There is no force-unlock path in the automation.

Never sign up, log in, submit a form, accept terms, contact an operator, start
a trial, make a payment, install software, use credentials, mutate an API, or
conduct a port scan, vulnerability scan, fuzzing, password-reset, credential,
or exploit test. Respect robots, source terms, paywalls, CAPTCHAs, rate limits,
and access restrictions. Do not bypass them.

## Evidence and hold rules

| Tier | Minimum evidence | Meaning |
| --- | --- | --- |
| A | Official site/legal page, official registry, or official announcement directly identifies Caribbean company, address, team, founder, or build origin. | Supports a narrow Caribbean-built claim after human approval. |
| B | Official product source plus reliable independent corroboration identifies the same Caribbean company/founder. | Supports carefully worded Caribbean-built copy after human approval. |
| C | Official source proves a named Caribbean market or workflow but not origin/team. | Market connection only; human fit and wording hold. |
| D | Search result, unaffiliated directory/social post, country TLD, or RDAP record. | Lead only; never a listing claim. |

Require Tier A or B for an unqualified Caribbean-built statement. Do not infer
origin from a name, TLD, design, RDAP, or unaffiliated directory. Use a hold,
not an automatic rejection, for possible duplicates; non-software or unclear
fit; unavailable/parked/access-blocked official sources; identity conflict;
insufficient Caribbean evidence; serious public risk; sensitive domains
(payments, credit, crypto, health, legal, children/education, identity,
biometrics, safety-sensitive marketplaces); restricted interaction; source
restrictions; sensitive data; or a budget/rate/time cap. Call a source
`observed unavailable` or `access_blocked`, never permanently dead.

The auditor uses only public, credential-free pages and ordinary GET/HEAD or
anonymous rendering. It records time-bounded observations about identity and
software fit, sampled availability, claim support, privacy/terms transparency,
passive HTTPS/header/mixed-content/public-exposure/tracker signals, and basic
desktop/mobile rendering. It is not a product-quality, security,
legal-compliance, availability, or endorsement certification.

Use only these public `productKind` values: `saas`, `mobile_app`,
`digital_platform`, `marketplace`, `api_or_developer_tool`, `web_tool`,
`software_enabled_service`, and `open_source_project`. Omit the field when the
public evidence cannot classify it; never invent a fallback enum.

## Model roles

| Role | Agent | Model | Effort | Output |
| --- | --- | --- | --- | --- |
| Broad discovery | `caribbean_scout` | `gpt-5.6-luna` | `low` | Leads, sources, query coverage, gaps. |
| Verification/dedupe | `caribbean_verifier` | `gpt-5.6-terra` | `medium` | Identity, canonical URL, duplicates, fit, evidence tier. |
| Audit/synthesis | `caribbean_auditor` | `gpt-5.6-sol` | `high` | Bounded observations, holds, review queue. |

If Luna is unavailable, use Terra at `low` only for discovery and set
`worker.modelFallback` to `gpt-5.6-terra-low`. Do not silently substitute any
other model or effort.

## Default weekly coverage and caps

Use three parallel scout batches, then wait before verification. Every weekly
run performs a general online-software query for each territory slice and an
all-region query for every sector lane. Rotate deeper sector-by-territory
passes so every lane receives a deep pass at least once every four runs.

- Territory slices: The Bahamas, Anguilla, Antigua and Barbuda, Aruba,
  Barbados, Belize, Bermuda, Bonaire, British Virgin Islands, Cayman Islands,
  Cuba, Curaçao, Dominica, Dominican Republic, French Guiana, Grenada,
  Guadeloupe, Guyana, Haiti, Jamaica, Martinique, Montserrat, Puerto Rico,
  Saint Barthélemy, Saint Kitts and Nevis, Saint Lucia, Saint Martin,
  Saint Vincent and the Grenadines, Sint Maarten, Suriname, Trinidad and
  Tobago, Turks and Caicos Islands, and the US Virgin Islands.
- Language slices: English, Spanish, French, Haitian Creole, Dutch, and
  Papiamento, using local spelling and demonym aliases where useful.
- Sector lanes: finance/payments; business operations/accounting/payroll;
  tourism/travel/transport; education; health/legal/regulatory; creator
  economy/commerce/marketplaces; developer tools/AI/cyber/open source; and
  government/agriculture/logistics/energy.
- Source lanes: official sites and app stores; government, university,
  accelerator, incubator, conference, and demo-day portfolios; reputable
  regional reporting; package registries and GitHub tied to an official owner;
  and directories/social results as leads only.

Default hard caps are 80 search queries, 180 source-page reads, 40 distinct
leads, 25 audited new candidates, two retries for a transient source failure,
and 50 minutes wall time. Reuse cached results inside a run. When a cap is
reached, finish the safe checkpoint and packet, label the run `partial`, and
list every uncovered slice rather than silently narrowing coverage.

## Worker transport

Every worker returns exactly one JSON object inside one fenced `json` block and
no prose outside it. Use ISO 8601 UTC timestamps, public-source URLs only, and
evidence-bounded wording. Omit unknown values instead of inventing them. Every
worker sets every side-effect attestation value to `false`.

### Common envelope

```json
{
  "contractVersion": "1.0",
  "role": "scout | verifier | auditor",
  "runId": "YYYY-MM-DD-unique-run-id",
  "worker": {
    "agent": "caribbean_scout | caribbean_verifier | caribbean_auditor",
    "model": "gpt-5.6-luna | gpt-5.6-terra | gpt-5.6-sol",
    "reasoningEffort": "low | medium | high",
    "modelFallback": null
  },
  "status": "complete | partial | stopped",
  "scope": {
    "territorySlices": ["string"],
    "languageSlices": ["string"],
    "sectorSlices": ["string"],
    "candidateIds": ["string"],
    "startedAt": "2026-07-23T00:00:00Z",
    "finishedAt": "2026-07-23T00:00:00Z"
  },
  "sideEffectAttestation": {
    "localWrites": false,
    "catalogWrites": false,
    "repositoryActions": false,
    "deploymentActions": false,
    "contactsMade": false,
    "accountsCreated": false,
    "formsSubmitted": false,
    "paymentsOrTrialsStarted": false,
    "authenticatedOrMutationTesting": false
  },
  "sources": [],
  "holds": [],
  "errors": [],
  "result": {}
}
```

Use this source object:

```json
{
  "sourceId": "src-001",
  "url": "https://example.com/",
  "sourceClass": "official_site | official_app_store | official_registry | official_announcement | accelerator | government_program | university | conference | reputable_press | package_registry | github | directory | social | search_result | other",
  "capturedAt": "2026-07-23T00:00:00Z",
  "access": "public_read_only | unavailable | access_blocked | restricted",
  "supports": ["identity | operator | product_purpose | product_kind | caribbean_connection | privacy_policy | terms | availability | security_observation | ux_observation"],
  "summary": "Concise public fact or observation; never a copied page body.",
  "confidence": "high | medium | low"
}
```

Use this hold object:

```json
{
  "candidateKey": "normalized-name-or-id",
  "code": "duplicate_known | possible_duplicate | not_eligible | official_source_unavailable | access_blocked | identity_conflict | caribbean_evidence_insufficient | public_risk | restricted_interaction_required | sensitive_domain_review | storage_safety_failure | catalog_dirty_at_start | run_locked | budget_cap | rate_limited | other",
  "severity": "info | caution | high",
  "reason": "Evidence-based explanation without speculation.",
  "evidenceSourceIds": ["src-001"],
  "safeNextHumanAction": "Bounded next step or empty string.",
  "terminalForThisRun": true
}
```

## Role payloads

### Scout `result`

```json
{
  "queries": [{
    "queryId": "q-001",
    "territorySlice": "Bahamas",
    "languageSlice": "English",
    "sectorSlice": "fintech",
    "query": "Bahamian fintech app",
    "sourceClassTarget": "search_result",
    "executedAt": "2026-07-23T00:00:00Z",
    "outcome": "complete | partial | restricted | rate_limited"
  }],
  "leads": [{
    "leadKey": "normalized-temporary-key",
    "displayName": "Candidate name",
    "candidateUrls": ["https://example.com/"],
    "sourceIds": ["src-001"],
    "territoryHints": ["Bahamas"],
    "languageHints": ["English"],
    "productKindHints": ["digital_platform"],
    "sectorHints": ["fintech"],
    "aliases": ["Alternate spelling"],
    "whyItIsALead": "Factual reason tied to source IDs.",
    "confidence": "low | medium | high"
  }],
  "coverage": {
    "searchedSlices": ["Bahamas|English|fintech"],
    "unsearchedSlices": [],
    "reasonForGaps": []
  }
}
```

The scout discovers leads only. It does not decide tier, dedupe, inclusion, or
audit outcome.

### Verifier `result`

```json
{
  "entities": [{
    "leadKey": "normalized-temporary-key",
    "resolution": "new_candidate | duplicate_known | possible_duplicate | existing_recheck | hold",
    "canonical": {
      "officialUrl": "https://example.com/",
      "finalUrl": "https://www.example.com/",
      "canonicalHost": "example.com",
      "officialAppStoreIds": ["public-id-or-empty"],
      "companyName": "Public company name or empty string",
      "productName": "Public product name",
      "aliases": ["Alias"]
    },
    "duplicateSignals": [{
      "type": "exact_domain | exact_app_store_id | exact_alias | fuzzy_name | same_company | redirect_match",
      "matchedRecord": "public-or-private-id-or-empty",
      "confidence": "high | medium | low",
      "explanation": "Factual explanation."
    }],
    "softwareFit": {
      "classification": "eligible_online_software | not_eligible | unclear",
      "productKind": "saas | mobile_app | digital_platform | marketplace | api_or_developer_tool | web_tool | software_enabled_service | open_source_project",
      "reason": "Evidence-based explanation."
    },
    "caribbeanEvidence": [{
      "tier": "A | B | C | D | unknown",
      "claim": "Narrow supported claim.",
      "sourceIds": ["src-001"],
      "confidence": "high | medium | low"
    }],
    "recommendedCaribbeanTier": "A | B | C | D | unknown",
    "auditEligibility": "eligible | hold",
    "auditTargets": ["https://example.com/"],
    "outstandingQuestions": ["string"]
  }]
}
```

Set `auditEligibility` to `eligible` only for a `new_candidate`, coherent
official identity, and eligible online-software fit. Tier C/D may be observed
only to document a hold, never to justify a Caribbean-built claim.

### Auditor `result`

```json
{
  "audits": [{
    "leadKey": "normalized-temporary-key",
    "canonicalOfficialUrl": "https://example.com/",
    "auditScope": "public_credential_free_surface_only",
    "observed": {
      "identityAndFit": {"operator": "Public name or empty", "productPurpose": "Source-supported summary", "productKind": "saas | mobile_app | digital_platform | marketplace | api_or_developer_tool | web_tool | software_enabled_service | open_source_project", "sourceIds": ["src-001"]},
      "operations": {"sampledAt": "2026-07-23T00:00:00Z", "rootStatus": "2xx | 3xx | 4xx | 5xx | unavailable | access_blocked | unknown", "finalUrl": "https://example.com/", "httpsObserved": true, "certificateObservation": "valid_at_sample | invalid_or_mismatch | not_checked | unknown", "supportOrContactPath": "URL-or-empty", "sourceIds": ["src-001"]},
      "claimConcordance": [{"claimType": "name | operator | description | category | country | caribbean_connection", "proposedClaim": "Narrow fact", "supported": true, "sourceIds": ["src-001"], "note": "Caveat or empty"}],
      "privacyAndTerms": {"privacyPolicy": "present | absent | inaccessible | not_applicable | unknown", "terms": "present | absent | inaccessible | not_applicable | unknown", "publicContactIdentity": "present | absent | unknown", "sourceIds": ["src-001"]},
      "passivePublicPosture": {"headersObserved": ["Strict-Transport-Security"], "mixedContentObserved": "yes | no | not_checked | unknown", "publicExposureClues": ["string"], "landingPageTrackers": ["string"], "sourceIds": ["src-001"]},
      "publicUxSmoke": {"desktopRender": "observed | blocked | not_checked", "mobileRender": "observed | blocked | not_checked", "obviousBrokenNavigation": "yes | no | unknown", "notes": "Observation only", "sourceIds": ["src-001"]}
    },
    "findings": [{"code": "unsupported_claim | missing_privacy_transparency | unavailable_source | public_risk | sensitive_domain | other", "severity": "info | caution | high", "statement": "Narrow evidence-based observation.", "sourceIds": ["src-001"]}],
    "recommendedOutcome": "ready_for_human_review | hold",
    "holdCodes": ["string"],
    "proposedPublicSafeSummary": "Evidence-bounded sentence or empty string",
    "outstandingQuestions": ["string"],
    "limitations": ["Public credential-free observation only."]
  }],
  "synthesis": {
    "readyForHumanReviewLeadKeys": ["normalized-temporary-key"],
    "holdLeadKeys": ["normalized-temporary-key"],
    "coverageGaps": ["string"],
    "humanDecisionsRequired": ["string"]
  }
}
```

The auditor may recommend only `ready_for_human_review` or `hold`; it never
sets a visibility or makes a final curation decision.

## Coordinator-normalized ledger input

For every non-duplicate audit result, the coordinator must create one private
normalized run envelope and pass it to `review_ledger.py ingest`. This is the
only write-shaped input the scheduled workflow sends to the ledger:

```json
{
  "contractVersion": "1.0",
  "runId": "YYYY-MM-DD-unique-run-id",
  "workerContractsValidated": true,
  "modelProvenance": {
    "models": ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
    "workers": [{
      "contractVersion": "1.0",
      "role": "scout",
      "agent": "caribbean_scout",
      "model": "gpt-5.6-luna",
      "reasoningEffort": "low",
      "status": "complete",
      "modelFallback": null
    }, {
      "contractVersion": "1.0",
      "role": "verifier",
      "agent": "caribbean_verifier",
      "model": "gpt-5.6-terra",
      "reasoningEffort": "medium",
      "status": "complete",
      "modelFallback": null
    }, {
      "contractVersion": "1.0",
      "role": "auditor",
      "agent": "caribbean_auditor",
      "model": "gpt-5.6-sol",
      "reasoningEffort": "high",
      "status": "complete",
      "modelFallback": null
    }],
    "fallbacks": []
  },
  "coverage": {
    "searchedSlices": ["Bahamas|English|business software"],
    "unsearchedSlices": [],
    "reasonForGaps": []
  },
  "sourceFailures": [],
  "workerResults": [
    {
      "contractVersion": "1.0",
      "role": "scout",
      "runId": "YYYY-MM-DD-unique-run-id",
      "worker": {
        "agent": "caribbean_scout",
        "model": "gpt-5.6-luna",
        "reasoningEffort": "low",
        "modelFallback": null
      },
      "status": "complete",
      "scope": {
        "territorySlices": ["Bahamas"],
        "languageSlices": ["English"],
        "sectorSlices": ["business software"],
        "candidateIds": []
      },
      "sideEffectAttestation": {
        "localWrites": false,
        "catalogWrites": false,
        "repositoryActions": false,
        "deploymentActions": false,
        "contactsMade": false,
        "accountsCreated": false,
        "formsSubmitted": false,
        "paymentsOrTrialsStarted": false,
        "authenticatedOrMutationTesting": false
      },
      "sources": [],
      "holds": [],
      "errors": [],
      "result": {
        "queries": [],
        "leads": [],
        "coverage": {
          "searchedSlices": [],
          "unsearchedSlices": [],
          "reasonForGaps": []
        }
      }
    }
  ],
  "sideEffectAttestation": {
    "accountsCreated": false,
    "authenticatedOrMutationTesting": false,
    "catalogWrites": false,
    "contactsMade": false,
    "deploymentActions": false,
    "formsSubmitted": false,
    "listedVisibilityWrites": false,
    "paymentsOrTrialsStarted": false,
    "repositoryActions": false
  },
  "sources": [{
    "sourceId": "src-001",
    "url": "https://official.example/about",
    "sourceClass": "official_site",
    "capturedAt": "2026-07-23T00:00:00Z",
    "summary": "Official product and Caribbean-origin support."
  }, {
    "sourceId": "src-002",
    "url": "https://independent.example/profile",
    "sourceClass": "reputable_press",
    "capturedAt": "2026-07-23T00:00:00Z",
    "summary": "Independent identity and origin corroboration."
  }],
  "candidates": [{
    "name": "Required public product name",
    "websiteUrl": "https://official.example",
    "companyName": "Public operator",
    "tagline": "Public-safe one-line description",
    "description": "Public-safe source-supported description",
    "country": "Primary Caribbean country",
    "countries": ["Primary Caribbean country"],
    "category": "Public category",
    "industry": "Public industry",
    "tags": ["Public tag"],
    "productKind": "digital_platform",
    "aliases": ["Alternate public product spelling"],
    "officialAppStoreIds": ["apple:123456789"],
    "caribbeanConnection": "Narrow public evidence claim",
    "caribbeanEvidenceTier": "B",
    "recommendation": "ready_for_human_review | hold",
    "confidence": 0.91,
    "sourceIds": ["src-001", "src-002"],
    "evidence": {
      "A": {"url": "https://official.example/about", "title": "Optional", "summary": "Official support"},
      "B": {"url": "https://independent.example/profile", "title": "Optional", "summary": "Independent corroboration"}
    },
    "privateReview": {
      "runId": "YYYY-MM-DD-unique-run-id",
      "auditScope": "public_credential_free_surface_only",
      "holdCodes": [],
      "sourceIds": ["src-001", "src-002"],
      "limitations": ["Public observation only"]
    }
  }]
}
```

The abbreviated `workerResults` example above shows the scout envelope shape;
the actual array must contain exactly one scout, verifier, and auditor envelope
using the full role payloads defined earlier. The ledger rejects a
missing/unknown contract version, `workerContractsValidated` other than
explicit `true`, missing or mismatched worker role/agent/model/effort/status
provenance, malformed role payloads, candidate-local source objects, worker or
run-level source references absent from the normalized matrix, absent coverage,
or any worker/run side-effect attestation field that is missing, unknown, or
not explicitly `false`. `name` and `websiteUrl` are required for private ingest.
Exact canonical domains and normalized official app-store IDs suppress
rediscovery; an exact name or alias on a different identity becomes a
possible-duplicate hold rather than an automatic merge. Projection additionally
requires the public operator, tagline, description, country, category,
industry, Caribbean-connection wording, and one of the eight allowed
`productKind` values. The ledger permits a record to become
`ready_for_human_review` only when `recommendation` equals
`ready_for_human_review`, `confidence` is at least `0.8`, Caribbean evidence is
Tier A or B, and evidence A and B have distinct valid public URLs. Tier A
requires an official source plus a second distinct public source. Tier B
requires an official source plus reliable independent corroboration. Otherwise
ingest it as a private hold. The ledger sanitizes the allowed public fields and,
during the scheduled sync, appends only `visibility: "unlisted"`; it never
projects `privateReview`, evidence, confidence, contacts, or audit data. Never
place a secret, cookie, browser state, form input, or unnecessary PII in either
part of the normalized object.

## Acceptance and packet

Accept a worker result only if its envelope and role payload conform; every
source reference resolves; all side-effect fields are `false`; no secret,
cookie, credential, private path, unredacted contact detail, or unsupported
claim appears; and the worker made no write. Reject malformed worker output
without partial ledger ingest.

Write private Markdown and JSON packets with the run ID, source matrix,
model/effort/fallback use, query/source counts, coverage gaps, source failures,
leads, duplicates, holds grouped by reason, human-review queue, projected
unlisted IDs, and human decisions required. End with an explicit attestation:
no account, form, contact, third-party mutation, `visibility: "listed"`, Git
action, or deployment occurred. Release the matching run lock only after the
packet and validation complete.
