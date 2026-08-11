import unittest
from types import SimpleNamespace

from correlator.online.state import (
    OnlineCorrelatorState,
    STATE_CLOSED,
    STATE_FORCED_CLOSED,
    STATE_MATCHED,
)


class FakeLifecycleTracer:
    def __init__(self) -> None:
        self.started = []
        self.finished = []

    def start(self, ue_correlation_id, start_time_ns, bound_time_ns, linked_protocols):
        self.started.append(
            (ue_correlation_id, start_time_ns, bound_time_ns, linked_protocols)
        )
        return SimpleNamespace(
            trace_id="1" * 32,
            span_id="2" * 16,
        )

    def finish(
        self,
        ue_correlation_id,
        state,
        close_reason,
        linked_protocols,
        start_time_ns,
        end_time_ns,
    ):
        self.finished.append(
            (ue_correlation_id, state, close_reason, start_time_ns, end_time_ns)
        )


def event(protocol, local_id, message_name, event_time_ns, ids, release=False):
    return {
        "protocol": protocol,
        "local_correlation_id": local_id,
        "message_name": message_name,
        "event_time_unix_ns": event_time_ns,
        "ids": ids,
        "release_complete": release,
    }


class OnlineCorrelatorStateTest(unittest.TestCase):
    def test_matched_lifecycle_survives_idle_until_both_releases(self):
        tracer = FakeLifecycleTracer()
        state = OnlineCorrelatorState(
            idle_timeout_ms=60_000,
            lifecycle_tracer=tracer,
        )
        start = 1_000_000_000

        pending = state.handle_event(
            event(
                "f1ap",
                "f1ap-ue-du-10",
                "InitialULRRCMessageTransfer",
                start,
                {"du_id": 10},
            )
        )
        self.assertIsNone(pending["trace_id"])
        self.assertIsNone(pending["parent_span_id"])
        state.handle_event(
            event(
                "f1ap",
                "f1ap-ue-du-10",
                "DLRRCMessageTransfer",
                start + 1_000_000,
                {"du_id": 10, "cu_id": 1},
            )
        )
        matched = state.handle_event(
            event(
                "ngap",
                "ngap-ue-ran-1-gen-1",
                "InitialUEMessage",
                start + 2_000_000,
                {"ran_id": 1, "generation": 1},
            )
        )

        self.assertEqual(matched["state"], STATE_MATCHED)
        self.assertEqual(matched["trace_id"], "1" * 32)
        self.assertEqual(matched["parent_span_id"], "2" * 16)
        self.assertEqual(len(tracer.started), 1)
        self.assertEqual(tracer.started[0][1:3], (start, start + 2_000_000))

        after_idle = state.handle_event(
            event(
                "f1ap",
                "f1ap-ue-du-10",
                "ULRRCMessageTransfer",
                start + 120_000_000_000,
                {"du_id": 10, "cu_id": 1},
            )
        )
        self.assertEqual(after_idle["state"], STATE_MATCHED)
        self.assertEqual(after_idle["trace_id"], "1" * 32)

        state.handle_event(
            event(
                "f1ap",
                "f1ap-ue-du-10",
                "UEContextReleaseComplete",
                start + 120_100_000_000,
                {"du_id": 10, "cu_id": 1},
                release=True,
            )
        )
        closed = state.handle_event(
            event(
                "ngap",
                "ngap-ue-ran-1-gen-1",
                "UEContextReleaseComplete",
                start + 120_200_000_000,
                {"ran_id": 1, "amf_id": 1, "generation": 1},
                release=True,
            )
        )
        self.assertEqual(closed["state"], STATE_CLOSED)
        self.assertEqual(closed["trace_id"], "1" * 32)
        self.assertEqual(len(tracer.finished), 1)
        self.assertEqual(
            tracer.finished[0][3:],
            (start, start + 120_200_000_000),
        )

    def test_idle_timeout_only_force_closes_pending_lifecycle(self):
        state = OnlineCorrelatorState(idle_timeout_ms=60_000)
        start = 1_000_000_000
        state.handle_event(
            event(
                "f1ap",
                "f1ap-ue-du-10",
                "InitialULRRCMessageTransfer",
                start,
                {"du_id": 10},
            )
        )
        state.handle_event(
            event(
                "ngap",
                "ngap-ue-ran-99-gen-1",
                "InitialUEMessage",
                start + 120_000_000_000,
                {"ran_id": 99, "generation": 1},
            )
        )
        snapshot = state.snapshot()
        self.assertEqual(
            snapshot["globals"]["ue-online-00000001"]["state"],
            STATE_FORCED_CLOSED,
        )


if __name__ == "__main__":
    unittest.main()
