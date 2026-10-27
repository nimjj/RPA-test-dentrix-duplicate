"""In-memory counters for the bot-detection heuristic, keyed by session id."""
import threading
import time
from collections import deque
from dataclasses import dataclass, field

_lock = threading.Lock()


@dataclass
class _State:
    requests: deque = field(default_factory=deque)
    last_form: float | None = None
    fast_streak: int = 0


_states: dict[str, _State] = {}


def reset() -> None:
    with _lock:
        _states.clear()


def forget(session_id: str) -> None:
    with _lock:
        _states.pop(session_id, None)


def record_request(session_id: str, max_per_min: int) -> bool:
    """True when the session made more than max_per_min requests in the last 60 s."""
    now = time.monotonic()
    with _lock:
        st = _states.setdefault(session_id, _State())
        st.requests.append(now)
        while st.requests and now - st.requests[0] > 60:
            st.requests.popleft()
        return len(st.requests) > max_per_min


def record_form(session_id: str, min_action_ms: int) -> bool:
    """True when more than 5 consecutive form submissions came less than
    min_action_ms apart: the 6th submission of a chain in which every one
    followed the previous by under min_action_ms."""
    now = time.monotonic()
    with _lock:
        st = _states.setdefault(session_id, _State())
        if st.last_form is not None and (now - st.last_form) * 1000 < min_action_ms:
            st.fast_streak += 1
        else:
            st.fast_streak = 0
        st.last_form = now
        return st.fast_streak >= 5  # 5 fast gaps = 6 submissions in the chain
