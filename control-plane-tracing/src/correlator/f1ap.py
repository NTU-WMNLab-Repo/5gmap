import os
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class UeBinding:
    correlation_id: str
    du_ue_id: Optional[int] = None
    cu_ue_id: Optional[int] = None
    c_rnti: Optional[int] = None
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


class F1apCorrelator:
    def __init__(self, max_contexts: int = 10000) -> None:
        self.max_contexts = max_contexts
        self._by_du: dict[int, UeBinding] = {}
        self._by_cu: dict[int, UeBinding] = {}
        self._by_rnti: dict[int, UeBinding] = {}

    @classmethod
    def from_env(cls) -> Optional["F1apCorrelator"]:
        if os.getenv("F1AP_ENABLE_CORRELATION", "1") == "0":
            return None
        max_contexts = parse_int(os.getenv("F1AP_CORRELATION_MAX_CONTEXTS", "10000"))
        return cls(max_contexts=max_contexts or 10000)

    def correlate(self, decoded: Any, event_time_ns: int) -> dict[str, bool | int | str]:
        fields = getattr(decoded, "fields", {})
        du_ue_id = parse_int(fields.get("f1ap.gnb.du.ue.f1ap.id"))
        cu_ue_id = parse_int(fields.get("f1ap.gnb.cu.ue.f1ap.id"))
        c_rnti = parse_int(fields.get("f1ap.c.rnti"))

        binding = self._lookup_binding(du_ue_id, cu_ue_id, c_rnti)
        if binding is None and any(value is not None for value in (du_ue_id, cu_ue_id, c_rnti)):
            binding = self._create_binding(du_ue_id, cu_ue_id, c_rnti, event_time_ns)

        attributes: dict[str, bool | int | str] = {}
        if binding is not None:
            self._update_binding(binding, du_ue_id, cu_ue_id, c_rnti, event_time_ns)
            attributes.update(self._ue_attributes(binding))
            if self._should_release_binding(decoded):
                attributes["f1ap.ue.binding_released"] = True
                self._remove_binding(binding)
            return attributes

        transaction_id = parse_int(fields.get("f1ap.transaction.id"))
        if transaction_id is not None:
            procedure_name = getattr(decoded, "procedure_name", "unknown")
            attributes["f1ap.correlation.kind"] = "transaction"
            attributes["f1ap.transaction.correlation_id"] = (
                f"f1ap-txn-{procedure_name}-{transaction_id}"
            )
            attributes["f1ap.transaction.id"] = transaction_id
        else:
            attributes["f1ap.correlation.kind"] = "none"

        return attributes

    def _lookup_binding(
        self,
        du_ue_id: Optional[int],
        cu_ue_id: Optional[int],
        c_rnti: Optional[int],
    ) -> Optional[UeBinding]:
        if du_ue_id is not None and du_ue_id in self._by_du:
            return self._by_du[du_ue_id]
        if cu_ue_id is not None and cu_ue_id in self._by_cu:
            return self._by_cu[cu_ue_id]
        if c_rnti is not None and c_rnti in self._by_rnti:
            return self._by_rnti[c_rnti]
        return None

    def _create_binding(
        self,
        du_ue_id: Optional[int],
        cu_ue_id: Optional[int],
        c_rnti: Optional[int],
        event_time_ns: int,
    ) -> UeBinding:
        self._evict_if_needed()

        seed = self._correlation_seed(du_ue_id, cu_ue_id, c_rnti)
        binding = UeBinding(
            correlation_id=f"f1ap-ue-{seed}",
            du_ue_id=du_ue_id,
            cu_ue_id=cu_ue_id,
            c_rnti=c_rnti,
            first_seen_ns=event_time_ns,
            last_seen_ns=event_time_ns,
        )
        self._index_binding(binding)
        return binding

    def _evict_if_needed(self) -> None:
        bindings = {id(binding): binding for binding in self._by_du.values()}
        bindings.update({id(binding): binding for binding in self._by_cu.values()})
        bindings.update({id(binding): binding for binding in self._by_rnti.values()})
        if len(bindings) < self.max_contexts:
            return
        oldest = min(bindings.values(), key=lambda binding: binding.last_seen_ns)
        self._remove_binding(oldest)

    @staticmethod
    def _correlation_seed(
        du_ue_id: Optional[int],
        cu_ue_id: Optional[int],
        c_rnti: Optional[int],
    ) -> str:
        if du_ue_id is not None:
            return f"du-{du_ue_id}"
        if cu_ue_id is not None:
            return f"cu-{cu_ue_id}"
        if c_rnti is not None:
            return f"rnti-{c_rnti}"
        return "unknown"

    def _update_binding(
        self,
        binding: UeBinding,
        du_ue_id: Optional[int],
        cu_ue_id: Optional[int],
        c_rnti: Optional[int],
        event_time_ns: int,
    ) -> None:
        if du_ue_id is not None:
            binding.du_ue_id = du_ue_id
        if cu_ue_id is not None:
            binding.cu_ue_id = cu_ue_id
        if c_rnti is not None:
            binding.c_rnti = c_rnti
        binding.last_seen_ns = event_time_ns
        binding.message_count += 1
        self._index_binding(binding)

    def _index_binding(self, binding: UeBinding) -> None:
        if binding.du_ue_id is not None:
            self._by_du[binding.du_ue_id] = binding
        if binding.cu_ue_id is not None:
            self._by_cu[binding.cu_ue_id] = binding
        if binding.c_rnti is not None:
            self._by_rnti[binding.c_rnti] = binding

    def _remove_binding(self, binding: UeBinding) -> None:
        if binding.du_ue_id is not None:
            self._by_du.pop(binding.du_ue_id, None)
        if binding.cu_ue_id is not None:
            self._by_cu.pop(binding.cu_ue_id, None)
        if binding.c_rnti is not None:
            self._by_rnti.pop(binding.c_rnti, None)

    @staticmethod
    def _should_release_binding(decoded: Any) -> bool:
        return getattr(decoded, "message_name", "") == "UEContextReleaseComplete"

    @staticmethod
    def _binding_state(binding: UeBinding) -> str:
        if binding.cu_ue_id is not None and binding.du_ue_id is not None:
            return "cu_du_bound"
        if binding.du_ue_id is not None:
            return "du_only"
        if binding.cu_ue_id is not None:
            return "cu_only"
        if binding.c_rnti is not None:
            return "rnti_only"
        return "unknown"

    def _ue_attributes(self, binding: UeBinding) -> dict[str, bool | int | str]:
        attrs: dict[str, bool | int | str] = {
            "f1ap.correlation.kind": "ue",
            "f1ap.ue.correlation_id": binding.correlation_id,
            "f1ap.ue.binding_state": self._binding_state(binding),
            "f1ap.ue.message_count": binding.message_count,
            "f1ap.ue.first_seen_unix_ns": binding.first_seen_ns,
            "f1ap.ue.last_seen_unix_ns": binding.last_seen_ns,
        }
        if binding.du_ue_id is not None:
            attrs["f1ap.ue.du_id"] = binding.du_ue_id
        if binding.cu_ue_id is not None:
            attrs["f1ap.ue.cu_id"] = binding.cu_ue_id
        if binding.c_rnti is not None:
            attrs["f1ap.ue.c_rnti"] = binding.c_rnti
            attrs["f1ap.ue.c_rnti.hex"] = f"0x{binding.c_rnti:04x}"
        return attrs
