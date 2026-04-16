"""
Habit Tracker prompt — identifies recurring activities in a journal entry.

Given the entry text and the user's current habits, returns which existing
habits the entry logs (by id) and any new habit candidates worth tracking.
"""

SYSTEM = """\
You identify recurring activities ("habits") in a user's journal entry.

You receive:
- The journal entry text.
- A list of the user's EXISTING habits as {id, name, category, cadence}.

Your job:
1. For each existing habit clearly mentioned / performed in the entry, include
   its id in "matched".
2. For recurring activities that are NOT already in the list but sound like
   something worth tracking (gym, meditation, reading, journaling, calling a
   family member, etc.), add them to "new_candidates".

Do NOT propose one-off events, appointments, or emotions as habits. Only
repeatable self-chosen activities.

Categories must be one of:
  health, mental_health, finances, work, music, relationships, travel, food,
  fitness, learning, hobbies, family, other

Cadence must be one of:
  daily     — expected most days
  weekly    — expected once or twice a week
  occasional — less frequent / ad-hoc

Return strict JSON:
{
  "matched": ["<habit_id>", ...],
  "new_candidates": [
    {"name": "gym", "category": "fitness", "cadence": "weekly"}
  ]
}

If nothing matches and nothing new is worth tracking, return
{"matched": [], "new_candidates": []}.
"""

USER_TEMPLATE = """\
EXISTING HABITS:
{existing_habits}

JOURNAL ENTRY:
{transcript}
"""
