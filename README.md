# pingdom

**Version 1.2.7**

A lightweight, zero-dependency network quality monitor written in Python 3.10+.  
It pings your **local gateway**, the **next-hop router**, and an **arbitrary host** (default `8.8.8.8`) on a configurable interval, writing per-host RTT statistics and packet accounting to individual rotating log files.  An auto-updating web dashboard reads the exported JSON data to display 12 hours of network quality history.

---

## Change Log

### 1.2.7 — 2026-03-22
- **New**: **Stddev** added as a selectable metric in the dashboard metric selector.
  - Button label: `Stddev`
  - Data field: `rtt_stddev_ms`
  - Chart title: *Round-Trip Time — Std Deviation*
  - Chart subtitle: `stddev ms over time`
  - Y-axis unit: `ms` (auto-scaled; no floor or ceiling, since stddev values on healthy networks are typically small and benefit from full auto-ranging)
- **Changed**: `metricField()` map extended with `stddev: 'rtt_stddev_ms'`.
- **Changed**: `METRIC_LABELS` map extended with the `stddev` entry.
- **Changed**: `unitFn` in `CHART_DEFS` already correctly returns `'ms'` for all non-loss metrics; no change required.

### 1.2.6 — 2026-03-22
- **Changed**: dedicated Packet Loss graph removed from the dashboard. Loss % is now accessed by selecting the **Loss %** option in the metric selector on the single RTT chart, which spans the full width of the page.
- **Changed**: `.charts-grid` CSS updated from `repeat(auto-fit, minmax(420px, 1fr))` to `1fr` so the single chart always fills the full available width.
- **Changed**: `CHART_DEFS` reduced to a single entry (`chartRtt`). The `chartLoss` entry and its associated canvas, legend, and scaffold HTML are removed.
- **Changed**: Y-axis auto-scaling for `%` unit — the hard `max: 100` cap is removed. The axis now starts at `0` and auto-scales to fit the actual data, giving better resolution when all loss values are low (e.g. 0–5%). The manual Loss % chart, which always graphed 0–100, no longer exists.

### 1.2.5 — 2026-03-22
- **Fix**: when the RTT chart metric selector is set to **Loss %**, the Y-axis tick labels now correctly show `%` instead of `ms`.
- **Fix**: the Y-axis is now capped at `min: 0, max: 100` when the unit is `%`, preventing the scale from auto-ranging beyond valid percentage bounds.
- **Changed**: `unit` in `CHART_DEFS` replaced with `unitFn` — a closure that evaluates `metric` at render time. The RTT chart entry returns `'%'` when metric is `loss`, `'ms'` otherwise. The Loss chart entry always returns `'%'`. This ensures both the Y-axis tick labels and the tooltip suffix always match the data being graphed.

### 1.2.4 — 2026-03-22
- **New**: the RTT chart title and subtitle now update dynamically when the metric selector is changed:
  - **Avg RTT** → *Round-Trip Time — Average* / `avg ms over time`
  - **Min RTT** → *Round-Trip Time — Minimum* / `min ms over time`
  - **Max RTT** → *Round-Trip Time — Maximum* / `max ms over time`
  - **Loss %** → *Packet Loss* / `% over time` (the Loss chart title is unchanged)
- **Changed**: `METRIC_LABELS` map added to the dashboard script — maps each metric key (`avg`, `min`, `max`, `loss`) to a `{ title, sub }` object consumed by `renderCharts()`.
- **Changed**: chart panel title and subtitle elements now carry stable IDs (`title_chartRtt`, `sub_chartRtt`) so `renderCharts()` can update them in-place without rebuilding the scaffold HTML.

