"""
Eval harness — Phase 4.

Runs the classifier and entity extractor against the golden dataset and
computes:
  - classifier_precision: fraction of predicted categories that appear in
                          the expected set (averaged across all entries)
  - entity_f1:            micro-averaged F1 across all entity types
                          (people, places, amounts, events)

Usage:
    python evals/run_evals.py

Outputs a JSON results file at evals/results_latest.json and prints a
human-readable summary.
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.WARNING)


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _precision(predicted: list[str], expected: list[str]) -> float:
    if not predicted:
        return 1.0  # nothing predicted, nothing wrong
    hits = sum(1 for p in predicted if p in expected)
    return hits / len(predicted)


def _f1(predicted: list[str], expected: list[str]) -> tuple[float, float, float]:
    """Returns (precision, recall, f1)."""
    pred_set = set(str(x).lower() for x in predicted)
    exp_set  = set(str(x).lower() for x in expected)
    if not pred_set and not exp_set:
        return 1.0, 1.0, 1.0
    if not pred_set:
        return 0.0, 0.0, 0.0
    if not exp_set:
        return 0.0, 1.0, 0.0
    tp = len(pred_set & exp_set)
    p  = tp / len(pred_set)
    r  = tp / len(exp_set)
    f1 = (2 * p * r / (p + r)) if (p + r) > 0 else 0.0
    return p, r, f1


# ---------------------------------------------------------------------------
# Main eval loop
# ---------------------------------------------------------------------------

async def run():
    from app.agents.classifier     import classify_sentences
    from app.agents.entity_extractor import extract_entities
    from app.agents.graph import EntryState

    dataset_path = Path(__file__).parent / "golden_dataset.json"
    thresholds_path = Path(__file__).parent / "thresholds.json"

    with open(dataset_path) as f:
        dataset = json.load(f)
    with open(thresholds_path) as f:
        thresholds = json.load(f)

    classifier_precisions = []
    entity_f1s = []
    per_entry = []
    prompt_versions_seen: dict[str, set] = {}  # agent -> set of versions seen

    total = len(dataset)
    for i, item in enumerate(dataset, 1):
        print(f"  [{i}/{total}] {item['id']}...", end=" ", flush=True)

        state: EntryState = {
            "raw_text":        item["text"],
            "entities":        {},
            "categories":      [],
            "events":          [],
            "summary":         "",
            "entry_id":        item["id"],
            "model_used":      {},
            "cache_hits":      {},
            "prompt_versions": {},
        }

        # --- Classifier ---
        cls_result  = await classify_sentences(state)
        predicted_cats: list[str] = []
        for row in cls_result["categories"]:
            predicted_cats.extend(row.get("categories", []))
        predicted_cats = list(set(predicted_cats))  # dedupe

        expected_cats = item["expected_categories"]
        cls_prec = _precision(predicted_cats, expected_cats)
        classifier_precisions.append(cls_prec)

        # Track prompt versions used across the eval run
        for agent, version in cls_result.get("prompt_versions", {}).items():
            prompt_versions_seen.setdefault(agent, set()).add(version)

        # --- Entity extractor ---
        ent_result = await extract_entities(state)
        entities   = ent_result["entities"]
        expected_ents = item["expected_entities"]

        # Micro F1 across all entity types
        entity_type_f1s = []
        for etype in ("people", "places", "amounts", "events"):
            pred = [str(x) for x in entities.get(etype, [])]
            exp  = [str(x) for x in expected_ents.get(etype, [])]
            _, _, f1 = _f1(pred, exp)
            entity_type_f1s.append(f1)
        entry_ent_f1 = sum(entity_type_f1s) / len(entity_type_f1s)
        entity_f1s.append(entry_ent_f1)

        for agent, version in ent_result.get("prompt_versions", {}).items():
            prompt_versions_seen.setdefault(agent, set()).add(version)

        per_entry.append({
            "id":                item["id"],
            "classifier_precision": round(cls_prec, 3),
            "entity_f1":            round(entry_ent_f1, 3),
            "predicted_categories": predicted_cats,
            "expected_categories":  expected_cats,
        })

        status = "✓" if cls_prec >= thresholds["classifier_precision"] else "✗"
        print(f"cls={cls_prec:.2f} {status}  ent_f1={entry_ent_f1:.2f}")

    # --- Aggregate ---
    mean_cls_prec = sum(classifier_precisions) / len(classifier_precisions)
    mean_ent_f1   = sum(entity_f1s) / len(entity_f1s)

    all_passed = (
        mean_cls_prec >= thresholds["classifier_precision"]
        and mean_ent_f1 >= thresholds["entity_f1"]
    )
    run_at = datetime.now(timezone.utc).isoformat()

    # Summarise which prompt versions were active: collapse each agent's set to a string
    prompt_versions_summary = {
        agent: sorted(versions)[0] if len(versions) == 1 else ",".join(sorted(versions))
        for agent, versions in prompt_versions_seen.items()
    }
    # Single-string label for the eval run record (classifier version is most meaningful)
    dominant_version = prompt_versions_summary.get("classifier", "unknown")

    results = {
        "run_at":               run_at,
        "classifier_precision": round(mean_cls_prec, 4),
        "entity_f1":            round(mean_ent_f1, 4),
        "thresholds":           thresholds,
        "passed": {
            "classifier_precision": mean_cls_prec >= thresholds["classifier_precision"],
            "entity_f1":            mean_ent_f1   >= thresholds["entity_f1"],
        },
        "prompt_versions": prompt_versions_summary,
        "per_entry": per_entry,
    }

    # Write results file (for CI gate + admin dashboard file reader)
    out_path = Path(__file__).parent / "results_latest.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)

    # Persist to PostgreSQL eval_runs table (for admin analytics)
    try:
        from app.db.crud import save_eval_run
        await save_eval_run(
            classifier_precision=round(mean_cls_prec, 4),
            entity_f1=round(mean_ent_f1, 4),
            passed=all_passed,
            prompt_version=dominant_version,
        )
        print("  Eval run saved to PostgreSQL.")
    except Exception as exc:
        print(f"  Warning: could not save eval run to PostgreSQL: {exc}")

    # --- Print summary ---
    print("\n" + "─" * 50)
    print(f"  Classifier precision : {mean_cls_prec:.4f}  (threshold: {thresholds['classifier_precision']})  {'PASS ✓' if results['passed']['classifier_precision'] else 'FAIL ✗'}")
    print(f"  Entity F1            : {mean_ent_f1:.4f}  (threshold: {thresholds['entity_f1']})  {'PASS ✓' if results['passed']['entity_f1'] else 'FAIL ✗'}")
    print("─" * 50)
    print(f"  Results saved to: {out_path}")

    return results


if __name__ == "__main__":
    results = asyncio.run(run())
    sys.exit(0 if all(results["passed"].values()) else 1)
