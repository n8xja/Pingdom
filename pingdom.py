#!/usr/bin/env python3
"""
pingdom.py - Network Quality Monitor
Version: 1.2.7

Monitors network latency by pinging the local gateway, next-hop router, and
an arbitrary host.  For each host the script maintains two dedicated log files:

  rtt_<role>_<host>.log     - timestamped RTT statistics (min/avg/max/stddev)
  packets_<role>_<host>.log - timestamped packets sent/received/lost + cumulative totals

All events are written to a central event log; threshold breaches go to a
separate alert log.  Persistent records are stored as JSON and are also
exported to a web-readable JSON summary consumed by the pingdom dashboard.
"""

import os
import re
import sys
import json
import time
import logging
import argparse
import ipaddress
import subprocess
import statistics
import traceback
from datetime import datetime, timezone
from pathlib import Path
from logging.handlers import RotatingFileHandler

# ──────────────────────────────────────────────
# VERSION
# ──────────────────────────────────────────────
VERSION = "1.2.7"

# ──────────────────────────────────────────────
# DEFAULT SCRIPT-LEVEL PATH VARIABLES
# (override via env vars; fall back to CWD)
# ──────────────────────────────────────────────
_SCRIPT_CONFIG_PATH: str = ""   # e.g. "/etc/pingdom"
_SCRIPT_LOG_PATH: str    = ""   # e.g. "/var/log/pingdom"
_SCRIPT_WEB_PATH: str    = ""   # e.g. "/var/www/pingdom"

# ──────────────────────────────────────────────
# RESOLVE PATHS
# ──────────────────────────────────────────────
def _resolve_path(env_var: str, script_var: str, subdir: str) -> Path:
    """Priority: env var -> script var -> CWD/<subdir>."""
    from_env = os.environ.get(env_var, "").strip()
    if from_env:
        return Path(from_env)
    if script_var.strip():
        return Path(script_var)
    return Path.cwd() / subdir


CONFIG_DIR = _resolve_path("PINGDOM_CONFIG_PATH", _SCRIPT_CONFIG_PATH, "config")
LOG_DIR    = _resolve_path("PINGDOM_LOG_PATH",    _SCRIPT_LOG_PATH,    "logs")
WEB_DIR    = _resolve_path("PINGDOM_WEB_PATH",    _SCRIPT_WEB_PATH,    "web")

CONFIG_FILE        = CONFIG_DIR / "pingdom.json"
EVENT_LOG          = LOG_DIR / "pingdom_events.log"
ALERT_LOG          = LOG_DIR / "pingdom_alerts.log"
RECORDS_FILE       = LOG_DIR / "pingdom_records.json"
PACKET_TOTALS_FILE = LOG_DIR / "pingdom_packet_totals.json"
WEB_DATA_FILE      = WEB_DIR / "pingdom_data.json"   # read by dashboard HTML

# ──────────────────────────────────────────────
# DEFAULT CONFIGURATION
# ──────────────────────────────────────────────
DEFAULT_CONFIG: dict = {
    "hosts": {
        "gateway":   "",
        "next_hop":  "",
        "arbitrary": "8.8.8.8"
    },
    "ping": {
        "count":            5,
        "interval_seconds": 60,
        "timeout_seconds":  5,
        "packet_size":      56
    },
    "alerting": {
        "enabled":            False,
        "rtt_threshold_ms":   200.0,
        "loss_threshold_pct": 20.0,
        "email": {
            "smtp_host":     "localhost",
            "smtp_port":     25,
            "smtp_username": "",
            "smtp_password": "",
            "from_address":  "pingdom@localhost",
            "recipients":    ["admin@example.com"]
        }
    },
    "logging": {
        "max_bytes":    10485760,
        "backup_count": 5,
        "level":        "INFO"
    },
    "storage": {
        "records_enabled":      True,
        "max_records_per_host": 10000
    },
    "web": {
        "enabled":         True,
        "export_hours":    12,
        "export_max_points": 720
    }
}

