import os

# User Configuration
OBS_CODE = 'Y28'                # Observatory IAU Code (ex: Y28 = OASI, Brasil)
OBJ_TYPE = 'NEOCP'              # 'NEOCP' or 'PCCP'
ALTITUDE_MIN = 10               # Minimum altitude for observation (degrees)
DURATION_MIN = 30               # Minimum continuous duration (minutes)
SUN_ALT_LIMIT = -18             # Sun altitude for astronomical night

# Program Configuration 
REQUESTS_TIMEOUT = 15
SELENIUM_IMPLICIT_WAIT = 10
SELENIUM_PAGE_LOAD_WAIT = 15
USE_CACHE = True
CACHE_DIR = "./cache"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; MPC-Bot/1.0)"}


# Defining Names for Default Values
DEFAULT_OBS_CODE = OBS_CODE
DEFAULT_OBJ_TYPE = OBJ_TYPE
DEFAULT_ALT_MIN = ALTITUDE_MIN
DEFAULT_DUR_MIN = DURATION_MIN

# Graphical Parameters
PLOT_START_HOUR = 12           # UTC time
PLOT_TIME_STEP_MINUTES = 10    # time step in minutes
PLOT_HOURS_RANGE = 24          # total hours to plot
PLOT_SUN_MOON = True           # include Sun and Moon in the plot
PLOT_LEGEND = False            # show legend in the plot