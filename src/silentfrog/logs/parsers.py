"""Access-log parsers (v2.0 V13).

Handles the Common Log Format, the Combined Log Format (CLF + referer +
user-agent), and JSON access logs (Apache/Nginx). Each line becomes a
``LogEntry``; unparseable lines are skipped. Never raises.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

# 1.2.3.4 - - [10/Oct/2026:13:55:36 +0000] "GET /path HTTP/1.1" 200 2326 "ref" "ua"
_CLF_RE = re.compile(
    r"^(?P<ip>\S+)\s+\S+\s+\S+\s+\[(?P<ts>[^\]]+)\]\s+"
    r'"(?P<method>[A-Z]+)\s+(?P<path>\S+)\s+\S+"\s+'
    r"(?P<status>\d{3})\s+(?P<bytes>\d+|-)"
    r'(?:\s+"(?P<ref>[^"]*)"\s+"(?P<ua>[^"]*)")?'
)


@dataclass(frozen=True)
class LogEntry:
    ip: str
    timestamp: str
    method: str
    path: str
    status: int
    user_agent: str = ""
    bytes: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "ip": self.ip,
            "timestamp": self.timestamp,
            "method": self.method,
            "path": self.path,
            "status": self.status,
            "user_agent": self.user_agent,
            "bytes": self.bytes,
        }


def _to_int(value: object) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


def _path_only(request_or_path: str) -> str:
    """Normalise a request target to just its path (drop scheme/host/query)."""
    target = request_or_path.split()[1] if request_or_path[:4].isupper() and " " in request_or_path else request_or_path
    split = urlsplit(target)
    return split.path or target


def _parse_clf(line: str) -> LogEntry | None:
    match = _CLF_RE.match(line.strip())
    if not match:
        return None
    data = match.groupdict()
    return LogEntry(
        ip=data["ip"],
        timestamp=data["ts"],
        method=data["method"],
        path=_path_only(data["path"]),
        status=_to_int(data["status"]),
        user_agent=data.get("ua") or "",
        bytes=_to_int(data["bytes"]) if data["bytes"] != "-" else 0,
    )


_JSON_REQUEST_KEYS = ("request", "request_line")
_JSON_UA_KEYS = ("http_user_agent", "user_agent", "agent")
_JSON_IP_KEYS = ("remote_addr", "ip", "client_ip")
_JSON_BYTE_KEYS = ("body_bytes_sent", "bytes", "bytes_sent")


def _first(data: dict[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return str(data[key])
    return ""


def _parse_json(line: str) -> LogEntry | None:
    try:
        data = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    request = _first(data, _JSON_REQUEST_KEYS)
    method = ""
    path = _first(data, ("uri", "path", "request_uri"))
    if request:
        parts = request.split()
        method = parts[0] if parts else ""
        path = parts[1] if len(parts) > 1 else path
    return LogEntry(
        ip=_first(data, _JSON_IP_KEYS),
        timestamp=_first(data, ("time", "time_local", "timestamp", "@timestamp")),
        method=method or _first(data, ("method", "request_method")),
        path=_path_only(path) if path else "",
        status=_to_int(data.get("status") or data.get("response_status")),
        user_agent=_first(data, _JSON_UA_KEYS),
        bytes=_to_int(_first(data, _JSON_BYTE_KEYS) or 0),
    )


def parse_log_line(line: str) -> LogEntry | None:
    stripped = line.strip()
    if not stripped:
        return None
    if stripped.startswith("{"):
        return _parse_json(stripped)
    return _parse_clf(stripped)


def parse_log_text(text: str) -> list[LogEntry]:
    entries: list[LogEntry] = []
    for line in (text or "").splitlines():
        entry = parse_log_line(line)
        if entry is not None and entry.path:
            entries.append(entry)
    return entries


__all__ = ["LogEntry", "parse_log_line", "parse_log_text"]