# ──────────────────────────────────────────────
# BOOTSTRAP: ensure dirs + files exist
# ──────────────────────────────────────────────
def bootstrap_paths() -> bool:
    """
    Ensure config, log, and web directories and required files exist.
    Returns True if we can proceed, False if config was just scaffolded.
    """
    created_config = False

    for d in (CONFIG_DIR, LOG_DIR, WEB_DIR):
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"[FATAL] Cannot create directory {d}: {exc}", file=sys.stderr)
            sys.exit(1)

    if not CONFIG_FILE.exists():
        try:
            CONFIG_FILE.write_text(
                json.dumps(DEFAULT_CONFIG, indent=4), encoding="utf-8"
            )
            created_config = True
        except OSError as exc:
            print(f"[FATAL] Cannot write config {CONFIG_FILE}: {exc}", file=sys.stderr)
            sys.exit(1)

    for lf in (EVENT_LOG, ALERT_LOG):
        if not lf.exists():
            try:
                lf.touch()
            except OSError as exc:
                print(f"[FATAL] Cannot create log file {lf}: {exc}", file=sys.stderr)
                sys.exit(1)

    return not created_config   # False => config was just scaffolded


# ──────────────────────────────────────────────
# LOGGER SETUP
# ──────────────────────────────────────────────
def _make_rotating_handler(path: Path, max_bytes: int, backup_count: int) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z"
    ))
    return handler


def setup_loggers(cfg: dict) -> tuple[logging.Logger, logging.Logger]:
    log_cfg    = cfg.get("logging", {})
    max_bytes  = int(log_cfg.get("max_bytes",    DEFAULT_CONFIG["logging"]["max_bytes"]))
    backup_cnt = int(log_cfg.get("backup_count", DEFAULT_CONFIG["logging"]["backup_count"]))
    level_name = log_cfg.get("level", "INFO").upper()
    level      = getattr(logging, level_name, logging.INFO)

    event_logger = logging.getLogger("pingdom.events")
    event_logger.setLevel(level)
    if not event_logger.handlers:
        event_logger.addHandler(_make_rotating_handler(EVENT_LOG, max_bytes, backup_cnt))
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter(
            "%(asctime)s  %(levelname)-8s  %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z"
        ))
        event_logger.addHandler(console)
    event_logger.propagate = False

    alert_logger = logging.getLogger("pingdom.alerts")
    alert_logger.setLevel(logging.WARNING)
    if not alert_logger.handlers:
        alert_logger.addHandler(_make_rotating_handler(ALERT_LOG, max_bytes, backup_cnt))
    alert_logger.propagate = False

    return event_logger, alert_logger


# ──────────────────────────────────────────────
# CONFIG LOADER
# ──────────────────────────────────────────────
def load_config() -> dict:
    try:
        raw = CONFIG_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        print(f"[FATAL] Config file is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
    except OSError as exc:
        print(f"[FATAL] Cannot read config {CONFIG_FILE}: {exc}", file=sys.stderr)
        sys.exit(1)


def merge_config(user: dict, defaults: dict) -> dict:
    """Deep-merge user config over defaults."""
    result = defaults.copy()
    for key, val in user.items():
        if isinstance(val, dict) and isinstance(result.get(key), dict):
            result[key] = merge_config(val, result[key])
        else:
            result[key] = val
    return result


# ──────────────────────────────────────────────
# HOST AUTO-DETECTION
# ──────────────────────────────────────────────
def _run(cmd: list[str], timeout: int = 5) -> str:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def detect_gateway(logger: logging.Logger) -> str:
    """Detect the default gateway IP."""
    out = _run(["ip", "route", "show", "default"])
    for line in out.splitlines():
        parts = line.split()
        if "via" in parts:
            idx = parts.index("via")
            candidate = parts[idx + 1]
            try:
                ipaddress.ip_address(candidate)
                logger.info(f"Auto-detected gateway: {candidate} (ip route)")
                return candidate
            except ValueError:
                pass

    out = _run(["netstat", "-rn"])
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] in ("default", "0.0.0.0/0"):
            for part in parts[1:]:
                try:
                    ipaddress.ip_address(part)
                    logger.info(f"Auto-detected gateway: {part} (netstat)")
                    return part
                except ValueError:
                    continue

    logger.warning("Could not auto-detect gateway.")
    return ""


