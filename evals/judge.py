"""
LLM-as-Judge — online eval scoring for Spiritbox.

Scores a batch of (entry, predicted_categories) pairs using GPT-4o as a judge.
The judge evaluates category relevance on a 0-1 scale.

Usage (standalone):
    python evals/judge.py --sample 5

Usage (from run_evals.py):
    from evals.judge import score_batch
    judge_score = await score_batch(per_entry_results)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

_JUDGE_SYSTEM = """\
You are an expert at evaluating the quality of life-domain categorization for personal journal entries.

For each entry you will be given:
- The raw journal text
- The predicted categories (e.g. "fitness", "health", "work")

Your task: rate how well the predicted categories capture the content of the entry.

Score 1.0  — all relevant life domains are captured, no irrelevant categories
Score 0.75 — most domains captured, minor omissions or one irrelevant category
Score 0.5  — partially correct, key domains missing or several irrelevant categories
Score 0.25 — mostly wrong, few correct categories
Score 0.0  — completely wrong

Return ONLY valid JSON: {"score": <float 0.0-1.0>, "reasoning": "<one sentence>"}
"""

_JUDGE_USER = """\
Journal entry:
{text}

Predicted categories: {categories}

Rate the category quality.
"""


async def score_entry(text: str, categories: list[str], client) -> tuple[float, str]:
    """Score a single entry using GPT-4o as judge. Returns (score, reasoning)."""
    from openai import AsyncOpenAI
    prompt = _JUDGE_USER.format(
        text=text[:500],  # cap at 500 chars to save tokens
        categories=", ".join(categories) if categories else "(none)",
    )
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",  # cheaper model is fine for judging
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0,
        )
        raw = response.choices[0].message.content or "{}"
        parsed = json.loads(raw)
        score = float(parsed.get("score", 0.0))
        reasoning = str(parsed.get("reasoning", ""))
        return max(0.0, min(1.0, score)), reasoning
    except Exception as exc:
        logger.warning(f"[judge] scoring failed: {exc}")
        return 0.0, f"error: {exc}"


async def score_batch(
    per_entry: list[dict],
    sample_size: int | None = None,
) -> dict:
    """
    Score a batch of eval results using LLM-as-judge.

    Args:
        per_entry:   List of dicts with keys: id, predicted_categories.
                     Optionally include 'text' key; if absent, categories are judged alone.
        sample_size: If set, only judge this many randomly-sampled entries (saves cost).

    Returns:
        {
            "mean_judge_score": float,
            "judged_count": int,
            "per_entry": [{"id": str, "score": float, "reasoning": str}, ...]
        }
    """
    from app.config import settings
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    entries = per_entry
    if sample_size and sample_size < len(entries):
        import random
        entries = random.sample(entries, sample_size)

    scores = []
    judged = []
    for item in entries:
        text = item.get("text", item.get("id", ""))
        cats = item.get("predicted_categories", [])
        score, reasoning = await score_entry(text, cats, client)
        scores.append(score)
        judged.append({"id": item["id"], "score": round(score, 3), "reasoning": reasoning})

    mean = sum(scores) / len(scores) if scores else 0.0
    return {
        "mean_judge_score": round(mean, 4),
        "judged_count": len(judged),
        "per_entry": judged,
    }


async def _main(sample: int):
    results_path = Path(__file__).parent / "results_latest.json"
    if not results_path.exists():
        print("No results_latest.json found. Run run_evals.py first.")
        sys.exit(1)

    with open(results_path) as f:
        results = json.load(f)

    print(f"Running LLM-as-judge on {sample} sampled entries...")
    judge_results = await score_batch(results["per_entry"], sample_size=sample)

    print(f"\n  Mean judge score: {judge_results['mean_judge_score']:.4f}  (n={judge_results['judged_count']})")
    for item in judge_results["per_entry"]:
        print(f"  [{item['id']}] {item['score']:.2f} — {item['reasoning']}")

    # Merge into results file
    results["judge"] = judge_results
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Judge scores merged into {results_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LLM-as-judge eval scorer")
    parser.add_argument("--sample", type=int, default=5, help="Number of entries to judge (default: 5)")
    args = parser.parse_args()
    asyncio.run(_main(args.sample))
