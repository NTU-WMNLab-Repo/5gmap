#!/usr/bin/env python3
import json
import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from correlator.online.lifecycle_trace import LifecycleTraceEmitter
from correlator.online.state import OnlineCorrelatorState


def load_state_from_env(
    lifecycle_tracer: LifecycleTraceEmitter | None = None,
) -> OnlineCorrelatorState:
    return OnlineCorrelatorState(
        initial_gap_ms=float(os.getenv("ONLINE_CORRELATION_INITIAL_GAP_MS", "1000")),
        release_gap_ms=float(os.getenv("ONLINE_CORRELATION_RELEASE_GAP_MS", "5000")),
        idle_timeout_ms=float(os.getenv("ONLINE_CORRELATION_IDLE_TIMEOUT_MS", "60000")),
        max_lifecycles=int(os.getenv("ONLINE_CORRELATION_MAX_LIFECYCLES", "10000")),
        lifecycle_tracer=lifecycle_tracer,
    )


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(message)s")


class CorrelatorHandler(BaseHTTPRequestHandler):
    state: OnlineCorrelatorState

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._write_json({"status": "ok"})
            return
        if self.path == "/v1/state":
            self._write_json(self.state.snapshot())
            return
        self.send_error(404, "not found")

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/v1/events":
                self._write_json(self.state.handle_event(payload))
                return
            if self.path == "/v1/resolve":
                self._write_json(self.state.resolve(payload))
                return
            self.send_error(404, "not found")
        except json.JSONDecodeError:
            self.send_error(400, "invalid json")
        except Exception:
            logging.exception("Request failed")
            self.send_error(500, "internal error")

    def log_message(self, fmt: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), fmt % args)

    def _read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("content-length", "0"))
        body = self.rfile.read(content_length)
        if not body:
            return {}
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise json.JSONDecodeError("expected object", body.decode("utf-8"), 0)
        return payload

    def _write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run() -> None:
    configure_logging()
    host = os.getenv("ONLINE_CORRELATOR_HOST", "0.0.0.0")
    port = int(os.getenv("ONLINE_CORRELATOR_PORT", "8080"))
    lifecycle_tracer = LifecycleTraceEmitter(
        os.getenv("OTEL_SERVICE_NAME", "control-plane-correlator")
    )
    CorrelatorHandler.state = load_state_from_env(lifecycle_tracer)
    server = ThreadingHTTPServer((host, port), CorrelatorHandler)
    logging.info("Online correlator listening on %s:%d", host, port)
    server.serve_forever()


if __name__ == "__main__":
    run()
