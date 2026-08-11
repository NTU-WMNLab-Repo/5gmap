import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from correlator.online.lifecycle_trace import LifecycleTraceEmitter


F1AP = "f1ap"
NGAP = "ngap"
STATE_PENDING = "pending"
STATE_MATCHED = "matched"
STATE_CLOSING = "closing"
STATE_CLOSED = "closed"
STATE_FORCED_CLOSED = "forced_closed"

F1AP_INITIAL = "InitialULRRCMessageTransfer"
NGAP_INITIAL = "InitialUEMessage"
RELEASE_COMPLETE = "UEContextReleaseComplete"


@dataclass
class ProtocolLifecycle:
    protocol: str
    local_key: str
    local_correlation_id: str
    global_id: str
    first_seen_ns: int
    last_seen_ns: int
    release_complete: bool = False
    forced_closed: bool = False
    close_reason: Optional[str] = None
    ids: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    messages: Counter[str] = field(default_factory=Counter)
    first_message_ns: dict[str, int] = field(default_factory=dict)
    last_message_ns: dict[str, int] = field(default_factory=dict)

    def update(self, event: dict[str, Any]) -> None:
        event_time_ns = parse_int(event.get("event_time_unix_ns")) or time.time_ns()
        self.first_seen_ns = min(self.first_seen_ns, event_time_ns)
        self.last_seen_ns = max(self.last_seen_ns, event_time_ns)

        message_name = str(event.get("message_name") or "")
        if message_name:
            self.messages.update([message_name])
            self.first_message_ns.setdefault(message_name, event_time_ns)
            self.last_message_ns[message_name] = event_time_ns

        for key, value in normalize_ids(event).items():
            self.ids[key].add(value)

        if bool(event.get("release_complete")) or message_name == RELEASE_COMPLETE:
            self.release_complete = True


@dataclass
class GlobalLifecycle:
    ue_correlation_id: str
    trace_id: Optional[str]
    parent_span_id: Optional[str]
    state: str
    first_seen_ns: int
    last_seen_ns: int
    f1ap_keys: set[str] = field(default_factory=set)
    ngap_keys: set[str] = field(default_factory=set)
    close_reason: Optional[str] = None

    def linked_protocols(self) -> list[str]:
        protocols = []
        if self.f1ap_keys:
            protocols.append(F1AP)
        if self.ngap_keys:
            protocols.append(NGAP)
        return protocols


