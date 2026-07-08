# PC Performance Monitor

A lightweight Windows desktop application for real-time system performance monitoring, process analysis, and slowdown diagnostics.

## Features

- **Dashboard** — Live CPU, RAM, Disk, GPU, and Network metrics with color-coded progress bars and 60-second history graphs
- **Processes** — Sortable, searchable process table showing PID, CPU %, RAM, Disk I/O, network connections, priority, start time, and status. High-resource processes are highlighted in red
- **Diagnostics** — Automatic analysis of system health with categorized alerts (Critical / Warning / Info) and actionable suggestions for fixing slowdowns
- **Dark/Light mode** toggle
- **No admin privileges** required for normal operation
- **Read-only** — never modifies, deletes, or accesses personal files

## Requirements

- **OS:** Windows 10 or Windows 11
- **Python:** 3.10 or later (3.11+ recommended)
- **GPU monitoring** requires an NVIDIA GPU with drivers installed (gracefully disabled otherwise)

## Quick Start (Run from source)

```bash
# 1. Clone or download this folder

# 2. Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

## Build Standalone .exe

### Option A — Use the build script

```bash
build.bat
```

The executable will be at `dist\PC-Monitor.exe`.

### Option B — Manual build

```bash
pip install -r requirements.txt

# Find your customtkinter install path
python -c "import customtkinter; print(customtkinter.__path__[0])"

# Build (replace the path below with the output from above)
pyinstaller --onefile --windowed --name "PC-Monitor" ^
    --add-data "C:\path\to\customtkinter;customtkinter" ^
    main.py
```

### Adding a custom icon

Place a `.ico` file in the project folder, then add `--icon your_icon.ico` to the PyInstaller command.

## Libraries Used

| Library | Purpose | License |
|---------|---------|---------|
| [psutil](https://github.com/giampaolo/psutil) | System & process monitoring | BSD-3 |
| [customtkinter](https://github.com/TomSchimansky/CustomTkinter) | Modern GUI framework | MIT |
| [GPUtil](https://github.com/anderskm/gputil) | NVIDIA GPU monitoring | MIT |
| [PyInstaller](https://github.com/pyinstaller/pyinstaller) | .exe packaging | GPL-2 (output is not GPL) |

All are free, open-source, actively maintained, and have no known critical vulnerabilities.

## Architecture

The entire application is a single Python file (`main.py`) with three main components:

1. **SystemDataCollector** — Background threads collect CPU, RAM, disk, GPU, network, and process data on separate intervals to minimize overhead
2. **UI layer** — CustomTkinter widgets (MetricCard, SpeedCard, MiniGraph) render live data with color-coded thresholds
3. **Diagnostics engine** — Analyzes collected data every 8 seconds and generates prioritized alerts

### Refresh intervals

| Data | Interval | Thread |
|------|----------|--------|
| System stats | 2s | Background |
| Process list | 3s | Background |
| Diagnostics | 8s | Background |
| UI update | 2s | Main (after) |

## Security & Privacy

- Runs without Administrator privileges
- All data is read-only system metrics — no file access, no registry writes, no network requests
- No telemetry, analytics, or data collection of any kind
- All exceptions are caught to prevent crashes
- GPU monitoring is optional and fails gracefully

## Troubleshooting

**"No compatible GPU detected"** — This is normal for AMD/Intel GPUs. GPUtil only supports NVIDIA. CPU/RAM/Disk/Network monitoring works fully regardless.

**Some processes show "N/A" for Disk I/O** — Windows restricts I/O counters for system-protected processes. This is expected behavior without admin rights.

**PyInstaller build fails on --add-data** — The customtkinter path varies by Python installation. Run the path-detection command shown in the build instructions and use the exact path output.

## Compatibility

Tested on Windows 10 22H2 and Windows 11 23H2 with Python 3.11 and 3.12. Uses only cross-platform APIs from psutil, though the UI and build tooling target Windows specifically.

