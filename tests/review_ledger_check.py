from __future__ import annotations

import copy
import fcntl
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER = (
    ROOT
    / ".agents"
    / "skills"
    / "caribbeansaas-weekly-review"
    / "scripts"
    / "review_ledger.py"
)


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def safe_attestation() -> dict[str, bool]:
    return {
        "accountsCreated": False,
        "authenticatedOrMutationTesting": False,
        "catalogWrites": False,
        "contactsMade": False,
        "deploymentActions": False,
        "formsSubmitted": False,
        "listedVisibilityWrites": False,
        "paymentsOrTrialsStarted": False,
        "repositoryActions": False,
    }


def safe_worker_attestation() -> dict[str, bool]:
    return {
        "accountsCreated": False,
        "authenticatedOrMutationTesting": False,
        "catalogWrites": False,
        "contactsMade": False,
        "deploymentActions": False,
        "formsSubmitted": False,
        "localWrites": False,
        "paymentsOrTrialsStarted": False,
        "repositoryActions": False,
    }


def sample_provenance(scout_model: str = "gpt-5.6-luna") -> dict:
    return {
        "models": [scout_model, "gpt-5.6-terra", "gpt-5.6-sol"],
        "workers": [
            {
                "contractVersion": "1.0",
                "role": "scout",
                "agent": "caribbean_scout",
                "model": scout_model,
                "reasoningEffort": "low",
                "status": "complete",
                "modelFallback": (
                    "gpt-5.6-terra-low"
                    if scout_model == "gpt-5.6-terra"
                    else None
                ),
            },
            {
                "contractVersion": "1.0",
                "role": "verifier",
                "agent": "caribbean_verifier",
                "model": "gpt-5.6-terra",
                "reasoningEffort": "medium",
                "status": "complete",
                "modelFallback": None,
            },
            {
                "contractVersion": "1.0",
                "role": "auditor",
                "agent": "caribbean_auditor",
                "model": "gpt-5.6-sol",
                "reasoningEffort": "high",
                "status": "complete",
                "modelFallback": None,
            },
        ],
        "fallbacks": [],
    }


def sample_worker_results(
    run_id: str,
    sources: list[dict],
    provenance: dict,
) -> list[dict]:
    role_results = {
        "scout": {
            "queries": [],
            "leads": [],
            "coverage": {
                "searchedSlices": [],
                "unsearchedSlices": [],
                "reasonForGaps": [],
            },
        },
        "verifier": {"entities": []},
        "auditor": {
            "audits": [],
            "synthesis": {
                "readyForHumanReviewLeadKeys": [],
                "holdLeadKeys": [],
                "coverageGaps": [],
                "humanDecisionsRequired": [],
            },
        },
    }
    results = []
    for worker_index, provenance_worker in enumerate(provenance["workers"]):
        role = provenance_worker["role"]
        results.append(
            {
                "contractVersion": "1.0",
                "role": role,
                "runId": run_id,
                "worker": {
                    "agent": provenance_worker["agent"],
                    "model": provenance_worker["model"],
                    "reasoningEffort": provenance_worker["reasoningEffort"],
                    "modelFallback": provenance_worker["modelFallback"],
                },
                "status": provenance_worker["status"],
                "scope": {
                    "territorySlices": ["Bahamas"],
                    "languageSlices": ["English"],
                    "sectorSlices": ["general"],
                    "candidateIds": [],
                },
                "sideEffectAttestation": safe_worker_attestation(),
                "sources": copy.deepcopy(sources) if worker_index == 2 else [],
                "holds": [],
                "errors": [],
                "result": copy.deepcopy(role_results[role]),
            }
        )
    return results