### 1.2.3 — 2026-03-22
- **New**: four chart point-radius constants added to the dashboard configuration block, giving full control over dot rendering without editing chart code:
  - `POINT_DENSITY_THRESHOLD` — number of data points above which the density guard activates (default `60`). Set to `Infinity` to always show dots at full size.
  - `POINT_RADIUS` — pixel radius of dots when the point count is at or below the threshold (default `2`).
  - `POINT_RADIUS_MIN` — minimum dot radius applied *above* the threshold (default `0`, preserving the original hide-when-dense behaviour). Set to `1` or higher to always show at least a hairline dot at every data point regardless of density.
  - `POINT_HOVER_RADIUS` — radius of the hover dot that appears on mouse-over regardless of all other settings (default `4`).
- **Changed**: `buildChart()` now derives `pointRadius` from `POINT_DENSITY_THRESHOLD`, `POINT_RADIUS`, and `POINT_RADIUS_MIN` instead of the previous inline literal `sortedTimes.length > 60 ? 0 : 2`.

### 1.2.2 — 2026-03-22
- **New**: dashboard auto-refresh interval is now user-selectable via a segment control: **10s / 30s / 1m / 5m** (default 1m). The previous hardcoded 30-second value is replaced by a mutable `autoRefreshMs` state variable.
- **New**: live countdown display next to the interval selector shows exactly how many seconds remain until the next auto-refresh (e.g. `47s`, `4m32s`). The countdown resets whenever the interval is changed, a manual refresh fires, or auto-refresh is toggled back on. It dims to `—` when auto-refresh is disabled.
- **Changed**: the `AUTO_REFRESH` constant has been removed; interval is now driven by the selected button's `data-ms` attribute and stored in `autoRefreshMs`.
- **Changed**: `scheduleAuto()` now also starts a per-second `countdownTimer` interval alongside the fetch `autoTimer`, and clears it correctly when auto-refresh is toggled off or the interval is changed.

### 1.2.1 — 2026-03-22
- **Fix**: dashboard no longer throws *"Canvas is already in use. Chart with ID '0' must be destroyed before the canvas can be reused"* when switching time windows, metric, or on auto-refresh.
  - Root cause: `renderCharts()` was writing new `<canvas>` elements into the DOM while Chart.js still held live references to the old ones, because the old destroy call happened inside `buildChart()` *after* the innerHTML replacement.
  - Fix 1: `destroyAllCharts()` is now called unconditionally at the top of `renderCharts()`, before any DOM work.
  - Fix 2: `Chart.getChart(canvas)` is called as a final safety net immediately before each `new Chart(...)` call to destroy any orphaned instance that survived through an error path.
  - Fix 3: `CHART_DEFS` is now a module-level constant with `fieldFn` closures so each chart always evaluates the current `metric` at render time rather than capturing a stale value.
- **Fix**: added `chartjs-adapter-date-fns` CDN script — Chart.js 4's `type: 'time'` X-axis scale requires an explicit date adapter; without it timestamps were not parsed and chart rendering silently failed in some browsers.

### 1.2.0 — 2026-03-22
- **Project renamed** from `ping_monitor` / `pingdom` to **`pingdom`** throughout.
- **All file names updated**: `pingdom.py`, `pingdom.json`, `pingdom_events.log`, `pingdom_alerts.log`, `pingdom_records.json`, `pingdom_packet_totals.json`.
- **All environment variables renamed**: `PINGDOM_CONFIG_PATH`, `PINGDOM_LOG_PATH`, `PINGDOM_WEB_PATH`.
- **New**: `web` config section — controls web data export (`enabled`, `export_hours`, `export_max_points`).
- **New**: `PINGDOM_WEB_PATH` environment variable / `_SCRIPT_WEB_PATH` script variable for the web output directory.
- **New**: `web/pingdom_data.json` exported after every ping cycle — the JSON feed consumed by the dashboard.
- **New**: `pingdom_dashboard.html` — single-file, dependency-light web dashboard displaying RTT and packet-loss charts for the last 12 hours (or configurable window), with live staleness indicator, auto-refresh, and full packet accounting table.