def detect_next_hop(gateway: str, logger: logging.Logger) -> str:
    """Use traceroute to find the first public hop beyond the gateway."""
    if not gateway:
        return "1.1.1.1"

    try:
        out = _run(["traceroute", "-n", "-m", "5", "-q", "1", "8.8.8.8"], timeout=15)
        hops: list[str] = []
        for line in out.splitlines():
            parts = line.split()
            if parts and parts[0].isdigit():
                for part in parts[1:]:
                    try:
                        ip = ipaddress.ip_address(part)
                        if not ip.is_private and str(ip) != gateway:
                            logger.info(f"Auto-detected next hop: {ip} (traceroute)")
                            return str(ip)
                        elif str(ip) != gateway:
                            hops.append(str(ip))
                    except ValueError:
                        continue
        if hops:
            logger.info(f"Auto-detected next hop (best effort): {hops[0]}")
            return hops[0]
    except Exception:
        pass

    fallback = "1.1.1.1"
    logger.warning(f"Could not detect next hop; using fallback {fallback}")
    return fallback


def resolve_hosts(cfg: dict, logger: logging.Logger) -> dict[str, str]:
    """Return role -> IP mapping, auto-detecting blank entries."""
    hosts     = cfg.get("hosts", {})
    gateway   = hosts.get("gateway",   "").strip()
    next_hop  = hosts.get("next_hop",  "").strip()
    arbitrary = hosts.get("arbitrary", "8.8.8.8").strip()

    if not gateway:
        gateway = detect_gateway(logger)
    if not next_hop:
        next_hop = detect_next_hop(gateway, logger)
    if not arbitrary:
        arbitrary = "8.8.8.8"

    result: dict[str, str] = {}
    for role, host in [("gateway", gateway), ("next_hop", next_hop), ("arbitrary", arbitrary)]:
        if not host:
            logger.warning(f"No host for role '{role}'; will skip.")
            continue
        result[role] = host

    return result


# ──────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────
def _safe(host: str) -> str:
    """Sanitise an IP/hostname string for use in filenames."""
    return host.replace(".", "_").replace(":", "_")


def _fmt(val: float | None, decimals: int = 3) -> str:
    """Format a float or return 'N/A'."""
    return f"{val:.{decimals}f}" if val is not None else "N/A"


def _ensure_log(path: Path) -> None:
    if not path.exists():
        try:
            path.touch()
        except OSError as exc:
            print(f"[WARN] Could not create log {path}: {exc}", file=sys.stderr)


# ──────────────────────────────────────────────
# PER-HOST LOGGERS
# ──────────────────────────────────────────────
def get_rtt_logger(role: str, host: str, cfg: dict) -> logging.Logger:
    """Return a rotating logger writing to rtt_<role>_<host>.log."""
    log_cfg    = cfg.get("logging", {})
    max_bytes  = int(log_cfg.get("max_bytes",    DEFAULT_CONFIG["logging"]["max_bytes"]))
    backup_cnt = int(log_cfg.get("backup_count", DEFAULT_CONFIG["logging"]["backup_count"]))

    log_path = LOG_DIR / f"rtt_{role}_{_safe(host)}.log"
    _ensure_log(log_path)

    name   = f"pingdom.rtt.{role}"
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        logger.addHandler(_make_rotating_handler(log_path, max_bytes, backup_cnt))
    logger.propagate = False
    return logger


def get_packet_logger(role: str, host: str, cfg: dict) -> logging.Logger:
    """Return a rotating logger writing to packets_<role>_<host>.log."""
    log_cfg    = cfg.get("logging", {})
    max_bytes  = int(log_cfg.get("max_bytes",    DEFAULT_CONFIG["logging"]["max_bytes"]))
    backup_cnt = int(log_cfg.get("backup_count", DEFAULT_CONFIG["logging"]["backup_count"]))

    log_path = LOG_DIR / f"packets_{role}_{_safe(host)}.log"
    _ensure_log(log_path)

    name   = f"pingdom.packets.{role}"
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        logger.addHandler(_make_rotating_handler(log_path, max_bytes, backup_cnt))
    logger.propagate = False
    return logger