def sample_populated_worker_results(
    run_id: str,
    sources: list[dict],
    provenance: dict,
) -> list[dict]:
    results = sample_worker_results(run_id, sources, provenance)
    source_id = sources[0]["sourceId"]
    for result in results:
        result["sources"] = copy.deepcopy(sources)
    results[0]["result"] = {
        "queries": [
            {
                "queryId": "q-001",
                "territorySlice": "Bahamas",
                "languageSlice": "English",
                "sectorSlice": "business software",
                "query": "Bahamian business software",
                "sourceClassTarget": "search_result",
                "executedAt": "2026-07-23T12:00:00Z",
                "outcome": "complete",
            }
        ],
        "leads": [
            {
                "leadKey": "example-product",
                "displayName": "Example Product",
                "candidateUrls": ["https://new-product.example/"],
                "sourceIds": [source_id],
                "territoryHints": ["Bahamas"],
                "languageHints": ["English"],
                "productKindHints": ["digital_platform"],
                "sectorHints": ["business software"],
                "aliases": [],
                "whyItIsALead": "The official source describes online software.",
                "confidence": "high",
            }
        ],
        "coverage": {
            "searchedSlices": ["Bahamas|English|business software"],
            "unsearchedSlices": [],
            "reasonForGaps": [],
        },
    }
    results[1]["result"] = {
        "entities": [
            {
                "leadKey": "example-product",
                "resolution": "new_candidate",
                "canonical": {
                    "officialUrl": "https://new-product.example/",
                    "finalUrl": "https://new-product.example/",
                    "canonicalHost": "new-product.example",
                    "officialAppStoreIds": [],
                    "companyName": "Example Product Ltd.",
                    "productName": "Example Product",
                    "aliases": [],
                },
                "duplicateSignals": [],
                "softwareFit": {
                    "classification": "eligible_online_software",
                    "productKind": "digital_platform",
                    "reason": "The public source describes browser-delivered software.",
                },
                "caribbeanEvidence": [
                    {
                        "tier": "A",
                        "claim": "The public source connects the product to The Bahamas.",
                        "sourceIds": [source_id],
                        "confidence": "high",
                    }
                ],
                "recommendedCaribbeanTier": "A",
                "auditEligibility": "eligible",
                "auditTargets": ["https://new-product.example/"],
                "outstandingQuestions": [],
            }
        ]
    }
    results[2]["result"] = {
        "audits": [
            {
                "leadKey": "example-product",
                "canonicalOfficialUrl": "https://new-product.example/",
                "auditScope": "public_credential_free_surface_only",
                "observed": {
                    "identityAndFit": {
                        "operator": "Example Product Ltd.",
                        "productPurpose": "Browser-delivered business operations software.",
                        "productKind": "digital_platform",
                        "sourceIds": [source_id],
                    },
                    "operations": {
                        "sampledAt": "2026-07-23T12:05:00Z",
                        "rootStatus": "2xx",
                        "finalUrl": "https://new-product.example/",
                        "httpsObserved": True,
                        "certificateObservation": "valid_at_sample",
                        "supportOrContactPath": "",
                        "sourceIds": [source_id],
                    },
                    "claimConcordance": [
                        {
                            "claimType": "name",
                            "proposedClaim": "The product is named Example Product.",
                            "supported": True,
                            "sourceIds": [source_id],
                            "note": "",
                        }
                    ],
                    "privacyAndTerms": {
                        "privacyPolicy": "present",
                        "terms": "present",
                        "publicContactIdentity": "present",
                        "sourceIds": [source_id],
                    },
                    "passivePublicPosture": {
                        "headersObserved": ["Strict-Transport-Security"],
                        "mixedContentObserved": "no",
                        "publicExposureClues": [],
                        "landingPageTrackers": [],
                        "sourceIds": [source_id],
                    },
                    "publicUxSmoke": {
                        "desktopRender": "observed",
                        "mobileRender": "observed",
                        "obviousBrokenNavigation": "no",
                        "notes": "Public landing page rendered.",
                        "sourceIds": [source_id],
                    },
                },
                "findings": [],
                "recommendedOutcome": "ready_for_human_review",
                "holdCodes": [],
                "proposedPublicSafeSummary": "Caribbean business operations software.",
                "outstandingQuestions": [],
                "limitations": ["Public credential-free observation only."],
            }
        ],
        "synthesis": {
            "readyForHumanReviewLeadKeys": ["example-product"],
            "holdLeadKeys": [],
            "coverageGaps": [],
            "humanDecisionsRequired": ["Decide whether to list the product."],
        },
    }
    return results


def sample_catalog() -> dict:
    return {
        "schemaVersion": 2,
        "products": [
            {
                "id": "existing-app",
                "slug": "existing-app",
                "name": "Existing App",
                "websiteUrl": "https://existing.example",
                "productKind": "saas",
                "visibility": "listed",
                "description": "Existing public product.",
            }
        ],
    }


def eligible_candidate(name: str = "New Product", website_url: str = "https://new-product.example") -> dict:
    return {
        "name": name,
        "websiteUrl": website_url,
        "companyName": "New Product Ltd.",
        "tagline": "Regional operations software.",
        "description": "A digital platform for Caribbean operations teams.",
        "country": "Bahamas",
        "countries": ["Bahamas", "Caribbean"],
        "category": "Productivity",
        "industry": "Business operations",
        "tags": ["Operations", "Caribbean"],
        "productKind": "digital_platform",
        "caribbeanConnection": "Built for Caribbean business operations.",
        "recommendation": "ready_for_human_review",
        "confidence": 0.91,
        "caribbeanEvidenceTier": "A",
        "sources": [
            {
                "sourceId": "official-1",
                "url": "https://new-product.example/about",
                "sourceClass": "official_site",
                "summary": "Official product description.",
            },
            {
                "sourceId": "press-1",
                "url": "https://regional-news.example/new-product",
                "sourceClass": "reputable_press",
                "summary": "Regional corroboration.",
            },
        ],
        "evidence": {
            "A": {"url": "https://new-product.example/about", "summary": "Official product description."},
            "B": {"url": "https://regional-news.example/new-product", "summary": "Regional corroboration."},
        },
    }


