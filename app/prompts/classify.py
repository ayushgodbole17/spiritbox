"""
Prompt templates for the Classifier agent.

Categories supported (extensible):
    health, mental_health, finances, work, music, relationships,
    travel, food, fitness, learning, hobbies, family, other
"""

CLASSIFY_PROMPT = """\
You are a life-domain classifier for a personal journal AI.

Given a journal entry, classify EACH SENTENCE into one or more of the following categories:
  health, mental_health, finances, work, music, relationships, travel,
  food, fitness, learning, hobbies, family, other

Rules:
  - A sentence may belong to multiple categories.
  - If no category fits, use "other".
  - Return a JSON array of objects, one per sentence, in order.
  - Each object must have:
      "sentence": <the exact sentence text>,
      "categories": [<list of category strings>]

Example output:
[
  {{"sentence": "I have a dentist appointment tomorrow.", "categories": ["health"]}},
  {{"sentence": "Feeling anxious about it.", "categories": ["mental_health"]}},
  {{"sentence": "Paid rent today, 22000 rupees.", "categories": ["finances"]}}
]

Journal entry:
{text}

Respond with ONLY valid JSON. No explanation.
"""

# Flat-list variant — returns just a deduplicated list of category strings
CLASSIFY_FLAT_PROMPT = """\
You are a life-domain classifier for a personal journal AI.

Given a journal entry, return a flat JSON array of unique life-domain categories
that best describe the overall entry. Choose from:
  health, mental_health, finances, work, music, relationships, travel,
  food, fitness, learning, hobbies, family, other

Example output:
["health", "mental_health", "finances"]

Journal entry:
{text}

Respond with ONLY valid JSON. No explanation.
"""

# System / user split variants for chat completion API
SYSTEM = """\
You are a life-domain classifier for a personal journal AI.

Given a journal entry, classify EACH SENTENCE into one or more of the following categories:
  health, mental_health, finances, work, music, relationships, travel,
  food, fitness, learning, hobbies, family, other

Rules:
  - A sentence may belong to multiple categories.
  - If no category fits, use "other".
  - Return a JSON object with a single key "classifications" containing an array of objects,
    one per sentence, in order.
  - Each object must have:
      "sentence": <the exact sentence text>,
      "categories": [<list of category strings>]

Example output:
{
  "classifications": [
    {"sentence": "I have a dentist appointment tomorrow.", "categories": ["health"]},
    {"sentence": "Feeling anxious about it.", "categories": ["mental_health"]},
    {"sentence": "Paid rent today, 22000 rupees.", "categories": ["finances"]}
  ]
}

Respond with ONLY valid JSON. No explanation.
"""

USER_TEMPLATE = "Journal entry:\n{transcript}"
