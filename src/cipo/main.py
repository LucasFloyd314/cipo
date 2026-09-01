"""High-level workflows for retrieving and analyzing MPC ephemerides.

The public functions in this module coordinate the full package pipeline:
download data for an MPC object type and observatory code, parse the
ephemeris tables, calculate visibility windows, and present the resulting
summary. The MPC values are interpreted in UTC; altitude thresholds are in
degrees and duration thresholds are in minutes.

Supported workflows:
1. analyze_ephemeris_objects: Fetch, analyze, and plot in one call
2. process_mpc_data: Analyze with optional interactive object inspection

All functions use configuration defaults from config.py but accept override
parameters for flexibility.
"""

from datetime import timedelta

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from astropy.time import Time

from .config import (
    DEFAULT_ALT_MIN,
    DEFAULT_DUR_MIN,
    DEFAULT_OBJ_TYPE,
    DEFAULT_OBS_CODE,
    PLOT_HOUR_END_UTC,
    PLOT_HOUR_START_UTC,
)
from .downloader import _download_mpc_table, _get_mpc_url, fetch_mpc_data
from .filter import filter_visible_objects
from .parser import parse_mpc_data


def analyze_ephemeris_objects(
    obs_code=DEFAULT_OBS_CODE,
    obj_type=DEFAULT_OBJ_TYPE,
    altitude_min=DEFAULT_ALT_MIN,
    duration_min=DEFAULT_DUR_MIN,
    plot=True
):
    """Retrieve, analyze, and optionally plot MPC ephemeris data.

    The function requests the selected MPC confirmation page, parses its
    ephemeris sections, and keeps objects with at least ``duration_min``
    minutes at or above ``altitude_min`` degrees while the Sun is below the
    package's twilight limit. Results are sorted by descending maximum
    altitude. When ``plot`` is true, a Matplotlib chart is displayed for the
    configured observing interval (defined in UTC).

    Args:
        obs_code: Three-character MPC observatory code used for the request.
        obj_type: MPC page/object category accepted by ``fetch_mpc_data``.
        altitude_min: Minimum object altitude in degrees.
        duration_min: Minimum visibility duration in minutes.
        plot: Display altitude curves for the selected objects when true.

    Returns:
        A pandas DataFrame with one row per selected object and these columns:
        ``Temp Desig`` (the provisional MPC identifier), ``R.A.`` and
        ``Decl.`` (J2000 coordinates), ``V`` (visual magnitude),
        ``Visible_Minutes``, ``Max_Alt`` (degrees), and
        ``Max_Alt_Time_UTC``. An empty DataFrame is returned when the
        request, parsing, or visibility criteria produce no results.

    Side effects:
        Performs a network request, prints status/results to stdout, and may
        open a Matplotlib window. Network or malformed-data errors are
        handled by the lower-level downloader/parser functions.
    """
    text = fetch_mpc_data(obj_type, obs_code)
    if not text:
        return pd.DataFrame()

    ephem_dict = parse_mpc_data(text)
    if not ephem_dict:
        print("No ephemeris data could be parsed.")
        return pd.DataFrame()

    df_visible = filter_visible_objects(ephem_dict, altitude_min, duration_min)

    if df_visible.empty:
        print("No visible objects found with the current criteria.")
        return df_visible

    # Remove objetos com duração <= 0
    df_visible = df_visible[df_visible['Visible_Minutes'] > 0]
    if df_visible.empty:
        print("No objects meet the minimum duration requirement.")
        return df_visible

    # Ordena por altitude máxima
    df_visible = df_visible.sort_values('Max_Alt', ascending=False)

    print("\n=== VISIBLE OBJECTS (duration > 0) ===")
    cols = ['Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes', 'Max_Alt', 'Max_Alt_Time_UTC']
    print(df_visible[cols].to_string(index=False))

    if plot:
        # --- Período noturno: 18h-5h local (UTC-3) => 21h-8h UTC ---
        now_utc = Time.now().datetime
        now_dt = pd.to_datetime(now_utc)

        # Define início da noite (hoje às 21h UTC)
        start_night = now_dt.replace(hour=PLOT_HOUR_START_UTC, minute=0, second=0, microsecond=0)
        if now_dt >= start_night:
            start_night += timedelta(days=1)

        # Fim da noite (dia seguinte às 8h UTC)
        end_night = start_night + timedelta(hours=(24 - PLOT_HOUR_START_UTC + PLOT_HOUR_END_UTC))

        # Offsets em horas a partir de agora
        start_offset = (start_night - now_dt).total_seconds() / 3600.0
        end_offset = (end_night - now_dt).total_seconds() / 3600.0

        if end_offset < 0:
            start_night += timedelta(days=1)
            end_night += timedelta(days=1)
            start_offset = (start_night - now_dt).total_seconds() / 3600.0
            end_offset = (end_night - now_dt).total_seconds() / 3600.0

        print(f"Plotting: {start_night} a {end_night} (UTC)")
        print(f"Offsets: {start_offset:.1f}h a {end_offset:.1f}h a partir de agora")

        plt.figure(figsize=(14, 7))

        for obj in df_visible['Temp Desig']:
            df_obj = ephem_dict[obj].copy()
            ut_clean = df_obj['UT'].astype(str).str.replace(r'[\s\.]', '', regex=True).str.zfill(4)
            df_obj['Datetime_UTC'] = pd.to_datetime(
                df_obj['Date'] + ' ' + ut_clean,
                format='%Y %m %d %H%M',
                errors='coerce'
            )
            df_obj = df_obj.dropna(subset=['Datetime_UTC'])
            df_obj['Object Alt'] = pd.to_numeric(df_obj['Object Alt'], errors='coerce')
            times_hours = (df_obj['Datetime_UTC'] - now_dt).dt.total_seconds() / 3600

            mask = (times_hours >= start_offset) & (times_hours <= end_offset)
            if mask.sum() > 0:
                plt.plot(
                    times_hours[mask],
                    df_obj['Object Alt'][mask],
                    marker='.',
                    linestyle='-',
                    linewidth=1.2,
                    alpha=0.7,
                    color='steelblue'
                )

        plt.axhline(altitude_min, color='red', linestyle='--', linewidth=2, label=f'Limite {altitude_min}°')
        plt.xlim(start_offset - 0.5, end_offset + 0.5)
        plt.ylim(0, 90)
        plt.xlabel('Hours from now (UTC)', fontsize=12)
        plt.ylabel('Altitude (°)', fontsize=12)
        plt.title(f'Curves of altitude for visible objects (OASI - code {obs_code})', fontsize=14)

        # Keeps only the limit legend (removes object names)
        plt.legend(loc='upper right')

        plt.grid(True, alpha=0.3)

        # Ticks every 2 hours
        ticks = np.arange(start_offset, end_offset + 1, 2)
        plt.xticks(ticks, [f'{int(t)}h' if t >= 0 else f'{int(t)}h' for t in ticks])

        plt.tight_layout()
        plt.show()

    return df_visible