### 1.1.0 — 2026-03-22
- Dedicated `packets_<role>_<host>.log` per host with per-cycle and cumulative totals.
- `pingdom_packet_totals.json` — persistent cumulative packet counts, survives restarts.
- `--stats` CLI flag for terminal summary.
- Explicit `lost` field computed and propagated everywhere.
- Handler guard prevents duplicate log entries on repeated calls.

### 1.0.0 — 2026-03-22
- Initial release.
- Auto-detection of gateway and next-hop.
- Per-host rotating RTT logs.
- Centralised event log and alert log.
- JSON record storage.
- Email alerting (authenticated and unauthenticated SMTP).
- First-run bootstrap with helpful exit message.
- `--once` and continuous loop modes.
- CLI host overrides.

---

## Requirements

| Requirement | Notes |
|---|---|
| Python | 3.10 or later |
| `ping` binary | Pre-installed on Linux, macOS, and Windows |
| `ip route` or `netstat` | For gateway auto-detection (Linux / macOS) |
| `traceroute` | For next-hop auto-detection (optional; falls back to `1.1.1.1`) |
| Web server (optional) | nginx or Apache to serve the dashboard — see below |
| No third-party Python packages | Uses stdlib only |

---

## Quick Start

```bash
# Clone the repository
git clone https://github.com/n8xja/pingdom.git
cd pingdom

# Run once — auto-detects all three hosts
python pingdom.py --once

# Run continuously (default 60-second interval)
python pingdom.py

# Override hosts explicitly
python pingdom.py --gateway 192.168.1.1 --next-hop 10.0.0.1 --arbitrary 1.1.1.1

# Print a cumulative packet summary and exit
python pingdom.py --stats
```

On the **first run**, if the configuration file does not exist the script will:
1. Create the `config/`, `logs/`, and `web/` directory structure.
2. Write a default `pingdom.json` with all options documented.
3. Print the path to the new config file.
4. **Exit** — edit the config, then re-run.

---

## Configuration and Log Paths

Paths are resolved in this priority order:

| Priority | Source | Variable / Env Var |
|---|---|---|
| 1 | Environment variable | `PINGDOM_CONFIG_PATH` / `PINGDOM_LOG_PATH` / `PINGDOM_WEB_PATH` |
| 2 | Script-level variable | `_SCRIPT_CONFIG_PATH` / `_SCRIPT_LOG_PATH` / `_SCRIPT_WEB_PATH` |
| 3 | Current working directory | `./config/` / `./logs/` / `./web/` |

### Setting via environment

```bash
export PINGDOM_CONFIG_PATH=/etc/pingdom
export PINGDOM_LOG_PATH=/var/log/pingdom
export PINGDOM_WEB_PATH=/var/www/html/pingdom
python pingdom.py
```

### Files created automatically

| File | Purpose |
|---|---|
| `{CONFIG_DIR}/pingdom.json` | Main configuration file |
| `{LOG_DIR}/pingdom_events.log` | All events, info, warnings, errors |
| `{LOG_DIR}/pingdom_alerts.log` | Threshold-breach alerts only |
| `{LOG_DIR}/rtt_{role}_{host}.log` | Per-host RTT statistics (min/avg/max/stddev) |
| `{LOG_DIR}/packets_{role}_{host}.log` | Per-host packet accounting (sent/recv/lost, cycle + cumulative) |
| `{LOG_DIR}/pingdom_records.json` | Persistent per-cycle record store |
| `{LOG_DIR}/pingdom_packet_totals.json` | Persistent cumulative packet totals per role |
| `{WEB_DIR}/pingdom_data.json` | Web-readable JSON data feed (updated every cycle) |

Place `pingdom_dashboard.html` in `{WEB_DIR}` alongside `pingdom_data.json` for the dashboard to work.

---

## Configuration File — `pingdom.json`

