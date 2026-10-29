"""CIPO - Confirming Interplanetary Object Observatory.

The package retrieves and parses provisional ephemerides from the MPC,
filters objects by site visibility, and helps rank observing opportunities
for candidate NEO/PCCP targets. The default behavior is intentionally
conservative: provisional ephemerides are treated as visibility candidates,
not as a final orbit product.
"""

from .config import *  # noqa: F401, F403
from .downloader import *  # noqa: F401, F403
from .filter import *  # noqa: F401, F403
from .main import *  # noqa: F401, F403
from .parser import *  # noqa: F401, F403
from .graphics import get_object_ephemeris, plot_object_altitude, plot_visibility_from_mpc  # noqa: F401
from .visibility import (  # noqa: F401
    calculate_observation_windows,
    calculate_oasi_observation_windows,
    calculate_site_observation_windows,
)

__version__ = "0.1.1"
__author__ = "Lucas Correa de Souza, Mario De Pra"

__all__ = [
    "analyze_ephemeris_objects",
    "get_prioritized_observable_objects",
    "process_mpc_data",
    "get_mpc_ephemeris_max_date_for_observatory",
    "oasi_observation_windows",
    "get_oasi_observation_windows",
    "fetch_mpc_data",
    "get_object_ephemeris",
    "plot_object_altitude",
    "plot_visibility_from_mpc",
    "parse_mpc_data",
    "filter_visible_objects",
    "calculate_observation_windows",
    "calculate_oasi_observation_windows",
    "calculate_site_observation_windows",
    "DEFAULT_OBS_CODE",
    "DEFAULT_OBJ_TYPE",
    "DEFAULT_ALT_MIN",
    "DEFAULT_DUR_MIN",
]
