# CIPO - Confirming Interplanetary Object Observatory

**CIPO** is a Python package for retrieving, parsing, and analyzing unconfirmed object data from the **Minor Planet Center's NEO Confirmation Page (NEOCP)** and **Possible Comet Confirmation Page (PCCP)**. It provides tools to calculate visibility windows, filter by altitude and duration criteria, and schedule observations for a given observatory.

## Features

- **Fetch MPC data** via Selenium with automatic caching to reduce network load
- **Parse ephemeris tables** robustly from MPC pages with fallback strategies for formatting variations
- **Filter objects** by minimum altitude and continuous visibility duration
- **Calculate observation windows** based on lunar phases (New Moon periods)
- **Plot visibility curves** for selected objects during dark-sky intervals
- **Support multiple object types**: NEOCP (NEOs) and PCCP (possible comets)
- **Observatory-centric**: Specify any MPC-registered observatory code (e.g., Y28 for OASI/Brazil)

## Installation

### Requirements
- Python ≥ 3.13
- Dependencies automatically installed via `pip` or `uv`

### Setup

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd cipo
   ```

2. Install in development mode:
   ```bash
   uv pip install -e .
   ```
   Or with `pip`:
   ```bash
   pip install -e .
   ```

3. (Optional) Install development dependencies:
   ```bash
   uv pip install -r requirements-dev.txt
   ```

## Quick Start

### Basic Usage: Analyze Visible Objects

```python
from cipo import analyze_ephemeris_objects

# Fetch and analyze unconfirmed objects visible from observatory Y28 (OASI, Brazil)
df = analyze_ephemeris_objects(
    obs_code='Y28',
    obj_type='NEOCP',
    altitude_min=10,      # Minimum 10° altitude
    duration_min=30,      # Minimum 30 minutes visible
    plot=True             # Display altitude curves
)

print(df[['Temp Desig', 'R.A.', 'Decl.', 'Max_Alt', 'Visible_Minutes']])
```

### Interactive Mode

```python
from cipo import process_mpc_data

# Retrieve and enter interactive mode to inspect specific objects
df = process_mpc_data(
    obs_code='Y28',
    obj_type='NEOCP',
    interactive_mode=True
)
# User can then enter a provisional designation to view details
```

### Calculate Lunar Observation Windows

```python
from cipo import calculate_observation_windows

# Find New Moon observation windows (7 days before/after) for the next year
windows = calculate_observation_windows(
    latitude=-22.5,    # Observatory latitude (degrees)
    longitude=-43.5,   # Observatory longitude (degrees)
    start_year=2026,
    num_years=1
)

for start, new_moon, end in windows:
    print(f"Window: {start} to {end} (New Moon: {new_moon})")
```

## Configuration

Edit [src/cipo/config.py](src/cipo/config.py) to customize default parameters:

```python
# User Configuration
OBS_CODE = 'Y28'                # Your observatory's MPC code
OBJ_TYPE = 'NEOCP'              # 'NEOCP' or 'PCCP'
ALTITUDE_MIN = 10               # Minimum altitude (degrees)
DURATION_MIN = 30               # Minimum duration (minutes)
SUN_ALT_LIMIT = -18             # Sun altitude for astronomical night