# ──────────────────────────────────────────────
# PING
# ──────────────────────────────────────────────
def ping_host(host: str, count: int, timeout: int, packet_size: int,
              event_log: logging.Logger) -> dict | None:
    """
    Run the system ping binary and return a parsed statistics dict.
    Returns None on hard failure (binary missing, OS error, timeout).

    Returned dict keys:
        host       str         - target host
        sent       int         - packets transmitted
        received   int         - packets received
        lost       int         - packets lost (sent - received)
        loss_pct   float       - packet loss percentage
        min        float|None  - minimum RTT in ms
        avg        float|None  - average RTT in ms
        max        float|None  - maximum RTT in ms
        stddev     float|None  - RTT standard deviation in ms
        raw_rtts   list[float] - per-packet RTTs (may be empty)
    """
    platform = sys.platform

    if platform.startswith("win"):
        cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000),
               "-l", str(packet_size), host]
    elif platform == "darwin":
        cmd = ["ping", "-c", str(count), "-W", str(timeout * 1000),
               "-s", str(packet_size), host]
    else:
        cmd = ["ping", "-c", str(count), "-W", str(timeout),
               "-s", str(packet_size), host]

    event_log.debug(f"Running: {' '.join(cmd)}")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout * count + 10
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        event_log.error(f"ping timed out for host {host}")
        return None
    except FileNotFoundError:
        event_log.error("'ping' command not found on this system.")
        return None
    except OSError as exc:
        event_log.error(f"ping OS error for {host}: {exc}")
        return None

    return _parse_ping_output(output, host, count, event_log)


def _parse_ping_output(output: str, host: str, count: int,
                       event_log: logging.Logger) -> dict:
    """Parse cross-platform ping output into a statistics dict."""

    result: dict = {
        "host":     host,
        "sent":     count,
        "received": 0,
        "lost":     count,
        "loss_pct": 100.0,
        "min":      None,
        "avg":      None,
        "max":      None,
        "stddev":   None,
        "raw_rtts": []
    }

    # ── Packet counts ──────────────────────────────────────────────────────
    loss_patterns = [
        r"(\d+)\s+packets?\s+transmitted,\s*(\d+)[\s\w]*\s+received",  # Linux / macOS
        r"Packets:\s*Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+)",        # Windows
    ]
    for pat in loss_patterns:
        m = re.search(pat, output, re.IGNORECASE)
        if m:
            sent = int(m.group(1))
            recv = int(m.group(2))
            result["sent"]     = sent
            result["received"] = recv
            result["lost"]     = max(0, sent - recv)
            result["loss_pct"] = round(result["lost"] / sent * 100, 1) if sent else 100.0
            break

    # ── RTT summary line ───────────────────────────────────────────────────
    rtt_patterns = [
        r"(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*"
        r"([\d.]+)/([\d.]+)/([\d.]+)/([\d.]+)",
        r"Minimum\s*=\s*([\d]+)ms,\s*Maximum\s*=\s*([\d]+)ms,\s*Average\s*=\s*([\d]+)ms",
    ]
    for pat in rtt_patterns:
        m = re.search(pat, output, re.IGNORECASE)
        if m:
            groups = [float(g) for g in m.groups()]
            if len(groups) == 4:
                result["min"], result["avg"], result["max"], result["stddev"] = groups
            else:
                result["min"], result["max"], result["avg"] = groups
            break

    # ── Per-packet RTTs for stddev fallback ───────────────────────────────
    rtt_line_pat = re.compile(r"time[=<]([\d.]+)\s*ms", re.IGNORECASE)
    rtts = [float(m.group(1)) for m in rtt_line_pat.finditer(output)]
    if rtts:
        result["raw_rtts"] = rtts
        if result["stddev"] is None and len(rtts) > 1:
            result["stddev"] = round(statistics.stdev(rtts), 3)
        if result["min"] is None:
            result["min"] = round(min(rtts), 3)
        if result["max"] is None:
            result["max"] = round(max(rtts), 3)
        if result["avg"] is None:
            result["avg"] = round(statistics.mean(rtts), 3)

    if result["received"] == 0:
        event_log.warning(f"No replies from {host} — host may be unreachable.")

    return result


# ──────────────────────────────────────────────
# CUMULATIVE PACKET TOTALS  (persistent JSON)
# ──────────────────────────────────────────────
def load_packet_totals() -> dict:
    """
    Load cumulative packet totals from disk.

    Structure:
        {
            "<role>": {
                "host":     "<ip>",
                "sent":     int,
                "received": int,
                "lost":     int,
                "cycles":   int
            }
        }
    """
    if not PACKET_TOTALS_FILE.exists():
        return {}
    try:
        raw = PACKET_TOTALS_FILE.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_packet_totals(totals: dict, event_log: logging.Logger) -> None:
    try:
        PACKET_TOTALS_FILE.write_text(json.dumps(totals, indent=2), encoding="utf-8")
    except OSError as exc:
        event_log.error(f"Failed to write packet totals: {exc}")


