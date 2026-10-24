import json
import os
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from common import utc_now


DB_PATH = os.environ.get("DB_PATH", "/data/observations.sqlite3")
CONFIG_PATH = os.environ.get("CONFIG_PATH", "/config/fixtures.json")
LOCK = threading.Lock()
LAST_PRUNE = 0.0


def connect():
    connection = sqlite3.connect(DB_PATH, timeout=5)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""CREATE TABLE IF NOT EXISTS batches (
        probe_id TEXT NOT NULL, boot_id TEXT NOT NULL, sequence INTEGER NOT NULL,
        received_at TEXT NOT NULL, PRIMARY KEY(probe_id, boot_id, sequence))""")
    connection.execute("""CREATE TABLE IF NOT EXISTS observations (
        id INTEGER PRIMARY KEY, probe_id TEXT NOT NULL, boot_id TEXT NOT NULL,
        sequence INTEGER NOT NULL, subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL,
        metric TEXT NOT NULL, collected_at TEXT NOT NULL, received_at TEXT NOT NULL,
        payload TEXT NOT NULL)""")
    connection.execute("""CREATE INDEX IF NOT EXISTS observation_lookup
        ON observations(subject_kind, subject_id, metric, collected_at DESC, id DESC)""")
    connection.execute("CREATE INDEX IF NOT EXISTS observation_received ON observations(received_at)")
    connection.execute("""CREATE TABLE IF NOT EXISTS latest (
        subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL, metric TEXT NOT NULL,
        probe_id TEXT NOT NULL, collected_at TEXT NOT NULL, received_at TEXT NOT NULL,
        payload TEXT NOT NULL, PRIMARY KEY(subject_kind, subject_id, metric))""")
    return connection


def initialize():
    with closing(connect()) as db, db:
        if db.execute("SELECT 1 FROM latest LIMIT 1").fetchone() is None:
            db.execute("""INSERT INTO latest
                (subject_kind, subject_id, metric, probe_id, collected_at, received_at, payload)
                SELECT subject_kind, subject_id, metric, probe_id, collected_at, received_at, payload
                FROM (
                    SELECT subject_kind, subject_id, metric, probe_id, collected_at,
                           received_at, payload, ROW_NUMBER() OVER (
                        PARTITION BY subject_kind, subject_id, metric
                        ORDER BY collected_at DESC, id DESC) AS rank
                    FROM observations
                ) WHERE rank = 1""")


def is_stale(record, now):
    timestamp = record.get("observed_at") or record["collected_at"]
    sampled = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return (now - sampled).total_seconds() > record["ttl_seconds"]


SNAPSHOT_KINDS = {"node", "pod", "container", "service", "gpu", "link"}
REQUIRED_NODE_METRICS = ("node_ready", "node_allocatable_cpu", "node_allocatable_memory",
                         "node_cpu_usage_cores", "node_memory_working_set_bytes")


def decision_snapshot(rows, now):
    records = [(json.loads(payload), received_at) for payload, received_at in rows]
    inventories = [record for record, _ in records
                   if record["subject_kind"] == "inventory"
                   and record["metric"] == "k8s_object_uids"]
    inventory = max(inventories, key=lambda item: item["collected_at"], default=None)
    if inventory is None or inventory.get("status") != "ok" or is_stale(inventory, now):
        raise ValueError("cluster inventory missing or stale")
    members = inventory.get("value")
    if not isinstance(members, dict) or any(
        not isinstance(members.get(kind), list) or
        any(not isinstance(uid, str) for uid in members[kind])
        for kind in ("node", "pod", "container", "service")
    ):
        raise ValueError("invalid cluster inventory")
    active = {kind: set(uids) for kind, uids in members.items()}
    selected = []
    unavailable = []
    excluded = {"event": 0, "other": 0, "retired": 0, "stale": 0, "non_ok": 0}
    for record, received_at in records:
        kind = record["subject_kind"]
        if kind == "event":
            excluded["event"] += 1
            continue
        if kind not in SNAPSHOT_KINDS:
            excluded["other"] += 1
            continue
        if kind in ("gpu", "link"):
            present = record.get("node_uid") in active["node"]
        else:
            present = record["subject_id"] in active[kind]
        if not present:
            excluded["retired"] += 1
            continue
        if is_stale(record, now):
            excluded["stale"] += 1
            continue
        if record["status"] != "ok":
            excluded["non_ok"] += 1
            unavailable.append({key: record.get(key) for key in
                                ("subject_kind", "subject_id", "node_uid", "site_id", "metric",
                                 "status", "reason", "source", "observed_at", "collected_at")})
            continue
        record["received_at"] = received_at
        selected.append(record)
    selected.sort(key=lambda item: (item["subject_kind"], item["subject_id"], item["metric"]))
    available = {(item["subject_kind"], item["subject_id"], item["metric"]) for item in selected}
    missing = [{"subject_kind": "node", "subject_id": uid, "metric": metric}
               for uid in sorted(active["node"]) for metric in REQUIRED_NODE_METRICS
               if ("node", uid, metric) not in available]
    return {"inventory": {"source": inventory["source"],
                          "collected_at": inventory["collected_at"],
                          "ttl_seconds": inventory["ttl_seconds"],
                          "counts": {kind: len(active[kind]) for kind in
                                     ("node", "pod", "container", "service")}},
            "observations": selected, "unavailable": unavailable, "missing": missing,
            "excluded": excluded}


def validate_batch(body):
    if not isinstance(body, dict):
        raise ValueError("batch must be an object")
    if body.get("schema_version") != 1:
        raise ValueError("unsupported schema_version")
    for field in ("probe_id", "boot_id"):
        if not isinstance(body.get(field), str) or not body[field] or len(body[field]) > 160:
            raise ValueError(f"invalid {field}")
    if type(body.get("sequence")) is not int or body["sequence"] < 1:
        raise ValueError("invalid sequence")
    records = body.get("observations")
    if not isinstance(records, list) or len(records) > 5000:
        raise ValueError("invalid observations")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid record")
        for field in ("subject_kind", "subject_id", "metric", "source", "unit", "collected_at"):
            if not isinstance(record.get(field), str) or not record[field] or len(record[field]) > 256:
                raise ValueError(f"invalid {field}")
        for field in ("collected_at", "observed_at"):
            if record.get(field) is not None:
                timestamp = datetime.fromisoformat(record[field].replace("Z", "+00:00"))
                if timestamp.tzinfo is None or timestamp.utcoffset().total_seconds() != 0:
                    raise ValueError(f"{field} must be UTC")
        if record.get("status") not in ("ok", "unknown", "unsupported", "error"):
            raise ValueError("invalid status")
        if record.get("provenance") not in ("measured", "configured", "simulated"):
            raise ValueError("invalid provenance")
        if type(record.get("ttl_seconds")) is not int or not 1 <= record["ttl_seconds"] <= 86400:
            raise ValueError("invalid ttl_seconds")
        if record["status"] == "ok" and record.get("value") is None:
            raise ValueError("ok record requires value")
    return records


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        if len(args) > 1 and str(args[1]) == "200":
            return
        super().log_message(format, *args)

    def reply(self, status, body):
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_POST(self):
        global LAST_PRUNE
        if self.path != "/v1/observations":
            return self.reply(404, {"error": "not found"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 2_000_000:
                return self.reply(413, {"error": "batch too large or empty"})
            body = json.loads(self.rfile.read(size))
            records = validate_batch(body)
            received = utc_now()
            with LOCK, closing(connect()) as db, db:
                cursor = db.execute("INSERT OR IGNORE INTO batches VALUES (?, ?, ?, ?)",
                                    (body["probe_id"], body["boot_id"], body["sequence"], received))
                duplicate = cursor.rowcount == 0
                if not duplicate:
                    rows = [
                        (body["probe_id"], body["boot_id"], body["sequence"],
                         item["subject_kind"], item["subject_id"], item["metric"],
                         item["collected_at"], received, json.dumps(item)) for item in records
                    ]
                    db.executemany("""INSERT INTO observations
                        (probe_id, boot_id, sequence, subject_kind, subject_id, metric,
                         collected_at, received_at, payload)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows)
                    db.executemany("""INSERT INTO latest
                        (probe_id, subject_kind, subject_id, metric, collected_at, received_at, payload)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(subject_kind, subject_id, metric) DO UPDATE SET
                            probe_id=excluded.probe_id, collected_at=excluded.collected_at,
                            received_at=excluded.received_at, payload=excluded.payload
                        WHERE excluded.collected_at >= latest.collected_at""", [
                        (probe_id, kind, subject_id, metric, collected_at, received_at, payload)
                        for probe_id, _boot_id, _sequence, kind, subject_id, metric,
                            collected_at, received_at, payload in rows
                    ])
                if time.monotonic() - LAST_PRUNE >= 3600:
                    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
                    db.execute("DELETE FROM observations WHERE received_at < ?", (cutoff,))
                    db.execute("DELETE FROM batches WHERE received_at < ?", (cutoff,))
                    db.execute("DELETE FROM latest WHERE received_at < ?", (cutoff,))
                    LAST_PRUNE = time.monotonic()
            self.reply(200, {"stored": not duplicate, "duplicate": duplicate, "received_at": received})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            print(f"receiver error: {exc}", flush=True)
            self.reply(500, {"error": "storage error"})

    def do_GET(self):
        route = urlsplit(self.path)
        if route.path in ("/healthz", "/readyz"):
            try:
                with closing(connect()) as db:
                    db.execute("SELECT 1").fetchone()
                return self.reply(200, {"status": "ok"})
            except Exception:
                return self.reply(503, {"status": "unavailable"})
        if route.path == "/v1/summary":
            with LOCK, closing(connect()) as db:
                rows = db.execute("SELECT probe_id, payload FROM latest").fetchall()
            now = datetime.now(timezone.utc)
            summary = {"total": len(rows), "stale": 0, "by_kind": {}, "by_status": {},
                       "by_probe": {}, "non_ok": []}
            for probe_id, payload in rows:
                record = json.loads(payload)
                kind, status = record["subject_kind"], record["status"]
                summary["by_kind"][kind] = summary["by_kind"].get(kind, 0) + 1
                summary["by_status"][status] = summary["by_status"].get(status, 0) + 1
                summary["by_probe"][probe_id] = summary["by_probe"].get(probe_id, 0) + 1
                summary["stale"] += is_stale(record, now)
                if status != "ok" and len(summary["non_ok"]) < 10:
                    summary["non_ok"].append({"subject_kind": kind, "subject_id": record["subject_id"],
                                              "metric": record["metric"], "status": status,
                                              "reason": record.get("reason")})
            with open(CONFIG_PATH, encoding="utf-8") as handle:
                summary["fixtures_version"] = json.load(handle).get("version")
            return self.reply(200, {"schema_version": 1, "generated_at": utc_now(), **summary})
        if route.path == "/v1/snapshot":
            query = parse_qs(route.query)
            try:
                limit = int(query.get("limit", ["10000"])[0])
                offset = int(query.get("offset", ["0"])[0])
                if not 1 <= limit <= 10000 or offset < 0:
                    raise ValueError("invalid limit or offset")
            except ValueError as exc:
                return self.reply(400, {"error": str(exc)})
            with LOCK, closing(connect()) as db:
                rows = db.execute("SELECT payload, received_at FROM latest").fetchall()
            now = datetime.now(timezone.utc)
            try:
                snapshot = decision_snapshot(rows, now)
            except ValueError as exc:
                return self.reply(503, {"error": str(exc), "generated_at": now.isoformat()})
            selected = snapshot["observations"]
            for key, field in (("kind", "subject_kind"), ("metric", "metric"), ("site", "site_id")):
                value = query.get(key, [None])[0]
                if value:
                    selected = [record for record in selected if record.get(field) == value]
            total = len(selected)
            snapshot["observations"] = selected[offset:offset + limit]
            with open(CONFIG_PATH, encoding="utf-8") as handle:
                fixtures = json.load(handle)
            return self.reply(200, {"schema_version": 1, "generated_at": now.isoformat(),
                                    "total": total,
                                    "next_offset": offset + len(snapshot["observations"])
                                    if offset + len(snapshot["observations"]) < total else None,
                                    **snapshot, "fixtures": fixtures})
        if route.path != "/v1/state":
            return self.reply(404, {"error": "not found"})
        query = parse_qs(route.query)
        try:
            limit = int(query.get("limit", ["10000"])[0])
            offset = int(query.get("offset", ["0"])[0])
            if not 1 <= limit <= 10000 or offset < 0:
                raise ValueError("invalid limit or offset")
        except ValueError as exc:
            return self.reply(400, {"error": str(exc)})
        filters = []
        values = []
        for key, column in (("kind", "subject_kind"), ("metric", "metric")):
            value = query.get(key, [None])[0]
            if value:
                filters.append(f"{column} = ?")
                values.append(value)
        where = " WHERE " + " AND ".join(filters) if filters else ""
        with LOCK, closing(connect()) as db:
            total = db.execute("SELECT count(*) FROM latest" + where, values).fetchone()[0]
            rows = db.execute("SELECT payload, received_at FROM latest" + where +
                              " ORDER BY received_at DESC LIMIT ? OFFSET ?", values + [limit, offset]).fetchall()
        now = datetime.now(timezone.utc)
        state = []
        for payload, received_at in rows:
            record = json.loads(payload)
            record["stale"] = is_stale(record, now)
            record["received_at"] = received_at
            state.append(record)
        with open(CONFIG_PATH, encoding="utf-8") as handle:
            fixtures = json.load(handle)
        self.reply(200, {"schema_version": 1, "generated_at": utc_now(), "total": total,
                         "next_offset": offset + len(state) if offset + len(state) < total else None,
                         "observations": state, "fixtures": fixtures})


if __name__ == "__main__":
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    initialize()
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
