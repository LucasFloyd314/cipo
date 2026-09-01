"""Configuration parameters for CIPO.

This module centralizes all user-adjustable settings:
- Observatory identification (IAU code)
- Observation criteria (altitude, duration, twilight)
- Network and browser timeouts
- Caching behavior
- Plotting defaults

Edit these parameters to customize CIPO's behavior without modifying core code.

Notes:
    - Longitude is geocentric (MPC convention), with West > 180° (or use negative)
    - Altitude is topocentric (observer's horizon)
    - Times are all in UTC
    - Solar twilight (-18°) defines astronomical night
"""

# ============================================================================
# User Configuration: Observable and Site Parameters
# ============================================================================

OBS_CODE = 'Y28'                # Observatory IAU Code (e.g., Y28 = OASI, Brasil)
OBJ_TYPE = 'NEOCP'              # Default object type: 'NEOCP' or 'PCCP'
ALTITUDE_MIN = 10               # Minimum altitude for observation (degrees)
DURATION_MIN = 30               # Minimum continuous duration above ALTITUDE_MIN (minutes)
SUN_ALT_LIMIT = -18             # Sun altitude limit for astronomical night (degrees)

# ============================================================================
# Program Configuration: Network and Caching
# ============================================================================

REQUESTS_TIMEOUT = 15           # HTTP request timeout (seconds)
SELENIUM_IMPLICIT_WAIT = 10     # Selenium implicit wait (seconds)
SELENIUM_PAGE_LOAD_WAIT = 15    # Selenium explicit wait for page load (seconds)
USE_CACHE = True                # Cache ephemeris locally to reduce MPC load
CACHE_DIR = "./cache"           # Directory to store cached ephemeris files
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MPC-Bot/1.0)"}  # HTTP headers

# ============================================================================
# Defaults: Exported Names for Backward Compatibility
# ============================================================================

DEFAULT_OBS_CODE = OBS_CODE
DEFAULT_OBJ_TYPE = OBJ_TYPE
DEFAULT_ALT_MIN = ALTITUDE_MIN
DEFAULT_DUR_MIN = DURATION_MIN

# ============================================================================
# Graphical Parameters: Plotting and Visualization
# ============================================================================

PLOT_HOUR_START_UTC = 21        # Start of observing window in UTC (e.g., 21 = 9 PM)
PLOT_HOUR_END_UTC = 8           # End of observing window in UTC (next day, e.g., 8 = 8 AM)
PLOT_START_HOUR = 12            # Default UTC start hour for plotting
PLOT_TIME_STEP_MINUTES = 10     # Time step for ephemeris grid (minutes)
PLOT_HOURS_RANGE = 24           # Total hours to plot in visualization
PLOT_SUN_MOON = True            # Include Sun and Moon altitude curves in plot
PLOT_LEGEND = False             # Show legend in altitude plot