def update_packet_totals(totals: dict, role: str, host: str, stats: dict) -> None:
    """Accumulate per-cycle packet counts into the running totals dict."""
    if role not in totals:
        totals[role] = {"host": host, "sent": 0, "received": 0, "lost": 0, "cycles": 0}
    totals[role]["host"]     = host
    totals[role]["sent"]     += stats["sent"]
    totals[role]["received"] += stats["received"]
    totals[role]["lost"]     += stats["lost"]
    totals[role]["cycles"]   += 1


# ──────────────────────────────────────────────
# RTT RECORD STORAGE  (persistent JSON)
# ──────────────────────────────────────────────
def load_records() -> dict:
    if not RECORDS_FILE.exists():
        return {}
    try:
        raw = RECORDS_FILE.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_records(records: dict, cfg: dict, event_log: logging.Logger) -> None:
    max_per_host = int(
        cfg.get("storage", {}).get(
            "max_records_per_host",
            DEFAULT_CONFIG["storage"]["max_records_per_host"]
        )
    )
    for role in records:
        if len(records[role]) > max_per_host:
            records[role] = records[role][-max_per_host:]
    try:
        RECORDS_FILE.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except OSError as exc:
        event_log.error(f"Failed to write records: {exc}")


def append_record(records: dict, role: str, host: str, stats: dict) -> None:
    """Append one ping-cycle result to the records store."""
    if role not in records:
        records[role] = []
    records[role].append({
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "host":          host,
        "sent":          stats["sent"],
        "received":      stats["received"],
        "lost":          stats["lost"],
        "loss_pct":      stats["loss_pct"],
        "rtt_min_ms":    stats.get("min"),
        "rtt_avg_ms":    stats.get("avg"),
        "rtt_max_ms":    stats.get("max"),
        "rtt_stddev_ms": stats.get("stddev"),
    })


# ──────────────────────────────────────────────
# WEB DATA EXPORT
# ──────────────────────────────────────────────
def export_web_data(records: dict, totals: dict, cfg: dict,
                    event_log: logging.Logger) -> None:
    """
    Write a JSON snapshot consumed by the pingdom dashboard (pingdom_data.json).

    The file contains:
      - generated_at  : ISO-8601 UTC timestamp of this export
      - version       : pingdom version string
      - window_hours  : how many hours of history are included
      - totals        : cumulative packet totals per role
      - hosts         : per-role time-series data for the export window
    """
    web_cfg      = cfg.get("web", {})
    if not web_cfg.get("enabled", DEFAULT_CONFIG["web"]["enabled"]):
        return

    export_hours  = int(web_cfg.get("export_hours",     DEFAULT_CONFIG["web"]["export_hours"]))
    max_points    = int(web_cfg.get("export_max_points", DEFAULT_CONFIG["web"]["export_max_points"]))

    now      = datetime.now(timezone.utc)
    cutoff   = now.timestamp() - export_hours * 3600

    payload: dict = {
        "generated_at": now.isoformat(),
        "version":      VERSION,
        "window_hours": export_hours,
        "totals":       totals,
        "hosts":        {}
    }

    for role, entries in records.items():
        # Filter to the export window and downsample if needed
        windowed = [
            e for e in entries
            if _parse_ts(e.get("timestamp", "")) >= cutoff
        ]
        # Thin evenly to max_points
        if len(windowed) > max_points:
            step     = len(windowed) / max_points
            windowed = [windowed[int(i * step)] for i in range(max_points)]

        payload["hosts"][role] = windowed

    try:
        WEB_DATA_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        event_log.debug(f"Web data exported to {WEB_DATA_FILE}")
    except OSError as exc:
        event_log.error(f"Failed to write web data: {exc}")


def _parse_ts(ts: str) -> float:
    """Convert ISO-8601 timestamp string to UNIX epoch float; returns 0 on failure."""
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (ValueError, TypeError):
        return 0.0


