import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Optional


F1AP_UE_KEYS = (
    "f1ap.ue.correlation_id",
    "f1ap.ue.du_id",
    "f1ap.ue.cu_id",
    "f1ap.ue.c_rnti",
    "f1ap.gnb.du.ue.f1ap.id",
    "f1ap.gnb.cu.ue.f1ap.id",
    "f1ap.c.rnti",
)
NGAP_UE_KEYS = (
    "ngap.ue.correlation_id",
    "ngap.ue.ran_id",
    "ngap.ue.amf_id",
    "ngap.ue.context_generation",
    "ngap.ran.ue.ngap.id",
    "ngap.amf.ue.ngap.id",
)


@dataclass
class OnlineCorrelationConfig:
    endpoint: str
    timeout_seconds: float
    fail_open: bool


class OnlineCorrelatorClient:
    def __init__(self, cfg: OnlineCorrelationConfig, service_name: str) -> None:
        self.cfg = cfg
        self.service_name = service_name
        self._failed_requests = 0

    @classmethod
    def from_env(cls, service_name: str) -> Optional["OnlineCorrelatorClient"]:
        if os.getenv("ONLINE_CORRELATION_ENABLED", "1") == "0":
            return None
        endpoint = os.getenv("ONLINE_CORRELATION_ENDPOINT", "").strip().rstrip("/")
        if not endpoint:
            return None
        timeout_ms = float(os.getenv("ONLINE_CORRELATION_TIMEOUT_MS", "100"))
        fail_open = os.getenv("ONLINE_CORRELATION_FAIL_OPEN", "1") != "0"
        return cls(
            OnlineCorrelationConfig(
                endpoint=endpoint,
                timeout_seconds=timeout_ms / 1000.0,
                fail_open=fail_open,
            ),
            service_name=service_name,
        )

    def correlate(self, event: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/events", event)

    def resolve(self, event: dict[str, Any]) -> dict[str, Any]:
        return self._post("/v1/resolve", event)

    def _post(self, path: str, event: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.cfg.endpoint}{path}"
        body = json.dumps(event, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=body,
            headers={"content-type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.cfg.timeout_seconds,
            ) as response:
                payload = response.read().decode("utf-8")
            return json.loads(payload)
        except (OSError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            self._failed_requests += 1
            if self._failed_requests == 1 or self._failed_requests % 100 == 0:
                logging.exception(
                    "Online correlator request failed; failures=%d",
                    self._failed_requests,
                )
            if self.cfg.fail_open:
                return {
                    "trace_id": None,
                    "parent_span_id": None,
                    "ue_correlation_id": None,
                    "state": "unavailable",
                    "confidence": "none",
                    "linked_protocols": [],
                    "close_reason": "correlator_unavailable",
                    "error": "online_correlator_unavailable",
                }
            raise


def is_online_ue_candidate(protocol: str, attributes: dict[str, Any]) -> bool:
    keys = F1AP_UE_KEYS if protocol == "f1ap" else NGAP_UE_KEYS
    for key in keys:
        value = attributes.get(key)
        if value is not None and value != "":
            return True
    return False


def build_online_event(
    service_name: str,
    protocol: str,
    direction: str,
    message_name: str,
    procedure_name: str,
    event_time_ns: int,
    attributes: dict[str, Any],
) -> dict[str, Any]:
    ids = protocol_ids(protocol, attributes)
    local_key = f"{protocol}.ue.correlation_id"
    return {
        "service_name": service_name,
        "protocol": protocol,
        "local_correlation_id": attributes.get(local_key),
        "direction": direction,
        "message_name": message_name,
        "procedure_name": procedure_name,
        "event_time_unix_ns": event_time_ns,
        "ids": ids,
        "release_complete": message_name == "UEContextReleaseComplete"
        or bool(attributes.get(f"{protocol}.ue.binding_released")),
    }


def protocol_ids(protocol: str, attributes: dict[str, Any]) -> dict[str, Any]:
    if protocol == "f1ap":
        return {
            "du_id": first_present(
                attributes,
                "f1ap.ue.du_id",
                "f1ap.gnb.du.ue.f1ap.id",
            ),
            "cu_id": first_present(
                attributes,
                "f1ap.ue.cu_id",
                "f1ap.gnb.cu.ue.f1ap.id",
            ),
            "c_rnti": first_present(attributes, "f1ap.ue.c_rnti", "f1ap.c.rnti"),
        }
    return {
        "ran_id": first_present(
            attributes,
            "ngap.ue.ran_id",
            "ngap.ran.ue.ngap.id",
        ),
        "amf_id": first_present(
            attributes,
            "ngap.ue.amf_id",
            "ngap.amf.ue.ngap.id",
        ),
        "generation": attributes.get("ngap.ue.context_generation"),
    }


def first_present(attributes: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = attributes.get(key)
        if value is not None:
            return value
    return None
