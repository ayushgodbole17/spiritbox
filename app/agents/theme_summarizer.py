"""
Weekly Theme Summarizer

Clusters the last 7 days of journal entries per user into 3-5 themes and
stores the result in `theme_rollups`. Invoked weekly by Cloud Scheduler
via POST /internal/rollup/weekly.

Clustering uses a simple greedy cosine-similarity grouping over the
existing entry embeddings (pgvector). LLM (Tier 1, gpt-4o-mini) writes a
short label + summary per cluster.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from langfuse import observe
from sqlalchemy import text

from app.db.session import get_session
from app.llm.router import chat_completion, TIER_1

logger = logging.getLogger(__name__)

_COS_THRESHOLD = 0.72   # greedy cluster cohesion cutoff
_MIN_CLUSTER_SIZE = 2
_MAX_CLUSTERS = 5


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _greedy_cluster(entries: list[dict]) -> list[list[dict]]:
    """Greedy cosine clustering — seeds a new cluster when nothing nearby."""
    clusters: list[dict] = []  # [{centroid, members}]
    for entry in entries:
        emb = entry["embedding"]
        best_idx, best_sim = -1, -1.0
        for i, cl in enumerate(clusters):
            sim = _cosine(emb, cl["centroid"])
            if sim > best_sim:
                best_sim, best_idx = sim, i
        if best_idx >= 0 and best_sim >= _COS_THRESHOLD:
            cl = clusters[best_idx]
            n = len(cl["members"])
            cl["centroid"] = [(c * n + e) / (n + 1) for c, e in zip(cl["centroid"], emb)]
            cl["members"].append(entry)
        else:
            clusters.append({"centroid": list(emb), "members": [entry]})

    clusters.sort(key=lambda c: len(c["members"]), reverse=True)
    kept = [c["members"] for c in clusters if len(c["members"]) >= _MIN_CLUSTER_SIZE]
    if not kept and clusters:
        # No multi-entry cluster formed — keep the single biggest so the
        # rollup isn't empty on sparse weeks.
        kept = [clusters[0]["members"]]
    return kept[:_MAX_CLUSTERS]


async def _label_cluster(members: list[dict]) -> dict:
    """Ask the LLM for a short label + 2-3 sentence summary for the cluster."""
    snippets = "\n\n".join(
        f"- ({m['entry_date']}): {(m.get('summary') or m.get('raw_text') or '')[:400]}"
        for m in members
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You synthesize recurring themes from a user's journal entries. "
                "Given several entries that cluster together, produce a JSON object with "
                "'label' (2-4 words, title case) and 'summary' (2-3 sentences capturing "
                "what links these entries). Respond with JSON only, no prose."
            ),
        },
        {
            "role": "user",
            "content": f"Entries:\n{snippets}\n\nRespond with JSON: {{\"label\": \"...\", \"summary\": \"...\"}}",
        },
    ]
    try:
        response, _ = await chat_completion(
            tier=TIER_1,
            messages=messages,
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        raw = (response.choices[0].message.content or "").strip()
        parsed = json.loads(raw)
        label = str(parsed.get("label") or "Theme").strip()[:60]
        summary = str(parsed.get("summary") or "").strip()
    except Exception as exc:
        logger.warning(f"[theme_summarizer] cluster labeling failed: {exc!r}")
        label, summary = "Theme", ""

    return {
        "label":      label,
        "summary":    summary,
        "entry_ids":  [m["entry_id"] for m in members],
        "entry_count": len(members),
    }


async def _fetch_recent_embeddings(user_id: str, since: datetime) -> list[dict]:
    """Pull entry embeddings for the window as list-of-floats dicts."""
    async with get_session() as session:
        rows = await session.execute(
            text("""
                SELECT entry_id::text, raw_text, summary, entry_date,
                       embedding::text AS emb_text
                FROM entry_embeddings
                WHERE user_id = :user_id
                  AND entry_date >= :since
                  AND embedding IS NOT NULL
                ORDER BY entry_date DESC
            """),
            {"user_id": user_id, "since": since},
        )
        out: list[dict] = []
        for row in rows.mappings():
            # pgvector's ::text form is "[0.1,0.2,...]"
            raw_emb = row["emb_text"] or ""
            try:
                vec = [float(x) for x in raw_emb.strip("[]").split(",") if x]
            except ValueError:
                continue
            if not vec:
                continue
            out.append({
                "entry_id":   row["entry_id"],
                "raw_text":   row["raw_text"] or "",
                "summary":    row["summary"] or "",
                "entry_date": row["entry_date"].isoformat() if row["entry_date"] else "",
                "embedding":  vec,
            })
        return out


@observe()
async def run_weekly_rollup(user_id: str) -> dict:
    """
    Compute themes over the last 7 days for one user. Inserts a row in
    `theme_rollups` and returns the serialized result.
    """
    now = datetime.now(timezone.utc)
    week_start = now - timedelta(days=7)

    entries = await _fetch_recent_embeddings(user_id, since=week_start)
    if not entries:
        logger.info(f"[theme_summarizer] no entries for user={user_id} this week; skipping")
        return {"user_id": user_id, "themes": [], "entry_count": 0}

    clusters = _greedy_cluster(entries)
    themes = [await _label_cluster(members) for members in clusters]

    rollup_id = uuid.uuid4()
    async with get_session() as session:
        await session.execute(
            text("""
                INSERT INTO theme_rollups (id, user_id, week_start, themes, entry_count, created_at)
                VALUES (:id, :user_id, :week_start, CAST(:themes AS JSONB), :entry_count, :created_at)
            """),
            {
                "id":         rollup_id,
                "user_id":    user_id,
                "week_start": week_start,
                "themes":     json.dumps(themes),
                "entry_count": len(entries),
                "created_at": now,
            },
        )
        await session.commit()

    logger.info(
        f"[theme_summarizer] user={user_id} rolled up {len(entries)} entries "
        f"into {len(themes)} themes"
    )
    return {
        "rollup_id":   str(rollup_id),
        "user_id":     user_id,
        "week_start":  week_start.isoformat(),
        "themes":      themes,
        "entry_count": len(entries),
    }


async def run_weekly_rollup_for_all_users() -> list[dict]:
    """Run the rollup for every user that has at least one recent entry."""
    async with get_session() as session:
        rows = await session.execute(
            text("""
                SELECT DISTINCT user_id FROM entry_embeddings
                WHERE entry_date >= NOW() - INTERVAL '7 days'
            """)
        )
        user_ids = [row[0] for row in rows.all() if row[0]]

    results = []
    for uid in user_ids:
        try:
            results.append(await run_weekly_rollup(uid))
        except Exception as exc:
            logger.error(f"[theme_summarizer] rollup failed for user={uid}: {exc!r}", exc_info=True)
    return results