# ──────────────────────────────────────────────
# LOG WRITERS
# ──────────────────────────────────────────────
def write_rtt_log(role: str, host: str, stats: dict, cfg: dict) -> None:
    """Write one timestamped RTT line to rtt_<role>_<host>.log."""
    logger = get_rtt_logger(role, host, cfg)
    logger.info(
        f"host={host}  "
        f"min={_fmt(stats.get('min'))}ms  "
        f"avg={_fmt(stats.get('avg'))}ms  "
        f"max={_fmt(stats.get('max'))}ms  "
        f"stddev={_fmt(stats.get('stddev'))}ms"
    )


def write_packet_log(role: str, host: str, stats: dict,
                     totals: dict, cfg: dict) -> None:
    """
    Write one timestamped packet-accounting line to packets_<role>_<host>.log.

    Format: cycle counts || cumulative totals
    """
    logger = get_packet_logger(role, host, cfg)

    t      = totals.get(role, {})
    t_sent = t.get("sent",     0)
    t_recv = t.get("received", 0)
    t_lost = t.get("lost",     0)
    t_cyc  = t.get("cycles",   0)
    t_loss = round(t_lost / t_sent * 100, 1) if t_sent else 0.0

    logger.info(
        f"host={host}  "
        f"cycle_sent={stats['sent']}  "
        f"cycle_recv={stats['received']}  "
        f"cycle_lost={stats['lost']}  "
        f"cycle_loss={stats['loss_pct']:.1f}%  "
        f"||  "
        f"total_sent={t_sent}  "
        f"total_recv={t_recv}  "
        f"total_lost={t_lost}  "
        f"total_loss={t_loss:.1f}%  "
        f"total_cycles={t_cyc}"
    )


# ──────────────────────────────────────────────
# ALERTING
# ──────────────────────────────────────────────
def check_thresholds(role: str, host: str, stats: dict,
                     cfg: dict, alert_log: logging.Logger) -> None:
    alert_cfg = cfg.get("alerting", {})
    if not alert_cfg.get("enabled", False):
        return

    rtt_thresh  = float(alert_cfg.get("rtt_threshold_ms",   DEFAULT_CONFIG["alerting"]["rtt_threshold_ms"]))
    loss_thresh = float(alert_cfg.get("loss_threshold_pct", DEFAULT_CONFIG["alerting"]["loss_threshold_pct"]))

    messages: list[str] = []
    avg  = stats.get("avg")
    loss = stats.get("loss_pct", 0.0)

    if avg is not None and avg > rtt_thresh:
        messages.append(f"RTT avg {avg:.1f} ms exceeds threshold {rtt_thresh:.1f} ms")

    if loss > loss_thresh:
        messages.append(
            f"Packet loss {loss:.1f}% "
            f"({stats['lost']}/{stats['sent']} packets lost) "
            f"exceeds threshold {loss_thresh:.1f}%"
        )

    for msg in messages:
        alert_log.warning(f"ALERT [{role}] {host}: {msg}")
        _send_email_alert(role, host, msg, stats, cfg, alert_log)


def _send_email_alert(role: str, host: str, message: str, stats: dict,
                      cfg: dict, alert_log: logging.Logger) -> None:
    import smtplib
    from email.mime.text import MIMEText

    email_cfg  = cfg.get("alerting", {}).get("email", {})
    smtp_host  = email_cfg.get("smtp_host", "localhost")
    smtp_port  = int(email_cfg.get("smtp_port", 25))
    username   = email_cfg.get("smtp_username", "").strip()
    password   = email_cfg.get("smtp_password", "")
    from_addr  = email_cfg.get("from_address", "pingdom@localhost")
    recipients = email_cfg.get("recipients", [])

    if not recipients:
        alert_log.warning("Email alerting enabled but no recipients configured.")
        return

    subject = f"[pingdom] Alert: {role} ({host})"
    body = (
        f"Pingdom Alert\n"
        f"-------------\n"
        f"Role              : {role}\n"
        f"Host              : {host}\n"
        f"Issue             : {message}\n"
        f"Packets sent      : {stats['sent']}\n"
        f"Packets received  : {stats['received']}\n"
        f"Packets lost      : {stats['lost']}  ({stats['loss_pct']:.1f}%)\n"
        f"RTT min/avg/max/stddev (ms): "
        f"{_fmt(stats.get('min'))}/{_fmt(stats.get('avg'))}/"
        f"{_fmt(stats.get('max'))}/{_fmt(stats.get('stddev'))}\n"
        f"Timestamp         : {datetime.now(timezone.utc).isoformat()}\n"
    )

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = ", ".join(recipients)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            server.ehlo_or_helo_if_needed()
            try:
                server.starttls()
            except smtplib.SMTPException:
                pass
            if username:
                server.login(username, password)
            server.sendmail(from_addr, recipients, msg.as_string())
        alert_log.info(f"Alert email sent to {recipients}")
    except Exception as exc:
        alert_log.error(f"Failed to send alert email: {exc}")