```jsonc
{
    // ── Hosts ────────────────────────────────────────────────
    "hosts": {
        "gateway":   "",       // Leave blank for auto-detection via 'ip route'
        "next_hop":  "",       // Leave blank for auto-detection via 'traceroute'
        "arbitrary": "8.8.8.8" // Any reachable host or IP
    },

    // ── Ping behaviour ───────────────────────────────────────
    "ping": {
        "count":            5,   // Packets per ping cycle
        "interval_seconds": 60,  // Seconds between full ping cycles
        "timeout_seconds":  5,   // Per-packet wait timeout
        "packet_size":      56   // ICMP payload bytes
    },

    // ── Alerting ─────────────────────────────────────────────
    "alerting": {
        "enabled":            false,
        "rtt_threshold_ms":   200.0,
        "loss_threshold_pct": 20.0,

        "email": {
            "smtp_host":     "localhost",
            "smtp_port":     25,
            "smtp_username": "",              // Leave blank for unauthenticated SMTP
            "smtp_password": "",
            "from_address":  "pingdom@localhost",
            "recipients":    ["admin@example.com"]
        }
    },

    // ── Logging ──────────────────────────────────────────────
    "logging": {
        "max_bytes":    10485760,  // 10 MB per log file before rotation
        "backup_count": 5,
        "level":        "INFO"     // DEBUG | INFO | WARNING | ERROR | CRITICAL
    },

    // ── Storage ──────────────────────────────────────────────
    "storage": {
        "records_enabled":      true,
        "max_records_per_host": 10000
    },

    // ── Web export ───────────────────────────────────────────
    "web": {
        "enabled":           true,   // Write pingdom_data.json after each cycle
        "export_hours":      12,     // Hours of history to include in the export
        "export_max_points": 720     // Downsample to at most this many data points per host
    }
}
```

### Key Options

| Option | Default | Effect |
|---|---|---|
| `ping.count` | `5` | More packets → more accurate statistics |
| `ping.interval_seconds` | `60` | Lower = finer granularity, more system load |
| `alerting.enabled` | `false` | Must be `true` to send alert emails |
| `alerting.rtt_threshold_ms` | `200.0` | Adjust to match your SLA |
| `alerting.loss_threshold_pct` | `20.0` | Raise to reduce noise on flaky links |
| `alerting.email.smtp_username` | `""` | Empty → unauthenticated SMTP relay |
| `web.enabled` | `true` | Set `false` to skip JSON export |
| `web.export_hours` | `12` | Dashboard default history window |
| `web.export_max_points` | `720` | Cap chart resolution for large datasets |
| `storage.max_records_per_host` | `10000` | Prevents unbounded JSON file growth |

---

## Application Behaviour

### Startup

1. **Path resolution** — Config, log, and web directories are determined via env vars, script variables, or CWD fallback.
2. **Bootstrap** — Missing directories and files are created automatically. If the config file was just scaffolded, the script prints its path and exits.
3. **Config merge** — User config is deep-merged over built-in defaults so partially-specified files work correctly.
4. **Host resolution** — Hosts not specified in config are auto-detected:
   - **Gateway**: parsed from `ip route show default` (Linux) or `netstat -rn` (macOS/BSD).
   - **Next-hop**: parsed from `traceroute -n -m 5 8.8.8.8`; falls back to `1.1.1.1`.
   - **Arbitrary**: defaults to `8.8.8.8` if blank.

### Ping Cycle

For each resolved host:
1. Runs the system `ping` binary with configured `count`, `timeout`, and `packet_size`.
2. Parses output for **packets sent, received, and lost** and RTT statistics. Handles Linux, macOS, and Windows ping formats.
3. Writes a timestamped RTT line to `rtt_<role>_<host>.log`.
4. Writes a timestamped packet-accounting line to `packets_<role>_<host>.log` — both per-cycle counts and running cumulative totals.
5. Updates `pingdom_packet_totals.json`.
6. Writes a consolidated summary line to `pingdom_events.log`.
7. Checks RTT avg and packet-loss against thresholds; fires alerts if enabled.
8. Appends a full record to `pingdom_records.json`.