def process_mpc_data(
    obs_code=DEFAULT_OBS_CODE,
    obj_type=DEFAULT_OBJ_TYPE,
    interactive_mode=True
):
    """Run visibility analysis without plotting and optionally inspect objects interactively.

    This convenience wrapper uses DEFAULT_ALT_MIN and DEFAULT_DUR_MIN from config,
    retrieves visible objects, and optionally starts a console prompt where a user
    can enter a value from the returned 'Temp Desig' column to view that object's
    detailed row. Enter '0' (zero) to exit the interactive prompt.

    This is useful for quick analysis workflows where you want to:
    1. Retrieve all visible objects for today
    2. Inspect individual objects without plotting
    3. Get detailed ephemeris data for planning

    Args:
        obs_code: Three-character MPC observatory code (default from config).
        obj_type: 'NEOCP' or 'PCCP' (default from config).
        interactive_mode: If True (default), enter console prompt to inspect objects
            by their 'Temp Desig' identifier. If False, return results silently.

    Returns:
        pandas.DataFrame with visible objects (same as analyze_ephemeris_objects),
        or empty DataFrame if no objects satisfy default criteria.

    Side effects:
        Performs network request and prints status/results. When interactive_mode
        is True, reads object identifiers from stdin and displays matching rows.

    Example:
        >>> df = process_mpc_data(obs_code='Y28')
        >>> # When prompted, enter an object name like 'K26A02' to see its details
        >>> # Enter '0' to exit
    """
    df_visible = analyze_ephemeris_objects(
        obs_code, obj_type,
        altitude_min=DEFAULT_ALT_MIN,
        duration_min=DEFAULT_DUR_MIN,
        plot=False
    )
    if df_visible.empty:
        return df_visible

    if interactive_mode:
        print("\n--- Interactive mode ---")
        while True:
            target = input("Enter 'Temp Desig' to see details (or '0' to exit): ").strip()
            if target == '0':
                break
            obj_row = df_visible[df_visible['Temp Desig'] == target]
            if not obj_row.empty:
                print(obj_row.iloc[0].to_string())
            else:
                print(f"Object '{target}' not found in the visible list.")

    return df_visible