# ──────────────────────────────────────────────
# STATS SUMMARY  (--stats flag)
# ──────────────────────────────────────────────
def print_stats_summary(hosts: dict[str, str]) -> None:
    """Print a formatted packet-accounting summary from the persistent totals file."""
    totals  = load_packet_totals()
    records = load_records()

    print(f"\n{'─' * 72}")
    print(f"  pingdom v{VERSION}  —  Cumulative Packet & RTT Summary")
    print(f"  Totals file : {PACKET_TOTALS_FILE}")
    print(f"{'─' * 72}")

    for role, host in hosts.items():
        t      = totals.get(role, {})
        t_sent = t.get("sent",     0)
        t_recv = t.get("received", 0)
        t_lost = t.get("lost",     0)
        t_cyc  = t.get("cycles",   0)
        t_loss = round(t_lost / t_sent * 100, 1) if t_sent else 0.0

        recs = records.get(role, [])
        recent_avg_rtts = [
            r["rtt_avg_ms"] for r in recs[-20:]
            if r.get("rtt_avg_ms") is not None
        ]
        avg_rtt_str = (
            f"{statistics.mean(recent_avg_rtts):.2f} ms (last {len(recent_avg_rtts)} cycles)"
            if recent_avg_rtts else "N/A"
        )

        print(f"\n  [{role}]  {host}")
        print(f"    Packets sent     : {t_sent:>12,}")
        print(f"    Packets received : {t_recv:>12,}")
        print(f"    Packets lost     : {t_lost:>12,}  ({t_loss:.1f}%)")
        print(f"    Recent avg RTT   : {avg_rtt_str}")
        print(f"    Total cycles     : {t_cyc:>12,}")
        print(f"    Total records    : {len(recs):>12,}")

    print(f"\n{'─' * 72}\n")


# ──────────────────────────────────────────────
# MAIN MONITOR LOOP
# ──────────────────────────────────────────────
def run_once(hosts: dict[str, str], cfg: dict,
             event_log: logging.Logger, alert_log: logging.Logger) -> None:
    """Execute one full round of pings across all configured hosts."""
    ping_cfg = cfg.get("ping", {})
    count    = int(ping_cfg.get("count",           DEFAULT_CONFIG["ping"]["count"]))
    timeout  = int(ping_cfg.get("timeout_seconds", DEFAULT_CONFIG["ping"]["timeout_seconds"]))
    pkt_size = int(ping_cfg.get("packet_size",     DEFAULT_CONFIG["ping"]["packet_size"]))
    store_on = cfg.get("storage", {}).get(
        "records_enabled", DEFAULT_CONFIG["storage"]["records_enabled"]
    )

    records = load_records() if store_on else {}
    totals  = load_packet_totals()

    for role, host in hosts.items():
        event_log.info(
            f"Pinging [{role}] {host}  count={count}  size={pkt_size}B  timeout={timeout}s"
        )
        stats = ping_host(host, count, timeout, pkt_size, event_log)

        if stats is None:
            event_log.error(f"[{role}] {host}: ping failed completely; skipping cycle.")
            continue

        event_log.info(
            f"[{role}] {host}  "
            f"sent={stats['sent']}  recv={stats['received']}  "
            f"lost={stats['lost']}  loss={stats['loss_pct']:.1f}%  "
            f"rtt min/avg/max/stddev (ms)="
            f"{_fmt(stats.get('min'))}/{_fmt(stats.get('avg'))}/"
            f"{_fmt(stats.get('max'))}/{_fmt(stats.get('stddev'))}"
        )

        update_packet_totals(totals, role, host, stats)
        write_rtt_log(role, host, stats, cfg)
        write_packet_log(role, host, stats, totals, cfg)
        check_thresholds(role, host, stats, cfg, alert_log)

        if store_on:
            append_record(records, role, host, stats)

    save_packet_totals(totals, event_log)
    if store_on:
        save_records(records, cfg, event_log)

    export_web_data(records, totals, cfg, event_log)


