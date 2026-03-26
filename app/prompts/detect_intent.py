"""
Prompt templates for the Intent Detector agent.

Detects actionable intents that should trigger scheduler jobs or tasks:
  - reminder: set a reminder for an event
  - task:     add a to-do item
  - note:     save a reference for later lookup
"""

DETECT_INTENT_PROMPT = """\
You are an intent detector for a personal journal AI called Spiritbox.

Given a journal entry, identify any actionable intents that the AI should act on.
Return a JSON array of intent objects. Each object must have:

{{
  "type": "reminder" | "task" | "note",
  "description": "<short description of the action>",
  "datetime": "<date/time string if applicable, else null>",
  "priority": "high" | "medium" | "low"
}}

Rules:
  - Only extract intents that are clearly implied by the text.
  - Do NOT invent tasks not mentioned.
  - For "reminder" type, the datetime field is required.
  - Return an empty array ([]) if no intents are found.

Examples:
  Input: "I have a dentist appointment tomorrow at 10am."
  Output:
  [
    {{
      "type": "reminder",
      "description": "Dentist appointment",
      "datetime": "tomorrow at 10am",
      "priority": "high"
    }}
  ]

  Input: "Had a great day. Nothing specific to do."
  Output: []

Journal entry:
{text}

Respond with ONLY valid JSON. No explanation.
"""

# System / user split variants for the Phase 2 chat completion API
SYSTEM = """\
You are an intent detector for a personal journal AI called Spiritbox.

Given extracted entities from a journal entry, determine which events should trigger
reminder emails for the user.

Return ONLY a valid JSON object with a single key "reminders" containing an array:
{
  "reminders": [
    {
      "event_description": "<short description of the event>",
      "event_time": "<ISO8601 datetime string>",
      "reminder_time": "<ISO8601 datetime string — exactly 1 hour before event_time>",
      "channel": "email"
    }
  ]
}

Rules:
  - Only include events that have a clear, resolvable datetime (not vague expressions like "someday").
  - reminder_time must be exactly 1 hour before event_time.
  - All datetimes must be ISO8601 format with timezone offset (e.g. 2024-03-25T10:00:00+05:30).
  - If no schedulable events are found, return {"reminders": []}.
  - Do NOT invent events not present in the entities.

Respond with ONLY valid JSON. No explanation.
"""

USER_TEMPLATE = (
    "Today's date and time: {current_datetime}\n"
    "User timezone: {timezone}\n"
    "Extracted entities: {entities_json}\n\n"
    "Determine which events need reminders."
)
