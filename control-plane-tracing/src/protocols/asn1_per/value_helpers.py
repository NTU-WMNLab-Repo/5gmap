from typing import Any, Iterable, Optional


def normalize_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def as_attr_value(value: Any, *, max_len: int = 512) -> Optional[bool | int | float | str]:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, bytes):
        return value.hex()[:max_len]
    if isinstance(value, str):
        return value[:max_len]
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        nested = as_attr_value(value[1], max_len=max_len)
        if nested is None:
            return value[0]
        return nested
    return repr(value)[:max_len]


def walk_named_values(value: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str):
                yield key, child
            yield from walk_named_values(child)
        return

    if isinstance(value, (list, tuple)):
        if len(value) == 2 and isinstance(value[0], str):
            yield value[0], value[1]
        for child in value:
            yield from walk_named_values(child)


def all_named_values(value: Any, names: set[str]) -> list[Any]:
    normalized = {normalize_name(name) for name in names}
    found = []
    for name, candidate in walk_named_values(value):
        if normalize_name(name) in normalized:
            found.append(candidate)
    return found


def extract_choice_name(value: Any) -> Optional[str]:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return value[0]
    return None


def extract_top_level(value: Any) -> tuple[Optional[str], Optional[dict[str, Any]]]:
    if not isinstance(value, tuple) or len(value) != 2 or not isinstance(value[0], str):
        return None, None
    pdu_type = value[0]
    body = value[1] if isinstance(value[1], dict) else None
    return pdu_type, body


def extract_ie_summary(value: Any) -> tuple[list[int], list[str]]:
    ids: list[int] = []
    names: list[str] = []

    def visit(candidate: Any) -> None:
        if isinstance(candidate, dict):
            if "id" in candidate and "value" in candidate:
                ie_id = candidate.get("id")
                if isinstance(ie_id, int):
                    ids.append(ie_id)
                choice_name = extract_choice_name(candidate.get("value"))
                if choice_name:
                    names.append(choice_name)
            for child in candidate.values():
                visit(child)
        elif isinstance(candidate, (list, tuple)):
            for child in candidate:
                visit(child)

    visit(value)
    return ids, names