def run_loop(hosts: dict[str, str], cfg: dict,
             event_log: logging.Logger, alert_log: logging.Logger) -> None:
    interval = int(cfg.get("ping", {}).get(
        "interval_seconds", DEFAULT_CONFIG["ping"]["interval_seconds"]
    ))
    event_log.info(
        f"Starting monitor loop  interval={interval}s  "
        f"hosts={list(hosts.values())}"
    )
    while True:
        try:
            run_once(hosts, cfg, event_log, alert_log)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            event_log.error(f"Unhandled error in run_once: {exc}")
            event_log.debug(traceback.format_exc())

        event_log.debug(f"Sleeping {interval}s ...")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            raise


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=f"pingdom v{VERSION} — Network Quality Monitor",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python pingdom.py                         # continuous loop\n"
            "  python pingdom.py --once                  # single cycle then exit\n"
            "  python pingdom.py --stats                 # print packet summary\n"
            "  python pingdom.py --gateway 192.168.1.1   # override gateway\n"
        )
    )
    parser.add_argument("--once",      action="store_true",
                        help="Run a single ping cycle, then exit.")
    parser.add_argument("--stats",     action="store_true",
                        help="Print cumulative packet & RTT summary, then exit.")
    parser.add_argument("--gateway",   metavar="IP", help="Override gateway host.")
    parser.add_argument("--next-hop",  metavar="IP", help="Override next-hop host.")
    parser.add_argument("--arbitrary", metavar="IP", help="Override arbitrary host.")
    parser.add_argument("--version",   action="version", version=f"%(prog)s {VERSION}")
    return parser.parse_args()


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
def main() -> None:
    args = parse_args()

    can_proceed = bootstrap_paths()
    if not can_proceed:
        print(
            "\n╔══════════════════════════════════════════════════════════════╗\n"
            "║              pingdom — First-Run Configuration               ║\n"
            "╠══════════════════════════════════════════════════════════════╣\n"
            "║  Required configuration file was not found.                  ║\n"
            "║  A default configuration has been created for you at:        ║\n"
           f"║    {str(CONFIG_FILE):<60}║\n"
            "║                                                              ║\n"
            "║  Please review and edit the configuration file, then re-run. ║\n"
            "║  Leave host values blank to enable auto-detection.           ║\n"
            "╚══════════════════════════════════════════════════════════════╝\n",
            file=sys.stderr
        )
        sys.exit(0)

    user_cfg = load_config()
    if not user_cfg:
        print(
            f"\n[ERROR] Configuration file is empty: {CONFIG_FILE}\n"
            f"  Populate it with valid JSON and re-run.\n"
            f"  A default template is available at: {CONFIG_FILE}\n",
            file=sys.stderr
        )
        sys.exit(1)

    cfg = merge_config(user_cfg, DEFAULT_CONFIG)

    event_log, alert_log = setup_loggers(cfg)
    event_log.info(f"pingdom v{VERSION} starting.")
    event_log.info(f"Config : {CONFIG_FILE}")
    event_log.info(f"Logs   : {LOG_DIR}")
    event_log.info(f"Web    : {WEB_DIR}")

    if args.gateway:
        cfg.setdefault("hosts", {})["gateway"]   = args.gateway
    if args.next_hop:
        cfg.setdefault("hosts", {})["next_hop"]  = args.next_hop
    if args.arbitrary:
        cfg.setdefault("hosts", {})["arbitrary"] = args.arbitrary

    hosts = resolve_hosts(cfg, event_log)
    if not hosts:
        event_log.error("No hosts resolved. Cannot continue.")
        sys.exit(1)

    event_log.info(f"Resolved hosts: {hosts}")

    if args.stats:
        print_stats_summary(hosts)
        sys.exit(0)

    try:
        if args.once:
            run_once(hosts, cfg, event_log, alert_log)
        else:
            run_loop(hosts, cfg, event_log, alert_log)
    except KeyboardInterrupt:
        event_log.info("Interrupted by user. Exiting.")
    except Exception as exc:
        event_log.critical(f"Fatal error: {exc}")
        event_log.debug(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()