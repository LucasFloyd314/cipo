"""CIPO - Confirming Interplanetary Object Observatory.

A Python package for retrieving, parsing, and analyzing unconfirmed object
data from the Minor Planet Center's NEO Confirmation Page (NEOCP) and Possible
Comet Confirmation Page (PCCP), with support for visibility calculation and
scheduling for a given observatory.

Key modules:
- config: Configuration parameters (observatory code, altitude limits, etc.)
- downloader: Fetch ephemeris data from MPC pages using Selenium
- parser: Parse ephemeris tables into structured DataFrames
- filter: Filter objects by altitude and visibility duration criteria
- visibility: Calculate observation windows based on lunar phases
- main: High-level workflows (analyze_ephemeris_objects, process_mpc_data)
- graphics: Visualization and plotting utilities (advanced)

Example usage:
    from cipo import analyze_ephemeris_objects
    
    df = analyze_ephemeris_objects(
        obs_code='Y28',
        obj_type='NEOCP',
        altitude_min=10,
        duration_min=30,
        plot=True
    )
    print(df[['Temp Desig', 'R.A.', 'Decl.', 'Max_Alt']])
"""

from .config import *  # noqa: F401, F403
from .downloader import *  # noqa: F401, F403
from .filter import *  # noqa: F401, F403
from .main import *  # noqa: F401, F403
from .parser import *  # noqa: F401, F403
from .visibility import calculate_observation_windows  # noqa: F401

__version__ = "0.1.0"
__author__ = "Lucas Correa de Souza, Mario De Pra"

__all__ = [
    "analyze_ephemeris_objects",
    "process_mpc_data",
    "fetch_mpc_data",
    "parse_mpc_data",
    "filter_visible_objects",
    "calculate_observation_windows",
    "DEFAULT_OBS_CODE",
    "DEFAULT_OBJ_TYPE",
    "DEFAULT_ALT_MIN",
    "DEFAULT_DUR_MIN",
]