After all hosts are processed, `web/pingdom_data.json` is updated with a filtered, (optionally downsampled) snapshot of the last `export_hours` hours of data.

### Graceful Degradation

- If a host cannot be reached, it is skipped for that cycle and a warning is logged.
- If the `ping` binary is missing, an error is logged and that host is skipped.
- If email delivery fails, the error is logged and the monitor continues running.
- `KeyboardInterrupt` exits cleanly with a log entry.

---

## Dashboard — `pingdom_dashboard.html`

A single self-contained HTML file that reads `pingdom_data.json` from the same directory.  
No build step, no backend, no npm — just serve both files from a web server.

### External dependencies (CDN, no install required)

| Library | Version | Purpose |
|---|---|---|
| [Chart.js](https://www.chartjs.org/) | 4.4.1 | RTT and packet-loss time-series charts |
| [chartjs-adapter-date-fns](https://github.com/chartjs/chartjs-adapter-date-fns) | 3.x | Required date adapter for Chart.js `type: 'time'` X-axis scale |
| [Google Fonts](https://fonts.google.com/) | — | JetBrains Mono + Syne typefaces |

Both Chart.js scripts are loaded from `cdnjs.cloudflare.com` / `cdn.jsdelivr.net`. The dashboard will not render charts if these CDNs are unreachable. For air-gapped deployments, download both scripts and update the `<script src="...">` tags to local paths.

### Features

| Feature | Detail |
|---|---|
| **Staleness indicator** | Header shows how long ago `pingdom_data.json` was generated (read from its `generated_at` field, not the fetch time). Dot colour: green → yellow after 90 s → red after 5 min. |
| **Auto-refresh toggle** | Enable or disable automatic refresh without a page reload. |
| **Refresh interval** | Segment control to select the auto-refresh interval: **10s / 30s / 1m / 5m** (default 1m). Changing the interval restarts the countdown immediately. |
| **Refresh countdown** | Live countdown (e.g. `47s`, `4m32s`) showing time until the next auto-refresh. Dims to `—` when auto-refresh is disabled. |
| **Time window** | Filter buttons: last 1 h / 3 h / 12 h / All — re-renders all charts and the packet table instantly. |
| **Metric selector** | Switch the RTT chart between Avg RTT / Min RTT / Max RTT / Stddev / Loss % without a page reload. The chart title and subtitle update to reflect the active metric (e.g. *Round-Trip Time — Std Deviation*). |
| **Status cards** | Per-host Online / Degraded / Offline badge with windowed avg RTT, avg loss %, and last-cycle sent/lost packet counts. |
| **Lifetime totals** | Cards showing cumulative sent / received / lost / loss % / cycles per host since first run (sourced from `totals` in the JSON export). |
| **RTT chart** | Multi-line time-series for all three hosts, respecting the active time window and metric selection. |
| **Loss %** | Packet loss is graphed by selecting **Loss %** in the metric selector; the single full-width chart switches field, title, and Y-axis unit automatically. The Y-axis auto-scales from 0 to fit the data (no hard 100% ceiling). |
| **Packet table** | Most recent 20 cycles per host: timestamp, sent, recv, lost, loss %, avg / min / max / stddev RTT. |

### Chart rendering behaviour

Charts are fully destroyed and rebuilt on every render triggered by a window-change, metric-change, or data refresh. The destroy sequence is:

1. All tracked `Chart` instances in the `charts` map are destroyed and removed.
2. `Chart.getChart(canvas)` is called on each canvas element as a safety net to catch any orphaned instances.
3. A final `Chart.getChart(ctx)` guard runs immediately before each `new Chart(...)` call.

This three-layer approach prevents the *"Canvas is already in use"* error that would otherwise occur when Chart.js retains a reference to a canvas element that has been replaced in the DOM.

### Chart point radius configuration

Four constants at the top of the dashboard `<script>` block control how data-point dots are drawn. Edit them directly in the HTML file — no other changes needed.

| Constant | Default | Description |
|---|---|---|
| `POINT_DENSITY_THRESHOLD` | `60` | Point count above which the density guard activates. Set to `Infinity` to always show full-size dots. |
| `POINT_RADIUS` | `2` | Dot radius in pixels when point count is at or below the threshold. Set to `0` for a line-only chart. |
| `POINT_RADIUS_MIN` | `0` | Minimum dot radius enforced *above* the threshold. `0` = fully suppress dots on dense data (original behaviour). Set to `1` or higher to always show at least a hairline dot at every data point. |
| `POINT_HOVER_RADIUS` | `4` | Dot radius on mouse-over hover, always applied regardless of the other settings. |

**How `POINT_RADIUS_MIN` interacts with `POINT_DENSITY_THRESHOLD`**

When the point count is above `POINT_DENSITY_THRESHOLD`, `pointRadius` is set to `POINT_RADIUS_MIN` rather than zero. This means:
- `POINT_RADIUS_MIN = 0` → dots are fully hidden above the threshold (dense line only).
- `POINT_RADIUS_MIN = 1` → a 1 px hairline dot appears at every point even on busy 12h or All-window charts.
- `POINT_RADIUS_MIN = 2` → same size as the normal dot; effectively disables the density guard.

The threshold of `60` at the default 60-second ping interval corresponds to roughly 1 hour of data, so dots are visible in the 1h window and suppressed for 3h, 12h, and All by default. If you shorten `ping.interval_seconds` in `pingdom.json`, lower the threshold to match (e.g. `30` for a 30-second interval).

### Serving with nginx

```nginx
server {
    listen 80;
    server_name pingdom.example.com;

    root /var/www/html/pingdom;
    index pingdom_dashboard.html;

    # Allow JSON to be fetched by the dashboard JS
    location /pingdom_data.json {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma        "no-cache";
        add_header Expires       "0";
        try_files $uri =404;
    }

    location / {
        try_files $uri $uri/ =404;
    }
}
```

Set `PINGDOM_WEB_PATH=/var/www/html/pingdom` and copy `pingdom_dashboard.html` there.

### Serving with Apache

```apache
<VirtualHost *:80>
    ServerName pingdom.example.com
    DocumentRoot /var/www/html/pingdom

    DirectoryIndex pingdom_dashboard.html

    <Location /pingdom_data.json>
        Header set Cache-Control "no-cache, no-store, must-revalidate"
        Header set Pragma "no-cache"
        Header set Expires "0"
    </Location>

    <Directory /var/www/html/pingdom>
        Options -Indexes
        AllowOverride None
        Require all granted
    </Directory>
</VirtualHost>
```

Enable `mod_headers`: `sudo a2enmod headers && sudo systemctl restart apache2`

---

## Data Structures

### RTT Log Entry (`rtt_<role>_<host>.log`)

```
YYYY-MM-DDThh:mm:ss+0000  INFO      host=8.8.8.8  min=9.123ms  avg=10.456ms  max=11.789ms  stddev=0.901ms
```

### Packet Log Entry (`packets_<role>_<host>.log`)

Left of `||` = per-cycle; right of `||` = cumulative session totals:

```
YYYY-MM-DDThh:mm:ss+0000  INFO  host=8.8.8.8  cycle_sent=5  cycle_recv=5  cycle_lost=0  cycle_loss=0.0%  ||  total_sent=150  total_recv=148  total_lost=2  total_loss=1.3%  total_cycles=30
```

### Cumulative Packet Totals (`pingdom_packet_totals.json`)

```jsonc
{
  "gateway":   { "host": "192.168.1.1", "sent": 150, "received": 150, "lost": 0, "cycles": 30 },
  "next_hop":  { "host": "1.1.1.1",     "sent": 150, "received": 149, "lost": 1, "cycles": 30 },
  "arbitrary": { "host": "8.8.8.8",     "sent": 150, "received": 148, "lost": 2, "cycles": 30 }
}
```

### Per-Cycle Record (`pingdom_records.json`)

```jsonc
{
  "gateway": [
    {
      "timestamp":     "YYYY-MM-DDThh:mm:ss+00:00",
      "host":          "192.168.1.1",
      "sent":          5,
      "received":      5,
      "lost":          0,
      "loss_pct":      0.0,
      "rtt_min_ms":    0.812,
      "rtt_avg_ms":    1.034,
      "rtt_max_ms":    1.441,
      "rtt_stddev_ms": 0.213
    }
    // ... up to max_records_per_host entries
  ]
}
```

### Web Data Export (`pingdom_data.json`)

Written to `{WEB_DIR}` after every cycle; consumed by the dashboard:

```jsonc
{
  "generated_at": "YYYY-MM-DDThh:mm:ss+00:00",
  "version":      "1.2.7",
  "window_hours": 12,
  "totals":       { /* same structure as pingdom_packet_totals.json */ },
  "hosts": {
    "gateway":   [ /* filtered & downsampled records */ ],
    "next_hop":  [ /* ... */ ],
    "arbitrary": [ /* ... */ ]
  }
}
```

---

## Storage Strategy

- **Format**: JSON throughout — human-readable, easily inspected with `jq`, importable into spreadsheets.
- **Write strategy**: read → append → trim → write-back per cycle.
- **Record rotation**: oldest entries evicted once per-host list exceeds `max_records_per_host`.
- **Log rotation**: all `.log` files rotated by `RotatingFileHandler` at `max_bytes` with `backup_count` copies.
- **Web export**: a fresh filtered slice is written after every cycle; no appending — the file is always a clean snapshot safe for concurrent HTTP reads.

---

## Running as a Service

### systemd (Linux)

Create `/etc/systemd/system/pingdom.service`:

```ini
[Unit]
Description=Pingdom Network Quality Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=nobody
Group=nogroup
WorkingDirectory=/opt/pingdom
Environment="PINGDOM_CONFIG_PATH=/etc/pingdom"
Environment="PINGDOM_LOG_PATH=/var/log/pingdom"
Environment="PINGDOM_WEB_PATH=/var/www/html/pingdom"
ExecStart=/usr/bin/python3 /opt/pingdom/pingdom.py
Restart=on-failure
RestartSec=15s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now pingdom
sudo journalctl -u pingdom -f
```

### macOS launchd

Create `~/Library/LaunchAgents/com.n8xja.pingdom.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>         <string>com.n8xja.pingdom</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/you/pingdom/pingdom.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PINGDOM_CONFIG_PATH</key> <string>/Users/you/.config/pingdom</string>
        <key>PINGDOM_LOG_PATH</key>    <string>/Users/you/Library/Logs/pingdom</string>
        <key>PINGDOM_WEB_PATH</key>    <string>/Users/you/Sites/pingdom</string>
    </dict>
    <key>RunAtLoad</key>   <true/>
    <key>KeepAlive</key>   <true/>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.n8xja.pingdom.plist
```

### Windows Task Scheduler

```powershell
$env = @(
  "PINGDOM_CONFIG_PATH=C:\pingdom\config",
  "PINGDOM_LOG_PATH=C:\pingdom\logs",
  "PINGDOM_WEB_PATH=C:\inetpub\wwwroot\pingdom"
)
$action  = New-ScheduledTaskAction -Execute "python" -Argument "C:\pingdom\pingdom.py"
$trigger = New-ScheduledTaskTrigger -AtStartup
Register-ScheduledTask -TaskName "Pingdom" -Action $action -Trigger $trigger -RunLevel Highest
```

---

## Dashboard File Layout

```
/var/www/html/pingdom/         (or wherever PINGDOM_WEB_PATH points)
├── pingdom_dashboard.html     ← copy manually once
└── pingdom_data.json          ← written automatically by pingdom.py each cycle
```

The dashboard fetches `pingdom_data.json` relative to its own URL, so both files must be in the same web-accessible directory.