MAX_TURNS = 10
_store: dict[str, list[dict]] = {}


def get(channel_id: str) -> list[dict]:
    return _store.setdefault(channel_id, [])


def update(channel_id: str, history: list[dict]) -> None:
    if len(history) > MAX_TURNS * 2:
        history = history[-(MAX_TURNS * 2):]
    _store[channel_id] = history


def clear(channel_id: str) -> None:
    _store.pop(channel_id, None)