# Program Configuration
USE_CACHE = True                # Cache ephemeris locally
CACHE_DIR = "./cache"           # Cache directory
REQUESTS_TIMEOUT = 15           # Network timeout (seconds)
SELENIUM_IMPLICIT_WAIT = 10     # Browser implicit wait (seconds)
```

## Data Sources

- **Minor Planet Center** (https://minorplanetcenter.net/): NEOCP and PCCP confirmation pages
- **JPL Ephemeris (DE421)**: For lunar phase calculations (included in Skyfield)
- **Observatory Codes**: MPC-registered three-character codes (e.g., Y28, 500, 688)

## Module Overview

### `config.py`
Central configuration for observatory, observation criteria, and plotting parameters.

### `downloader.py`
- `fetch_mpc_data()`: Fetch ephemeris text via Selenium with caching
- `_download_mpc_table()`: Download summary table of unconfirmed objects
- `MPCDriver`: Singleton manager for ChromeDriver (headless browser)

### `parser.py`
- `parse_mpc_data()`: Extract ephemeris tables using position-based column parsing with fallback strategies

### `filter.py`
- `filter_visible_objects()`: Filter objects by altitude and duration criteria during astronomical night

### `main.py`
High-level workflows:
- `analyze_ephemeris_objects()`: Fetch, parse, filter, and plot ephemeris data
- `process_mpc_data()`: Non-plotting analysis with optional interactive mode

### `visibility.py`
- `calculate_observation_windows()`: Identify New Moon observation windows for given location and year range

### `graphics.py`
Advanced plotting utilities (optional module for extended visualization):
- `plot_visibility_from_mpc()`: Generate detailed altitude curves with Sun/Moon overlays
- Coordinate conversion utilities (RA/Dec ↔ degrees)
- Manual astronomical altitude calculations

## Workflow: From Unconfirmed to Observable

1. **Retrieve unconfirmed objects**: `fetch_mpc_data(obs_code='Y28', obj_type='NEOCP')`
   - Uses Selenium to interact with MPC form
   - Caches results for reuse
   
2. **Parse ephemeris**: `parse_mpc_data(text)`
   - Extracts Date, UT, RA, Dec, altitude, magnitude for each object
   - Handles formatting variations
   
3. **Filter by visibility**: `filter_visible_objects(ephem_dict, altitude_min=10, time_min_minutes=30)`
   - Identifies continuous visibility windows
   - Removes rows during daylight or below altitude limit
   
4. **Display & analyze**: `analyze_ephemeris_objects(..., plot=True)`
   - Returns summary DataFrame
   - Plots altitude curves for selected night interval

## Key Scientific Assumptions

- **Time scale**: UTC throughout (MPC standard)
- **Coordinate frame**: J2000 equatorial (RA/Dec in ephemeris tables)
- **Astronomical night**: Sun below -18° altitude
- **Geodetic coordinates**: WGS84 (MPC observatory database)
- **Horizontal coordinates**: Altitude (0° = horizon, 90° = zenith) and azimuth computed in local frame
- **Refraction**: Not applied in altitude calculations (use Astropy for refined results)

## Caching Strategy

By default, CIPO caches ephemeris data to `./cache/` to reduce MPC server load:

```
cache/
├── ephem_NEOCP_Y28.pkl
└── ephem_PCCP_Y28.pkl
```

To refresh, delete the cache file or set `USE_CACHE=False` in config.

## Troubleshooting

### "No ephemeris available for today"
- Observatory code may not be registered with MPC or has no reported observations
- Check observatory code: https://minorplanetcenter.net/iau/lists/ObsCodes.html
- Try again later if the confirmation page has not received observations yet

### Chrome/Selenium errors
- Ensure Chrome/Chromium is installed: `google-chrome --version`
- Or install via webdriver-manager (automatic): `pip install webdriver-manager`

### Parsing failures
- MPC page layout may have changed; parser uses fallback strategies but may need updates
- Check raw page text: `text = fetch_mpc_data('NEOCP', 'Y28'); print(text[:1000])`

### Slow performance
- Enable caching (`USE_CACHE=True` in config)
- Increase `SELENIUM_IMPLICIT_WAIT` and `SELENIUM_PAGE_LOAD_WAIT` if page takes time to load

## Example: Complete Analysis

```python
from cipo import analyze_ephemeris_objects, calculate_observation_windows

# Get lunar observation windows for 2026
windows = calculate_observation_windows(-22.5, -43.5, 2026, 1)
print(f"Dark windows: {len(windows)}")

# Analyze visible objects during the first dark window
start, _, end = windows[0]
print(f"\nObjects visible during {start} to {end}:")

df = analyze_ephemeris_objects(
    obs_code='Y28',
    obj_type='NEOCP',
    altitude_min=20,
    duration_min=60,
    plot=True
)

if not df.empty:
    print("\nTop 5 highest-altitude objects:")
    print(df.nlargest(5, 'Max_Alt')[['Temp Desig', 'R.A.', 'Decl.', 'Max_Alt']])
else:
    print("No visible objects found.")
```

## Contributing

Contributions are welcome! Please:
1. Ensure all functions have docstrings
2. Add type hints
3. Run tests and validate against live MPC data
4. Update documentation if behavior changes

## License

[Add license information here]

## References

- Minor Planet Center: https://minorplanetcenter.net/
- Skyfield Astronomy Library: https://rhodesmill.org/skyfield/
- JPL Horizons System: https://ssd.jpl.nasa.gov/horizons/
- MPC Observatory Codes: https://minorplanetcenter.net/iau/lists/ObsCodes.html

## Authors

- **Lucas Correa de Souza** (lucascorreasouza@id.uff.br)
- **Mario De Pra** (depra@on.br)

## Citation

If you use CIPO in your research, please cite:

```
Correa de Souza, L., & De Pra, M. (2026). CIPO: Confirming Interplanetary Object Observatory. 
https://github.com/[repository]
```

---

**Last updated**: 2026-09-01  
**Version**: 0.1.0
