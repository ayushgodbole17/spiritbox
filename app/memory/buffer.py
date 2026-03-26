"""
Short-term conversation buffer — sliding window over recent turns.

Simple pure-Python implementation (no langchain.memory dependency).
Keeps the last k human+AI turn pairs in memory, keyed by session_id.
"""
import logging
from collections import deque
from functools import lru_cache
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_K = 10


@dataclass
class ConversationTurn:
    human: str
    ai: str


class ConversationBufferWindowMemory:
    """Sliding window conversation buffer — keeps last k turns."""

    def __init__(self, k: int = _DEFAULT_WINDOW_K):
        self.k = k
        self._turns: deque[ConversationTurn] = deque(maxlen=k)

    def save_context(self, human_input: dict, ai_output: dict) -> None:
        self._turns.append(ConversationTurn(
            human=human_input.get("input", ""),
            ai=ai_output.get("output", ""),
        ))

    @property
    def messages(self) -> list[dict]:
        """Return turns as a flat list of {role, content} dicts."""
        out = []
        for turn in self._turns:
            out.append({"role": "user", "content": turn.human})
            out.append({"role": "assistant", "content": turn.ai})
        return out

    def clear(self) -> None:
        self._turns.clear()


@lru_cache(maxsize=256)
def get_buffer(session_id: str, k: int = _DEFAULT_WINDOW_K) -> ConversationBufferWindowMemory:
    """
    Return (or create) a ConversationBufferWindowMemory for the given session.
    LRU-cached by session_id so the same buffer is reused across requests.
    """
    logger.debug(f"Creating/retrieving conversation buffer for session={session_id}")
    return ConversationBufferWindowMemory(k=k)


def add_turn(session_id: str, human_message: str, ai_message: str) -> None:
    buffer = get_buffer(session_id)
    buffer.save_context({"input": human_message}, {"output": ai_message})
    logger.debug(f"Saved turn to buffer for session={session_id}")


def get_history(session_id: str) -> list[dict]:
    return get_buffer(session_id).messages


def clear_buffer(session_id: str) -> None:
    get_buffer(session_id).clear()
    logger.debug(f"Cleared buffer for session={session_id}")