class ReviewLedgerCheck(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temporary.name)
        self.private_root = self.workspace / "private" / "reviews"
        self.catalog = self.workspace / "products.json"
        self.active_run_id: str | None = None
        write_json(self.catalog, sample_catalog())
        self.run_command("init")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_command(self, command: str, *extra: str, expected: int = 0) -> dict:
        completed = subprocess.run(
            [
                sys.executable,
                str(LEDGER),
                command,
                *extra,
                "--root",
                str(self.private_root),
                "--catalog",
                str(self.catalog),
                "--allow-dirty-catalog",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, expected, msg=completed.stderr)
        return json.loads(completed.stdout) if completed.stdout else {}

    def ingest(self, candidates: list[dict], run_id: str = "run-test") -> dict:
        self.ensure_run(run_id)
        input_path = self.workspace / "input.json"
        normalised_candidates = []
        sources = []
        for candidate in candidates:
            normalised = copy.deepcopy(candidate)
            candidate_sources = normalised.pop("sources", [])
            if candidate_sources:
                normalised["sourceIds"] = [source["sourceId"] for source in candidate_sources]
                sources.extend(candidate_sources)
            normalised_candidates.append(normalised)
        provenance = sample_provenance()
        write_json(
            input_path,
            {
                "contractVersion": "1.0",
                "runId": run_id,
                "workerContractsValidated": True,
                "modelProvenance": provenance,
                "coverage": {"searchedSlices": ["Bahamas|English|fintech"]},
                "sourceFailures": ["No access to one public directory."],
                "sideEffectAttestation": safe_attestation(),
                "sources": sources,
                "workerResults": sample_worker_results(run_id, sources, provenance),
                "candidates": normalised_candidates,
            },
        )
        return self.run_command("ingest", str(input_path))

    def ensure_run(self, run_id: str) -> None:
        if self.active_run_id == run_id:
            return
        if self.active_run_id:
            self.complete_active_run()
        self.run_command("begin-run", "--run-id", run_id)
        self.active_run_id = run_id

    def complete_active_run(self) -> None:
        self.assertIsNotNone(self.active_run_id)
        self.run_command("queue", "--run-id", str(self.active_run_id))
        self.run_command("validate")
        self.run_command("finish-run", "--run-id", str(self.active_run_id))
        self.active_run_id = None

    def candidate_rows(self) -> list[sqlite3.Row]:
        connection = sqlite3.connect(self.private_root / "registry.sqlite3")
        connection.row_factory = sqlite3.Row
        try:
            return connection.execute("SELECT * FROM candidates ORDER BY candidate_id").fetchall()
        finally:
            connection.close()

    def test_catalog_and_private_duplicates_are_not_reused(self) -> None:
        catalog_duplicate = eligible_candidate("Renamed Existing", "https://www.existing.example/pricing?utm_source=test")
        first = self.ingest([catalog_duplicate])
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(first["duplicateCatalog"], 1)
        self.assertEqual(self.candidate_rows()[0]["state"], "duplicate_catalog")

        local_candidate = eligible_candidate()
        self.ingest([local_candidate])
        retry = self.ingest([copy.deepcopy(local_candidate)])
        self.assertEqual(retry["observations"], 0)
        second = self.ingest([copy.deepcopy(local_candidate)], run_id="run-recheck")
        self.assertEqual(second["inserted"], 0)
        self.assertEqual(second["duplicateCandidates"], 1)
        self.assertEqual(second["observations"], 1)
        self.assertEqual(len(self.candidate_rows()), 2)
        events = [
            json.loads(line)
            for line in (self.private_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        duplicate_observations = [event for event in events if event["event"] == "candidate_observed"]
        self.assertEqual(len(duplicate_observations), 1)
        self.assertEqual(duplicate_observations[0]["runId"], "run-recheck")
        packet_result = self.run_command("queue", "--run-id", "run-recheck")
        packet = json.loads(Path(packet_result["queueJson"]).read_text(encoding="utf-8"))
        self.assertEqual(packet["counts"]["duplicateCandidates"], 1)
        self.assertEqual(packet["candidates"][0]["state"], "duplicate_candidate")

    def test_public_app_store_id_prevents_rediscovery_after_domain_change(self) -> None:
        catalog = sample_catalog()
        catalog["products"][0]["aliases"] = ["Existing Mobile"]
        catalog["products"][0]["officialAppStoreIds"] = ["apple:111222333"]
        write_json(self.catalog, catalog)
        candidate = eligible_candidate(
            "Renamed Mobile",
            "https://renamed-mobile.example",
        )
        candidate["officialAppStoreIds"] = [
            "https://apps.apple.com/bs/app/renamed/id111222333"
        ]
        result = self.ingest([candidate], run_id="run-public-app-id")
        self.assertEqual(result["duplicateCatalog"], 1)
        row = self.candidate_rows()[0]
        self.assertEqual(row["state"], "duplicate_catalog")
        self.assertEqual(row["duplicate_kind"], "catalog_app_store_id")
        self.assertEqual(row["catalog_match_id"], "existing-app")
        inventory = self.run_command("inventory")
        self.assertEqual(inventory["public"][0]["aliases"], ["Existing Mobile"])
        self.assertEqual(
            inventory["public"][0]["officialAppStoreIds"],
            ["apple:111222333"],
        )

    def test_ineligible_candidate_stays_held(self) -> None:
        held = eligible_candidate("Held Product", "https://held-product.example")
        held["confidence"] = 0.79
        held["evidence"] = {"A": {"url": "https://held-product.example/about"}}
        result = self.ingest([held])
        self.assertEqual(result["holds"], 1)
        self.assertEqual(self.candidate_rows()[0]["state"], "hold")
        queue = self.run_command("queue", "--run-id", "run-test")
        self.assertTrue(Path(queue["queue"]).exists())
        packet = json.loads(Path(queue["queueJson"]).read_text(encoding="utf-8"))
        self.assertEqual(packet["runId"], "run-test")
        self.assertEqual(
            packet["modelProvenance"]["models"],
            ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"],
        )
        self.assertTrue(packet["workerContractsValidated"])
        self.assertEqual(packet["sourceFailures"], ["No access to one public directory."])
        self.assertFalse(packet["packetOperationAttestation"]["listedVisibilityWrites"])
        sync = self.run_command("sync-unlisted", "--run-id", "run-test")
        self.assertEqual(sync["added"], 0)
        self.assertEqual(len(json.loads(self.catalog.read_text())["products"]), 1)

    def test_eligible_projection_is_unlisted_and_has_no_private_fields(self) -> None:
        candidate = eligible_candidate()
        candidate.update(
            {
                "aliases": ["New Product App"],
                "officialAppStoreIds": ["apple:123456789"],
                "privateNotes": "Do not expose this.",
                "internalNotes": "Private reviewer note.",
                "email": "founder@example.test",
                "auditFindings": {"severity": "private"},
            }
        )
        self.ingest([candidate])
        sync = self.run_command("sync-unlisted", "--run-id", "run-test")
        self.assertEqual(sync["added"], 1)
        products = json.loads(self.catalog.read_text(encoding="utf-8"))["products"]
        projection = products[-1]
        self.assertEqual(projection["visibility"], "unlisted")
        self.assertEqual(projection["aliases"], ["New Product App"])
        self.assertEqual(projection["officialAppStoreIds"], ["apple:123456789"])
        self.assertNotIn("status", projection)
        for private_key in ["privateNotes", "internalNotes", "email", "auditFindings", "evidence", "confidence"]:
            self.assertNotIn(private_key, projection)
        self.assertEqual(projection["logoUrl"], None)
        self.assertEqual(projection["screenshotUrls"], [])
        self.assertEqual(projection["founderNames"], [])
        self.assertEqual(projection["publishedAt"], None)
        row = self.candidate_rows()[0]
        self.assertIsNone(row["human_decision_json"])
        self.assertEqual(json.loads(row["automated_review_json"])["runId"], "run-test")
        private_serialized = row["private_payload_json"]
        automated_serialized = row["automated_review_json"]
        self.assertNotIn("founder@example.test", private_serialized)
        self.assertNotIn("founder@example.test", automated_serialized)
        self.assertNotIn('"candidate"', automated_serialized)
        self.assertIn("redactedInputFields", automated_serialized)
        self.run_command("queue", "--run-id", "run-test")
        self.assertTrue(self.run_command("validate")["valid"])

    def test_tier_a_accepts_a_second_distinct_official_source(self) -> None:
        candidate = eligible_candidate("Tier A Product", "https://tier-a-product.example")
        candidate["sources"][1]["sourceId"] = "registry-1"
        candidate["sources"][1]["sourceClass"] = "official_registry"
        candidate["sources"][1]["url"] = "https://registry.example/tier-a-product"
        candidate["evidence"]["B"]["url"] = "https://registry.example/tier-a-product"
        self.ingest([candidate], run_id="run-tier-a")
        self.assertEqual(self.candidate_rows()[0]["state"], "ready_for_human_review")
        self.assertEqual(self.run_command("sync-unlisted", "--run-id", "run-tier-a")["added"], 1)

    def test_sync_is_idempotent_and_preserves_listed_records(self) -> None:
        original_listed = copy.deepcopy(sample_catalog()["products"][0])
        self.ingest([eligible_candidate()])
        first = self.run_command("sync-unlisted", "--run-id", "run-test")
        self.assertEqual(first["added"], 1)
        first_bytes = self.catalog.read_bytes()
        second = self.run_command("sync-unlisted", "--run-id", "run-test")
        self.assertEqual(second["added"], 0)
        self.assertEqual(self.catalog.read_bytes(), first_bytes)
        products = json.loads(first_bytes)["products"]
        self.assertEqual(products[0], original_listed)
        self.assertEqual(sum(product.get("visibility") == "listed" for product in products), 1)
        self.assertEqual(sum(product.get("visibility") == "unlisted" for product in products), 1)

        events = [
            json.loads(line)
            for line in (self.private_root / "events.jsonl").read_text(encoding="utf-8").splitlines()
            if line
        ]
        event_keys = [event["eventKey"] for event in events]
        self.assertEqual(len(event_keys), len(set(event_keys)))
        self.assertEqual(sum(event["event"] == "candidate_ingested" for event in events), 1)
        self.assertEqual(sum(event["event"] == "candidate_synced_unlisted" for event in events), 1)
        self.assertEqual(sum(event["event"] == "candidate_observed" for event in events), 0)

    def test_validate_rejects_legacy_status_and_unknown_product_kind(self) -> None:
        invalid = sample_catalog()
        invalid["products"][0].pop("visibility")
        invalid["products"][0]["status"] = "published"
        invalid["products"][0]["productKind"] = "unknown"
        invalid["products"][0]["privateReview"] = {"runId": "must-not-be-public"}
        invalid["products"][0]["modelProvenance"] = {"model": "internal"}
        invalid["products"][0]["tagline"] = "Contact founder@example.test"
        write_json(self.catalog, invalid)
        result = self.run_command("validate", expected=1)
        self.assertFalse(result["valid"])
        self.assertTrue(any("legacy status" in issue for issue in result["issues"]))
        self.assertTrue(any("invalid visibility" in issue for issue in result["issues"]))
        self.assertTrue(any("invalid productKind" in issue for issue in result["issues"]))
        self.assertTrue(any("private fields present" in issue for issue in result["issues"]))
        self.assertTrue(any("fields outside the public schema" in issue for issue in result["issues"]))
        self.assertTrue(any("contact details found" in issue for issue in result["issues"]))

    def test_incomplete_projection_is_held_without_blocking_valid_candidate(self) -> None:
        incomplete = eligible_candidate("Incomplete Product", "https://incomplete.example")
        incomplete.pop("category")
        incomplete["productKind"] = "unknown"
        valid = eligible_candidate("Valid Product", "https://valid.example")
        result = self.ingest([incomplete, valid])
        self.assertEqual(result["holds"], 1)
        states = {row["name"]: row["state"] for row in self.candidate_rows()}
        self.assertEqual(states["Incomplete Product"], "hold")
        self.assertEqual(states["Valid Product"], "ready_for_human_review")
        sync = self.run_command("sync-unlisted", "--run-id", "run-test")
        self.assertEqual(sync["added"], 1)
        self.assertEqual(sync["projectionHolds"], 0)

    def test_sync_defensively_holds_corrupt_payload_and_continues(self) -> None:
        first = eligible_candidate("First Product", "https://first.example")
        second = eligible_candidate("Second Product", "https://second.example")
        self.ingest([first, second])
        with sqlite3.connect(self.private_root / "registry.sqlite3") as connection:
            row = connection.execute(
                "SELECT candidate_id, public_payload_json FROM candidates WHERE name = 'First Product'"
            ).fetchone()
            payload = json.loads(row[1])
            payload.pop("category")
            connection.execute(
                "UPDATE candidates SET public_payload_json = ? WHERE candidate_id = ?",
                (json.dumps(payload), row[0]),
            )
        sync = self.run_command("sync-unlisted", "--run-id", "run-test")
        self.assertEqual(sync["added"], 1)
        self.assertEqual(sync["projectionHolds"], 1)
        states = {row["name"]: row["state"] for row in self.candidate_rows()}
        self.assertEqual(states["First Product"], "hold")
        self.assertEqual(states["Second Product"], "synced_unlisted")

    def test_sync_requires_clean_at_start_and_active_lock(self) -> None:
        self.ingest([eligible_candidate()])
        with sqlite3.connect(self.private_root / "registry.sqlite3") as connection:
            connection.execute(
                "UPDATE runs SET catalog_clean_at_start = 0 WHERE run_id = 'run-test'"
            )
        self.run_command("sync-unlisted", "--run-id", "run-test", expected=2)
        self.complete_active_run()
        self.run_command("sync-unlisted", "--run-id", "run-test", expected=2)

    def test_unresolved_source_reference_rejects_ingest_atomically(self) -> None:
        self.ensure_run("run-unresolved")
        candidate = eligible_candidate()
        candidate.pop("sources")
        candidate["sourceIds"] = ["missing-source"]
        input_path = self.workspace / "unresolved.json"
        provenance = sample_provenance()
        write_json(
            input_path,
            {
                "contractVersion": "1.0",
                "runId": "run-unresolved",
                "workerContractsValidated": True,
                "modelProvenance": provenance,
                "coverage": {},
                "sourceFailures": [],
                "sideEffectAttestation": safe_attestation(),
                "sources": [],
                "workerResults": sample_worker_results(
                    "run-unresolved",
                    [],
                    provenance,
                ),
                "candidates": [candidate],
            },
        )
        self.run_command("ingest", str(input_path), expected=2)
        self.assertEqual(self.candidate_rows(), [])

    def test_candidate_local_sources_cannot_bypass_normalized_source_matrix(self) -> None:
        self.ensure_run("run-local-source-bypass")
        candidate = eligible_candidate()
        provenance = sample_provenance()
        input_path = self.workspace / "local-source-bypass.json"
        write_json(
            input_path,
            {
                "contractVersion": "1.0",
                "runId": "run-local-source-bypass",
                "workerContractsValidated": True,
                "modelProvenance": provenance,
                "coverage": {},
                "sourceFailures": [],
                "sideEffectAttestation": safe_attestation(),
                "sources": [],
                "workerResults": sample_worker_results(
                    "run-local-source-bypass",
                    [],
                    provenance,
                ),
                "candidates": [candidate],
            },
        )
        self.run_command("ingest", str(input_path), expected=2)
        self.assertEqual(self.candidate_rows(), [])

    def test_evidence_urls_must_resolve_to_candidate_sources(self) -> None:
        candidate = eligible_candidate()
        candidate["evidence"]["B"]["url"] = "https://unrelated.example/profile"
        result = self.ingest([candidate])
        self.assertEqual(result["holds"], 1)
        row = self.candidate_rows()[0]
        self.assertEqual(row["state"], "hold")
        self.assertIn(
            "evidence B URL is not present in the resolved source set",
            json.loads(row["hold_reasons_json"]),
        )

    def test_empty_successful_run_still_writes_packet(self) -> None:
        self.ensure_run("run-empty")
        input_path = self.workspace / "empty.json"
        provenance = sample_provenance()
        write_json(
            input_path,
            {
                "contractVersion": "1.0",
                "runId": "run-empty",
                "workerContractsValidated": True,
                "modelProvenance": provenance,
                "coverage": {"searchedSlices": ["Bahamas|English|general"]},
                "sourceFailures": [],
                "sideEffectAttestation": safe_attestation(),
                "sources": [],
                "workerResults": sample_worker_results("run-empty", [], provenance),
                "candidates": [],
            },
        )
        result = self.run_command("ingest", str(input_path))
        self.assertEqual(result["inserted"], 0)
        packet_result = self.run_command("queue", "--run-id", "run-empty")
        packet = json.loads(Path(packet_result["queueJson"]).read_text(encoding="utf-8"))
        self.assertEqual(packet["candidates"], [])
        self.assertEqual(packet["coverage"]["searchedSlices"], ["Bahamas|English|general"])
        self.assertEqual(packet["sideEffectAttestation"], safe_attestation())

    def test_missing_or_non_false_attestation_rejects_ingest(self) -> None:
        self.ensure_run("run-attestation")
        provenance = sample_provenance()
        base = {
            "contractVersion": "1.0",
            "runId": "run-attestation",
            "workerContractsValidated": True,
            "modelProvenance": provenance,
            "coverage": {},
            "sourceFailures": [],
            "sources": [],
            "workerResults": sample_worker_results(
                "run-attestation",
                [],
                provenance,
            ),
            "candidates": [],
        }
        input_path = self.workspace / "attestation.json"
        write_json(input_path, base)
        self.run_command("ingest", str(input_path), expected=2)
        base["sideEffectAttestation"] = safe_attestation()
        base["sideEffectAttestation"]["contactsMade"] = True
        write_json(input_path, base)
        self.run_command("ingest", str(input_path), expected=2)
        base["sideEffectAttestation"] = safe_attestation()
        base["sideEffectAttestation"]["gitActions"] = True
        write_json(input_path, base)
        self.run_command("ingest", str(input_path), expected=2)

    def test_worker_contract_and_model_mappings_are_required(self) -> None:
        self.ensure_run("run-worker-contract")
        input_path = self.workspace / "worker-contract.json"
        provenance = sample_provenance()
        envelope = {
            "contractVersion": "1.0",
            "runId": "run-worker-contract",
            "modelProvenance": provenance,
            "coverage": {},
            "sourceFailures": [],
            "sideEffectAttestation": safe_attestation(),
            "sources": [],
            "workerResults": sample_worker_results(
                "run-worker-contract",
                [],
                provenance,
            ),
            "candidates": [],
        }
        write_json(input_path, envelope)
        self.run_command("ingest", str(input_path), expected=2)
        envelope["workerContractsValidated"] = True
        envelope["modelProvenance"]["workers"][0]["model"] = "gpt-5.6-sol"
        write_json(input_path, envelope)
        self.run_command("ingest", str(input_path), expected=2)
        envelope["modelProvenance"] = sample_provenance()
        envelope["workerResults"] = sample_worker_results(
            "run-worker-contract",
            [],
            envelope["modelProvenance"],
        )
        envelope["workerResults"][2]["sideEffectAttestation"]["contactsMade"] = True
        write_json(input_path, envelope)
        self.run_command("ingest", str(input_path), expected=2)
        envelope["workerResults"] = sample_worker_results(
            "run-worker-contract",
            [],
            envelope["modelProvenance"],
        )
        write_json(input_path, envelope)
        accepted = self.run_command("ingest", str(input_path))
        self.assertEqual(accepted["inserted"], 0)

    def test_nested_worker_role_payloads_are_strictly_validated(self) -> None:
        self.ensure_run("run-nested-contract")
        provenance = sample_provenance()
        sources = eligible_candidate()["sources"]
        base = {
            "contractVersion": "1.0",
            "runId": "run-nested-contract",
            "workerContractsValidated": True,
            "modelProvenance": provenance,
            "coverage": {"searchedSlices": ["Bahamas|English|business software"]},
            "sourceFailures": [],
            "sideEffectAttestation": safe_attestation(),
            "sources": sources,
            "workerResults": sample_populated_worker_results(
                "run-nested-contract",
                sources,
                provenance,
            ),
            "candidates": [],
        }
        input_path = self.workspace / "nested-contract.json"
        write_json(input_path, base)
        self.assertEqual(self.run_command("ingest", str(input_path))["inserted"], 0)

        mutations = {
            "scout query scalar": lambda payload: payload["workerResults"][0]["result"].update(
                {"queries": [42]}
            ),
            "scout invalid outcome": lambda payload: payload["workerResults"][0]["result"][
                "queries"
            ][0].update({"outcome": "listed"}),
            "scout invalid product kind": lambda payload: payload["workerResults"][0]["result"][
                "leads"
            ][0].update({"productKindHints": ["website"]}),
            "verifier missing canonical field": lambda payload: payload["workerResults"][1][
                "result"
            ]["entities"][0]["canonical"].pop("canonicalHost"),
            "verifier invalid resolution": lambda payload: payload["workerResults"][1]["result"][
                "entities"
            ][0].update({"resolution": "listed"}),
            "verifier ineligible resolution": lambda payload: payload["workerResults"][1]["result"][
                "entities"
            ][0].update({"resolution": "duplicate_known"}),
            "auditor unknown visibility": lambda payload: payload["workerResults"][2]["result"][
                "audits"
            ][0].update({"visibility": "listed"}),
            "auditor invalid outcome": lambda payload: payload["workerResults"][2]["result"][
                "audits"
            ][0].update({"recommendedOutcome": "listed"}),
            "auditor string boolean": lambda payload: payload["workerResults"][2]["result"][
                "audits"
            ][0]["observed"]["operations"].update({"httpsObserved": "true"}),
            "auditor malformed synthesis": lambda payload: payload["workerResults"][2]["result"].update(
                {"synthesis": {"readyForHumanReviewLeadKeys": "example-product"}}
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                malformed = copy.deepcopy(base)
                mutate(malformed)
                write_json(input_path, malformed)
                self.run_command("ingest", str(input_path), expected=2)
        self.assertEqual(self.candidate_rows(), [])

    def test_partial_worker_run_is_private_only(self) -> None:
        self.ensure_run("run-partial-worker")
        candidate = eligible_candidate(
            "Partial Worker Product",
            "https://partial-worker.example",
        )
        sources = candidate.pop("sources")
        candidate["sourceIds"] = [source["sourceId"] for source in sources]
        provenance = sample_provenance()
        provenance["workers"][2]["status"] = "partial"
        input_path = self.workspace / "partial-worker.json"
        write_json(
            input_path,
            {
                "contractVersion": "1.0",
                "runId": "run-partial-worker",
                "workerContractsValidated": True,
                "modelProvenance": provenance,
                "coverage": {"searchedSlices": ["Bahamas|English|general"]},
                "sourceFailures": ["Auditor reached the configured source cap."],
                "sideEffectAttestation": safe_attestation(),
                "sources": sources,
                "workerResults": sample_worker_results(
                    "run-partial-worker",
                    sources,
                    provenance,
                ),
                "candidates": [candidate],
            },
        )
        result = self.run_command("ingest", str(input_path))
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(self.candidate_rows()[0]["state"], "ready_for_human_review")
        self.run_command(
            "sync-unlisted",
            "--run-id",
            "run-partial-worker",
            expected=2,
        )
        self.assertEqual(
            json.loads(self.catalog.read_text(encoding="utf-8"))["products"],
            sample_catalog()["products"],
        )

    def test_public_contact_details_are_removed_and_candidate_is_held(self) -> None:
        candidate = eligible_candidate()
        candidate["tagline"] = "Email founder@example.test or call +1 (242) 555-0199."
        result = self.ingest([candidate])
        self.assertEqual(result["holds"], 1)
        row = self.candidate_rows()[0]
        self.assertEqual(row["state"], "hold")
        for field in ("public_payload_json", "private_payload_json", "automated_review_json"):
            self.assertNotIn("founder@example.test", row[field])
            self.assertNotIn("555-0199", row[field])
        public_payload = json.loads(row["public_payload_json"])
        self.assertNotIn("tagline", public_payload)
        self.assertIn(
            "public projection field tagline contained a contact detail and was removed",
            json.loads(row["hold_reasons_json"]),
        )

    def test_dirty_fixture_flag_does_not_bypass_real_private_storage_boundary(self) -> None:
        specification = importlib.util.spec_from_file_location("review_ledger", LEDGER)
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)
        with self.assertRaises(module.LedgerError):
            module.ensure_private_storage(
                ROOT / "data" / "forbidden-private-review-root",
                ROOT / "data" / "products.json",
                True,
            )
        with self.assertRaises(module.LedgerError):
            module.catalog_is_clean(ROOT / "data" / "products.json", True)

    def test_run_lock_is_exclusive_and_released_only_by_matching_run(self) -> None:
        self.ensure_run("run-lock-a")
        lock_payload = json.loads((self.private_root / "run.lock").read_text(encoding="utf-8"))
        self.assertEqual(lock_payload["runId"], "run-lock-a")
        self.run_command("begin-run", "--run-id", "run-lock-b", expected=2)
        self.run_command("finish-run", "--run-id", "run-lock-b", expected=2)
        self.assertTrue((self.private_root / "run.lock").exists())
        self.run_command("finish-run", "--run-id", "run-lock-a", expected=2)
        self.assertTrue((self.private_root / "run.lock").exists())
        self.ingest([], run_id="run-lock-a")
        self.run_command("queue", "--run-id", "run-lock-a")
        self.run_command("validate")
        finished = self.run_command("finish-run", "--run-id", "run-lock-a")
        self.assertTrue(finished["lockReleased"])
        self.active_run_id = None
        self.assertFalse((self.private_root / "run.lock").exists())

    def test_finish_requires_ingest_packet_and_successful_validation(self) -> None:
        self.ensure_run("run-lifecycle")
        lock_path = self.private_root / "run.lock"
        self.run_command("finish-run", "--run-id", "run-lifecycle", expected=2)
        self.assertTrue(lock_path.exists())

        self.ingest([], run_id="run-lifecycle")
        self.run_command("finish-run", "--run-id", "run-lifecycle", expected=2)
        self.assertTrue(lock_path.exists())

        self.run_command("queue", "--run-id", "run-lifecycle")
        self.run_command("finish-run", "--run-id", "run-lifecycle", expected=2)
        self.assertTrue(lock_path.exists())

        invalid = sample_catalog()
        invalid["products"][0]["visibility"] = "archived"
        write_json(self.catalog, invalid)
        self.run_command("validate", expected=1)
        self.run_command("finish-run", "--run-id", "run-lifecycle", expected=2)
        self.assertTrue(lock_path.exists())

        write_json(self.catalog, sample_catalog())
        self.run_command("validate")
        write_json(
            self.catalog,
            {
                "schemaVersion": 2,
                "products": [
                    {
                        **sample_catalog()["products"][0],
                        "visibility": "archived",
                    }
                ],
            },
        )
        self.run_command("finish-run", "--run-id", "run-lifecycle", expected=2)
        self.assertTrue(lock_path.exists())

        write_json(self.catalog, sample_catalog())
        self.run_command("validate")
        self.ingest([], run_id="run-lifecycle")
        self.run_command("finish-run", "--run-id", "run-lifecycle", expected=2)
        self.assertTrue(lock_path.exists())
        self.run_command("queue", "--run-id", "run-lifecycle")
        self.run_command("validate")
        finished = self.run_command("finish-run", "--run-id", "run-lifecycle")
        self.assertTrue(finished["lockReleased"])
        self.active_run_id = None
        self.assertFalse(lock_path.exists())

    def test_same_run_commands_are_process_serialized(self) -> None:
        self.ensure_run("run-serialized")
        with (self.private_root / "run.lock").open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_command("queue", "--run-id", "run-serialized", expected=2)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def test_stable_ledger_mutex_serializes_initialization_and_lifecycle_handoffs(self) -> None:
        ledger_lock = self.private_root / "ledger.lock"
        self.assertTrue(ledger_lock.exists())
        with ledger_lock.open("r+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_command("inventory", expected=2)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def test_exact_app_store_id_prevents_rediscovery_across_name_and_domain_changes(self) -> None:
        first = eligible_candidate("Island Mobile", "https://island-mobile.example")
        first["officialAppStoreIds"] = [
            "https://apps.apple.com/bs/app/island-mobile/id123456789"
        ]
        first["sources"][0].update(
            {
                "url": "https://apps.apple.com/bs/app/island-mobile/id123456789",
                "sourceClass": "official_app_store",
            }
        )
        first["evidence"]["A"]["url"] = first["sources"][0]["url"]
        self.ingest([first], run_id="run-app-first")
        second = eligible_candidate("Island Mobile Pro", "https://new-island-mobile.example")
        second["officialAppStoreIds"] = ["apple:123456789"]
        result = self.ingest([second], run_id="run-app-second")
        self.assertEqual(result["duplicateCandidates"], 1)
        self.assertEqual(len(self.candidate_rows()), 1)
        stored_ids = json.loads(self.candidate_rows()[0]["app_store_ids_json"])
        self.assertEqual(stored_ids, ["apple:123456789"])

    def test_same_name_with_different_domain_is_a_hold_not_an_automatic_duplicate(self) -> None:
        first = eligible_candidate("Shared Name", "https://shared-one.example")
        second = eligible_candidate("Shared Name", "https://shared-two.example")
        self.ingest([first], run_id="run-name-first")
        result = self.ingest([second], run_id="run-name-second")
        self.assertEqual(result["duplicateCandidates"], 0)
        self.assertEqual(result["inserted"], 1)
        self.assertEqual(len(self.candidate_rows()), 2)
        second_row = next(
            row for row in self.candidate_rows() if row["website_url"] == "https://shared-two.example"
        )
        self.assertEqual(second_row["state"], "hold")
        self.assertEqual(second_row["duplicate_kind"], "possible_private_name")

    def test_inventory_exposes_identity_keys_without_private_review_notes(self) -> None:
        candidate = eligible_candidate("Inventory Product", "https://inventory.example")
        candidate["aliases"] = ["Inventory App"]
        candidate["officialAppStoreIds"] = ["apple:987654321"]
        self.ingest([candidate], run_id="run-inventory")
        result = self.run_command("inventory")
        self.assertEqual(result["counts"], {"public": 1, "private": 1})
        self.assertEqual(result["public"][0]["id"], "existing-app")
        self.assertEqual(result["private"][0]["aliases"], ["Inventory App"])
        self.assertEqual(
            result["private"][0]["officialAppStoreIds"],
            ["apple:987654321"],
        )
        self.assertNotIn("automatedReview", result["private"][0])
        self.assertNotIn("humanDecision", result["private"][0])


if __name__ == "__main__":
    unittest.main()
