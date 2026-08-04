import os
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class NgapUeBinding:
    correlation_id: str
    ran_ue_id: Optional[int] = None
    amf_ue_id: Optional[int] = None
    first_seen_ns: int = 0
    last_seen_ns: int = 0
    message_count: int = 0


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


class NgapCorrelator:
    def __init__(self, max_contexts: int = 10000) -> None:
        self.max_contexts = max_contexts
        self._by_ran: dict[int, NgapUeBinding] = {}
        self._by_amf: dict[int, NgapUeBinding] = {}

    @classmethod
    def from_env(cls) -> Optional["NgapCorrelator"]:
        if os.getenv("NGAP_ENABLE_CORRELATION", "1") == "0":
            return None
        max_contexts = parse_int(os.getenv("NGAP_CORRELATION_MAX_CONTEXTS", "10000"))
        return cls(max_contexts=max_contexts or 10000)

    def correlate(self, decoded: Any, event_time_ns: int) -> dict[str, bool | int | str]:
        fields = getattr(decoded, "fields", {})
        ran_ue_id = parse_int(fields.get("ngap.ran.ue.ngap.id"))
        amf_ue_id = parse_int(fields.get("ngap.amf.ue.ngap.id"))

        binding = self._lookup_binding(ran_ue_id, amf_ue_id)
        if binding is None and any(value is not None for value in (ran_ue_id, amf_ue_id)):
            binding = self._create_binding(ran_ue_id, amf_ue_id, event_time_ns)

        if binding is None:
            return {"ngap.correlation.kind": "none"}

        self._update_binding(binding, ran_ue_id, amf_ue_id, event_time_ns)
        attributes = self._ue_attributes(binding)
        if self._should_release_binding(decoded):
            attributes["ngap.ue.binding_released"] = True
            self._remove_binding(binding)
        return attributes

    def _lookup_binding(
        self,
        ran_ue_id: Optional[int],
        amf_ue_id: Optional[int],
    ) -> Optional[NgapUeBinding]:
        if ran_ue_id is not None and ran_ue_id in self._by_ran:
            return self._by_ran[ran_ue_id]
        if amf_ue_id is not None and amf_ue_id in self._by_amf:
            return self._by_amf[amf_ue_id]
        return None

    def _create_binding(
        self,
        ran_ue_id: Optional[int],
        amf_ue_id: Optional[int],
        event_time_ns: int,
    ) -> NgapUeBinding:
        self._evict_if_needed()

        seed = self._correlation_seed(ran_ue_id, amf_ue_id)
        binding = NgapUeBinding(
            correlation_id=f"ngap-ue-{seed}",
            ran_ue_id=ran_ue_id,
            amf_ue_id=amf_ue_id,
            first_seen_ns=event_time_ns,
            last_seen_ns=event_time_ns,
        )
        self._index_binding(binding)
        return binding

    def _evict_if_needed(self) -> None:
        bindings = {id(binding): binding for binding in self._by_ran.values()}
        bindings.update({id(binding): binding for binding in self._by_amf.values()})
        if len(bindings) < self.max_contexts:
            return
        oldest = min(bindings.values(), key=lambda binding: binding.last_seen_ns)
        self._remove_binding(oldest)

    @staticmethod
    def _correlation_seed(
        ran_ue_id: Optional[int],
        amf_ue_id: Optional[int],
    ) -> str:
        if ran_ue_id is not None:
            return f"ran-{ran_ue_id}"
        if amf_ue_id is not None:
            return f"amf-{amf_ue_id}"
        return "unknown"

    def _update_binding(
        self,
        binding: NgapUeBinding,
        ran_ue_id: Optional[int],
        amf_ue_id: Optional[int],
        event_time_ns: int,
    ) -> None:
        if ran_ue_id is not None:
            binding.ran_ue_id = ran_ue_id
        if amf_ue_id is not None:
            binding.amf_ue_id = amf_ue_id
        binding.last_seen_ns = event_time_ns
        binding.message_count += 1
        self._index_binding(binding)

    def _index_binding(self, binding: NgapUeBinding) -> None:
        if binding.ran_ue_id is not None:
            self._by_ran[binding.ran_ue_id] = binding
        if binding.amf_ue_id is not None:
            self._by_amf[binding.amf_ue_id] = binding

    def _remove_binding(self, binding: NgapUeBinding) -> None:
        if binding.ran_ue_id is not None:
            self._by_ran.pop(binding.ran_ue_id, None)
        if binding.amf_ue_id is not None:
            self._by_amf.pop(binding.amf_ue_id, None)

    @staticmethod
    def _should_release_binding(decoded: Any) -> bool:
        return getattr(decoded, "message_name", "") == "UEContextReleaseComplete"

    @staticmethod
    def _binding_state(binding: NgapUeBinding) -> str:
        if binding.ran_ue_id is not None and binding.amf_ue_id is not None:
            return "ran_amf_bound"
        if binding.ran_ue_id is not None:
            return "ran_only"
        if binding.amf_ue_id is not None:
            return "amf_only"
        return "unknown"

    def _ue_attributes(self, binding: NgapUeBinding) -> dict[str, bool | int | str]:
        attrs: dict[str, bool | int | str] = {
            "ngap.correlation.kind": "ue",
            "ngap.ue.correlation_id": binding.correlation_id,
            "ngap.ue.binding_state": self._binding_state(binding),
            "ngap.ue.message_count": binding.message_count,
            "ngap.ue.first_seen_unix_ns": binding.first_seen_ns,
            "ngap.ue.last_seen_unix_ns": binding.last_seen_ns,
        }
        if binding.ran_ue_id is not None:
            attrs["ngap.ue.ran_id"] = binding.ran_ue_id
        if binding.amf_ue_id is not None:
            attrs["ngap.ue.amf_id"] = binding.amf_ue_id
        return attrs