class OnlineCorrelatorState:
    """In-memory online F1AP/NGAP UE lifecycle correlator.

    The state only stores compact correlation metadata. Full decoded ASN.1
    values and payload bytes stay in the proxy worker that exports spans.
    """

    def __init__(
        self,
        initial_gap_ms: float = 1000.0,
        release_gap_ms: float = 5000.0,
        idle_timeout_ms: float = 60000.0,
        max_lifecycles: int = 10000,
        lifecycle_tracer: Optional["LifecycleTraceEmitter"] = None,
    ) -> None:
        self.initial_gap_ns = int(initial_gap_ms * 1_000_000)
        self.release_gap_ns = int(release_gap_ms * 1_000_000)
        self.idle_timeout_ns = int(idle_timeout_ms * 1_000_000)
        self.max_lifecycles = max_lifecycles
        self.lifecycle_tracer = lifecycle_tracer
        self._lock = threading.Lock()
        self._next_global = 1
        self._protocols: dict[str, dict[str, ProtocolLifecycle]] = {
            F1AP: {},
            NGAP: {},
        }
        self._active_keys: dict[str, dict[str, str]] = {
            F1AP: {},
            NGAP: {},
        }
        self._reuse_generations: dict[tuple[str, str], int] = defaultdict(int)
        self._globals: dict[str, GlobalLifecycle] = {}

    def handle_event(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            now_ns = parse_int(event.get("event_time_unix_ns")) or time.time_ns()
            self._expire_idle(now_ns)

            protocol = normalize_protocol(event.get("protocol"))
            if protocol is None:
                return self._none_response("unsupported_protocol")

            if not is_ue_event(event):
                return self._none_response("not_ue_related")

            lifecycle = self._upsert_protocol_lifecycle(protocol, event, now_ns)
            matched = self._try_match(lifecycle)
            global_lifecycle = self._globals[lifecycle.global_id]
            if matched is not None:
                global_lifecycle = matched

            self._update_global_from_protocol(global_lifecycle, lifecycle)
            self._refresh_global_state(global_lifecycle)
            self._sync_lifecycle_trace(global_lifecycle)
            self._evict_if_needed()
            return self._response(global_lifecycle, lifecycle)

    def resolve(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            now_ns = parse_int(event.get("event_time_unix_ns")) or time.time_ns()
            self._expire_idle(now_ns)

            protocol = normalize_protocol(event.get("protocol"))
            if protocol is None:
                return self._none_response("unsupported_protocol")

            local_key = self._active_key(protocol, self._base_local_key(protocol, event))
            lifecycle = self._protocols[protocol].get(local_key)
            if lifecycle is None:
                return self._none_response("unknown_lifecycle")

            global_lifecycle = self._globals.get(lifecycle.global_id)
            if global_lifecycle is None:
                return self._none_response("unknown_global_lifecycle")

            self._refresh_global_state(global_lifecycle)
            self._sync_lifecycle_trace(global_lifecycle)
            return self._response(global_lifecycle, lifecycle)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "globals": {
                    key: {
                        "ue_correlation_id": item.ue_correlation_id,
                        "trace_id": item.trace_id,
                        "parent_span_id": item.parent_span_id,
                        "state": item.state,
                        "first_seen_ns": item.first_seen_ns,
                        "last_seen_ns": item.last_seen_ns,
                        "f1ap_keys": sorted(item.f1ap_keys),
                        "ngap_keys": sorted(item.ngap_keys),
                        "linked_protocols": item.linked_protocols(),
                        "close_reason": item.close_reason,
                    }
                    for key, item in self._globals.items()
                },
                "f1ap": self._protocol_snapshot(F1AP),
                "ngap": self._protocol_snapshot(NGAP),
                "active_keys": {
                    F1AP: dict(self._active_keys[F1AP]),
                    NGAP: dict(self._active_keys[NGAP]),
                },
            }

    def _upsert_protocol_lifecycle(
        self,
        protocol: str,
        event: dict[str, Any],
        event_time_ns: int,
    ) -> ProtocolLifecycle:
        base_key = self._base_local_key(protocol, event)
        local_key = self._active_key(protocol, base_key)
        current = self._protocols[protocol].get(local_key)
        if current is not None and self._should_replace_lifecycle(current, event):
            global_lifecycle = self._globals.get(current.global_id)
            if global_lifecycle is not None and global_lifecycle.state != STATE_CLOSED:
                self._force_close_global(current.global_id, "id_reuse")
            local_key = self._next_reuse_key(protocol, base_key)
            current = None

        if current is None:
            global_lifecycle = self._create_global(event_time_ns)
            current = ProtocolLifecycle(
                protocol=protocol,
                local_key=local_key,
                local_correlation_id=str(event.get("local_correlation_id") or local_key),
                global_id=global_lifecycle.ue_correlation_id,
                first_seen_ns=event_time_ns,
                last_seen_ns=event_time_ns,
            )
            self._protocols[protocol][local_key] = current
            self._active_keys[protocol][base_key] = local_key
            self._link_protocol(global_lifecycle, current)

        current.update(event)
        return current

    def _try_match(self, lifecycle: ProtocolLifecycle) -> Optional[GlobalLifecycle]:
        other_protocol = NGAP if lifecycle.protocol == F1AP else F1AP
        candidates = list(self._protocols[other_protocol].values())
        scored = [
            (self._score_pair(lifecycle, candidate), candidate)
            for candidate in candidates
            if not candidate.forced_closed
        ]
        scored = [(score, candidate) for score, candidate in scored if score >= 70]
        if not scored:
            return None

        scored.sort(key=lambda item: item[0], reverse=True)
        other = scored[0][1]
        return self._merge_globals(lifecycle.global_id, other.global_id)

    def _score_pair(self, left: ProtocolLifecycle, right: ProtocolLifecycle) -> int:
        f1ap = left if left.protocol == F1AP else right
        ngap = left if left.protocol == NGAP else right
        score = 0

        if f1ap.ids.get("cu_id", set()).intersection(ngap.ids.get("ran_id", set())):
            score += 45

        f1_initial = f1ap.first_message_ns.get(F1AP_INITIAL)
        ngap_initial = ngap.first_message_ns.get(NGAP_INITIAL)
        if f1_initial is not None and ngap_initial is not None:
            gap = ngap_initial - f1_initial
            if 0 <= gap <= self.initial_gap_ns:
                score += 40
            elif -200_000_000 <= gap < 0:
                score += 10

        if lifecycles_overlap(f1ap, ngap):
            score += 10

        release_gap = release_gap_ns(f1ap, ngap)
        if release_gap is not None and release_gap <= self.release_gap_ns:
            score += 5

        return min(score, 100)

    def _merge_globals(self, left_id: str, right_id: str) -> GlobalLifecycle:
        left = self._globals[left_id]
        right = self._globals[right_id]
        if left is right:
            return left

        primary, secondary = sorted(
            [left, right],
            key=lambda item: (item.first_seen_ns, item.ue_correlation_id),
        )
        primary.f1ap_keys.update(secondary.f1ap_keys)
        primary.ngap_keys.update(secondary.ngap_keys)
        primary.first_seen_ns = min(primary.first_seen_ns, secondary.first_seen_ns)
        primary.last_seen_ns = max(primary.last_seen_ns, secondary.last_seen_ns)

        for key in primary.f1ap_keys:
            lifecycle = self._protocols[F1AP].get(key)
            if lifecycle is not None:
                lifecycle.global_id = primary.ue_correlation_id
        for key in primary.ngap_keys:
            lifecycle = self._protocols[NGAP].get(key)
            if lifecycle is not None:
                lifecycle.global_id = primary.ue_correlation_id

        self._globals.pop(secondary.ue_correlation_id, None)
        self._refresh_global_state(primary)
        return primary

    def _refresh_global_state(self, global_lifecycle: GlobalLifecycle) -> None:
        f1ap_released = self._all_protocol_keys_released(F1AP, global_lifecycle.f1ap_keys)
        ngap_released = self._all_protocol_keys_released(NGAP, global_lifecycle.ngap_keys)

        if global_lifecycle.state == STATE_FORCED_CLOSED:
            return

        if global_lifecycle.f1ap_keys and global_lifecycle.ngap_keys:
            if f1ap_released and ngap_released:
                global_lifecycle.state = STATE_CLOSED
                global_lifecycle.close_reason = "release_complete"
            elif f1ap_released or ngap_released:
                global_lifecycle.state = STATE_CLOSING
                global_lifecycle.close_reason = "partial_release"
            else:
                global_lifecycle.state = STATE_MATCHED
                global_lifecycle.close_reason = None
            return

        if f1ap_released or ngap_released:
            global_lifecycle.state = STATE_CLOSED
            global_lifecycle.close_reason = "single_protocol_release"
        else:
            global_lifecycle.state = STATE_PENDING
            global_lifecycle.close_reason = None

    def _all_protocol_keys_released(self, protocol: str, keys: set[str]) -> bool:
        if not keys:
            return False
        for key in keys:
            lifecycle = self._protocols[protocol].get(key)
            if lifecycle is None or not lifecycle.release_complete:
                return False
        return True

    def _update_global_from_protocol(
        self,
        global_lifecycle: GlobalLifecycle,
        lifecycle: ProtocolLifecycle,
    ) -> None:
        global_lifecycle.first_seen_ns = min(
            global_lifecycle.first_seen_ns,
            lifecycle.first_seen_ns,
        )
        global_lifecycle.last_seen_ns = max(
            global_lifecycle.last_seen_ns,
            lifecycle.last_seen_ns,
        )
        self._link_protocol(global_lifecycle, lifecycle)

    def _link_protocol(
        self,
        global_lifecycle: GlobalLifecycle,
        lifecycle: ProtocolLifecycle,
    ) -> None:
        if lifecycle.protocol == F1AP:
            global_lifecycle.f1ap_keys.add(lifecycle.local_key)
        else:
            global_lifecycle.ngap_keys.add(lifecycle.local_key)
        lifecycle.global_id = global_lifecycle.ue_correlation_id

    def _should_replace_lifecycle(
        self,
        lifecycle: ProtocolLifecycle,
        event: dict[str, Any],
    ) -> bool:
        global_lifecycle = self._globals.get(lifecycle.global_id)
        if global_lifecycle is not None and global_lifecycle.state in {
            STATE_CLOSED,
            STATE_FORCED_CLOSED,
        }:
            return True
        return False

    def _create_global(self, event_time_ns: int) -> GlobalLifecycle:
        ue_correlation_id = f"ue-online-{self._next_global:08d}"
        self._next_global += 1
        lifecycle = GlobalLifecycle(
            ue_correlation_id=ue_correlation_id,
            trace_id=None,
            parent_span_id=None,
            state=STATE_PENDING,
            first_seen_ns=event_time_ns,
            last_seen_ns=event_time_ns,
        )
        self._globals[ue_correlation_id] = lifecycle
        return lifecycle

    def _sync_lifecycle_trace(self, global_lifecycle: GlobalLifecycle) -> None:
        if not global_lifecycle.f1ap_keys or not global_lifecycle.ngap_keys:
            return
        if self.lifecycle_tracer is None:
            return

        if global_lifecycle.trace_id is None or global_lifecycle.parent_span_id is None:
            identity = self.lifecycle_tracer.start(
                global_lifecycle.ue_correlation_id,
                global_lifecycle.first_seen_ns,
                global_lifecycle.last_seen_ns,
                global_lifecycle.linked_protocols(),
            )
            global_lifecycle.trace_id = identity.trace_id
            global_lifecycle.parent_span_id = identity.span_id

        if global_lifecycle.state in {STATE_CLOSED, STATE_FORCED_CLOSED}:
            self.lifecycle_tracer.finish(
                global_lifecycle.ue_correlation_id,
                global_lifecycle.state,
                global_lifecycle.close_reason,
                global_lifecycle.linked_protocols(),
                global_lifecycle.first_seen_ns,
                global_lifecycle.last_seen_ns,
            )

    def _force_close_global(self, global_id: str, reason: str) -> None:
        lifecycle = self._globals.get(global_id)
        if lifecycle is None:
            return
        lifecycle.state = STATE_FORCED_CLOSED
        lifecycle.close_reason = reason
        self._sync_lifecycle_trace(lifecycle)

    def _expire_idle(self, now_ns: int) -> None:
        if self.idle_timeout_ns <= 0:
            return
        for global_lifecycle in self._globals.values():
            if global_lifecycle.state != STATE_PENDING:
                continue
            if now_ns - global_lifecycle.last_seen_ns > self.idle_timeout_ns:
                global_lifecycle.state = STATE_FORCED_CLOSED
                global_lifecycle.close_reason = "idle_timeout"

    def _evict_if_needed(self) -> None:
        if len(self._globals) <= self.max_lifecycles:
            return
        closed = [
            item
            for item in self._globals.values()
            if item.state in {STATE_CLOSED, STATE_FORCED_CLOSED}
        ]
        candidates = closed or list(self._globals.values())
        candidates.sort(key=lambda item: item.last_seen_ns)
        while len(self._globals) > self.max_lifecycles and candidates:
            victim = candidates.pop(0)
            self._remove_global(victim)

    def _remove_global(self, global_lifecycle: GlobalLifecycle) -> None:
        if global_lifecycle.state not in {STATE_CLOSED, STATE_FORCED_CLOSED}:
            self._force_close_global(global_lifecycle.ue_correlation_id, "evicted")
        else:
            self._sync_lifecycle_trace(global_lifecycle)
        for key in global_lifecycle.f1ap_keys:
            self._protocols[F1AP].pop(key, None)
            self._remove_active_alias(F1AP, key)
        for key in global_lifecycle.ngap_keys:
            self._protocols[NGAP].pop(key, None)
            self._remove_active_alias(NGAP, key)
        self._globals.pop(global_lifecycle.ue_correlation_id, None)

    def _response(
        self,
        global_lifecycle: GlobalLifecycle,
        protocol_lifecycle: ProtocolLifecycle,
    ) -> dict[str, Any]:
        return {
            "trace_id": global_lifecycle.trace_id,
            "parent_span_id": global_lifecycle.parent_span_id,
            "ue_correlation_id": global_lifecycle.ue_correlation_id,
            "state": global_lifecycle.state,
            "confidence": (
                "cross_protocol"
                if global_lifecycle.state in {STATE_MATCHED, STATE_CLOSING, STATE_CLOSED}
                and global_lifecycle.f1ap_keys
                and global_lifecycle.ngap_keys
                else "local"
            ),
            "linked_protocols": global_lifecycle.linked_protocols(),
            "close_reason": global_lifecycle.close_reason,
            "local_correlation_id": protocol_lifecycle.local_correlation_id,
            "local_state": (
                STATE_CLOSED if protocol_lifecycle.release_complete else STATE_PENDING
            ),
            "first_seen_unix_ns": global_lifecycle.first_seen_ns,
            "last_seen_unix_ns": global_lifecycle.last_seen_ns,
        }

    @staticmethod
    def _none_response(reason: str) -> dict[str, Any]:
        return {
            "trace_id": None,
            "parent_span_id": None,
            "ue_correlation_id": None,
            "state": "none",
            "confidence": "none",
            "linked_protocols": [],
            "close_reason": reason,
        }

    def _base_local_key(self, protocol: str, event: dict[str, Any]) -> str:
        local_id = event.get("local_correlation_id")
        if isinstance(local_id, str) and local_id:
            return local_id

        ids = normalize_ids(event)
        if protocol == F1AP:
            for name in ("du_id", "c_rnti", "cu_id"):
                if name in ids:
                    return f"f1ap-{name}-{ids[name]}"
        else:
            generation = ids.get("generation")
            if "ran_id" in ids and generation is not None:
                return f"ngap-ran-{ids['ran_id']}-gen-{generation}"
            for name in ("ran_id", "amf_id"):
                if name in ids:
                    return f"ngap-{name}-{ids[name]}"
        return f"{protocol}-unknown"

    def _active_key(self, protocol: str, base_key: str) -> str:
        return self._active_keys[protocol].get(base_key, base_key)

    def _next_reuse_key(self, protocol: str, base_key: str) -> str:
        counter_key = (protocol, base_key)
        self._reuse_generations[counter_key] += 1
        generation = self._reuse_generations[counter_key]
        return f"{base_key}#reuse-{generation}"

    def _remove_active_alias(self, protocol: str, local_key: str) -> None:
        stale = [
            base_key
            for base_key, active_key in self._active_keys[protocol].items()
            if active_key == local_key
        ]
        for base_key in stale:
            self._active_keys[protocol].pop(base_key, None)

    def _protocol_snapshot(self, protocol: str) -> dict[str, Any]:
        return {
            key: {
                "global_id": item.global_id,
                "local_correlation_id": item.local_correlation_id,
                "first_seen_ns": item.first_seen_ns,
                "last_seen_ns": item.last_seen_ns,
                "release_complete": item.release_complete,
                "ids": {name: sorted(values) for name, values in item.ids.items()},
                "messages": dict(item.messages),
            }
            for key, item in self._protocols[protocol].items()
        }


def is_ue_event(event: dict[str, Any]) -> bool:
    if isinstance(event.get("local_correlation_id"), str) and event["local_correlation_id"]:
        return True
    return bool(normalize_ids(event))


def normalize_ids(event: dict[str, Any]) -> dict[str, int]:
    protocol = normalize_protocol(event.get("protocol"))
    raw_ids = event.get("ids")
    ids: dict[str, int] = {}

    if isinstance(raw_ids, dict):
        for key, value in raw_ids.items():
            parsed = parse_int(value)
            if parsed is not None:
                ids[str(key)] = parsed

    if protocol == F1AP:
        aliases = {
            "du_id": ("f1ap.ue.du_id", "f1ap.gnb.du.ue.f1ap.id"),
            "cu_id": ("f1ap.ue.cu_id", "f1ap.gnb.cu.ue.f1ap.id"),
            "c_rnti": ("f1ap.ue.c_rnti", "f1ap.c.rnti"),
        }
    else:
        aliases = {
            "ran_id": ("ngap.ue.ran_id", "ngap.ran.ue.ngap.id"),
            "amf_id": ("ngap.ue.amf_id", "ngap.amf.ue.ngap.id"),
            "generation": ("ngap.ue.context_generation",),
        }

    attributes = event.get("attributes")
    if not isinstance(attributes, dict):
        attributes = {}

    for canonical, keys in aliases.items():
        if canonical in ids:
            continue
        for key in keys:
            parsed = parse_int(attributes.get(key))
            if parsed is not None:
                ids[canonical] = parsed
                break

    return ids


def normalize_protocol(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.lower()
    if value in {F1AP, NGAP}:
        return value
    return None


def parse_int(value: Any) -> Optional[int]:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value, 0)
        except ValueError:
            return None
    return None


def lifecycles_overlap(left: ProtocolLifecycle, right: ProtocolLifecycle) -> bool:
    return left.first_seen_ns <= right.last_seen_ns and right.first_seen_ns <= left.last_seen_ns


def release_gap_ns(left: ProtocolLifecycle, right: ProtocolLifecycle) -> Optional[int]:
    left_release = left.last_message_ns.get(RELEASE_COMPLETE)
    right_release = right.last_message_ns.get(RELEASE_COMPLETE)
    if left_release is None or right_release is None:
        return None
    return abs(left_release - right_release)
