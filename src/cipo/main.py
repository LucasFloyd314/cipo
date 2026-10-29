"""High-level workflows for retrieving and analyzing MPC ephemerides."""

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time

from .config import DEFAULT_ALT_MIN, DEFAULT_DUR_MIN, DEFAULT_OBJ_TYPE, DEFAULT_OBS_CODE
from .downloader import _download_mpc_table, _get_mpc_url, fetch_mpc_data  # noqa: F401
from .filter import _filter_ephemerides_by_date, filter_visible_objects
from .graphics import (
    get_object_ephemeris,
    plot_object_altitude,
    plot_visibility_from_mpc,
)
from .parser import get_mpc_ephemeris_max_date, parse_mpc_data
from .visibility import calculate_oasi_observation_windows


def get_mpc_ephemeris_max_date_for_observatory(
    obs_code=DEFAULT_OBS_CODE,
    obj_type=DEFAULT_OBJ_TYPE,
    use_cache=False,
):
    """Fetch MPC ephemerides and return their latest available UTC date."""
    text = fetch_mpc_data(obj_type, obs_code, use_cache=use_cache)
    return get_mpc_ephemeris_max_date(text)


def get_oasi_observation_windows(
    reference_date=None,
    obs_code=DEFAULT_OBS_CODE,
    obj_type=DEFAULT_OBJ_TYPE,
    num_windows=2,
    use_cache=False,
):
    """Return upcoming OASI windows that fit within MPC availability.

    The windows are selected from ``reference_date`` onward and are limited to
    ``num_windows`` results. A window is eligible only when its end date is not
    later than the latest date returned by the MPC.
    """
    reference_date = reference_date or pd.Timestamp.utcnow().date()
    if hasattr(reference_date, 'date'):
        reference_date = reference_date.date()

    max_date = get_mpc_ephemeris_max_date_for_observatory(
        obs_code=obs_code,
        obj_type=obj_type,
        use_cache=use_cache,
    )
    if max_date is None:
        return []

    windows = calculate_oasi_observation_windows(reference_date.year, 2)
    return [
        window for window in windows
        if window['end_date'] >= reference_date and window['end_date'] <= max_date
    ][:num_windows]


def analyze_ephemeris_objects(
    obs_code=DEFAULT_OBS_CODE,
    obj_type=DEFAULT_OBJ_TYPE,
    altitude_min=DEFAULT_ALT_MIN,
    duration_min=DEFAULT_DUR_MIN,
    plot=True,
    plot_all=False,
    show_object_names=False,
    use_cache=False,
    print_visible=True,
    reference_date=None,
):
    """Retrieve, filter, and optionally plot MPC ephemerides.

    Args:
        reference_date: Optional UTC calendar date. When provided, visibility
            analysis and plotting use only MPC rows for that date.
    """
    text = fetch_mpc_data(obj_type, obs_code, use_cache=False)
    if not text:
        return pd.DataFrame()

    ephem_dict = parse_mpc_data(text)
    if not ephem_dict:
        print("No ephemeris data could be parsed.")
        return pd.DataFrame()

    ephem_dict = _filter_ephemerides_by_date(ephem_dict, reference_date)
    if not ephem_dict:
        print(f"No MPC ephemeris rows are available for {pd.Timestamp(reference_date).date()}.")
        return pd.DataFrame()

    df_visible = filter_visible_objects(ephem_dict, altitude_min, duration_min)
    if df_visible.empty and not (plot and plot_all):
        print("No visible objects found with the current criteria.")
        return df_visible

    df_visible = df_visible[df_visible['Visible_Minutes'] > 0]
    if df_visible.empty and not (plot and plot_all):
        print("No objects meet the minimum duration requirement.")
        return df_visible

    if not df_visible.empty:
        df_visible = df_visible.sort_values('Max_Alt', ascending=False)

    if not df_visible.empty and print_visible:
        print("\n=== VISIBLE OBJECTS (duration > 0) ===")
        columns = [
            'Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes',
            'Max_Alt', 'Max_Alt_Time_UTC',
        ]
        print(df_visible[columns].to_string(index=False))

    if plot:
        plot_visibility_from_mpc(
            obs_code=obs_code,
            obj_type=obj_type,
            alt_min=altitude_min,
            dur_min=duration_min,
            plot_legend=False,
            show_object_names=show_object_names,
            plot_sun_moon=True,
            start_hour=0,
            n_hours=24,
            step_minutes=10,
            plot_all=plot_all,
            ephem_dict=ephem_dict,
        )

    return df_visible


def get_prioritized_observable_objects(
    obs_code=DEFAULT_OBS_CODE,
    obj_type=DEFAULT_OBJ_TYPE,
    magnitude_max=18.0,
    altitude_min=10.0,
    duration_min=DEFAULT_DUR_MIN,
    reference_date=None,
):
    """Fetch and rank objects that meet visibility, magnitude, and altitude limits.

    The result includes only objects with ``V <= magnitude_max``, maximum
    altitude strictly greater than ``altitude_min``, and a visibility window
    of at least ``duration_min`` minutes during astronomical night. Candidates
    are ordered by maximum altitude (descending), magnitude (ascending), and
    visible duration (descending). The default date is today in UTC.

    Args:
        obs_code: Active MPC observatory code.
        obj_type: MPC confirmation page, either ``NEOCP`` or ``PCCP``.
        magnitude_max: Inclusive upper limit for the MPC V magnitude.
        altitude_min: Strict lower limit for maximum object altitude, in degrees.
        duration_min: Minimum visibility-window duration, in minutes.
        reference_date: UTC calendar date to analyze. Defaults to today in UTC.

    Returns:
        pandas.DataFrame: Ranked candidates with a one-based ``Prioridade``
        column. An empty result preserves the visibility-analysis columns.
    """
    if reference_date is None:
        reference_date = pd.Timestamp.now(tz="UTC").date()

    visible_objects = analyze_ephemeris_objects(
        obs_code=obs_code,
        obj_type=obj_type,
        altitude_min=altitude_min,
        duration_min=duration_min,
        plot=False,
        print_visible=False,
        reference_date=reference_date,
    )
    if visible_objects.empty:
        empty_result = visible_objects.copy()
        empty_result.insert(0, "Prioridade", pd.Series(dtype="int64"))
        return empty_result

    ranked_objects = visible_objects.copy()
    for column in ("V", "Max_Alt", "Visible_Minutes"):
        ranked_objects[column] = pd.to_numeric(ranked_objects[column], errors="coerce")

    eligible = (
        (ranked_objects["V"] <= magnitude_max)
        & (ranked_objects["Max_Alt"] > altitude_min)
    )
    ranked_objects = ranked_objects.loc[eligible].copy()
    ranked_objects = ranked_objects.sort_values(
        by=["Max_Alt", "V", "Visible_Minutes"],
        ascending=[False, True, False],
        kind="stable",
    ).reset_index(drop=True)
    ranked_objects.insert(
        0,
        "Prioridade",
        range(1, len(ranked_objects) + 1),
    )
    return ranked_objects


def _extract_constant_coordinates(df_obj):
    """Extract the fixed RA/Dec represented by an MPC ephemeris row."""
    ra_tokens = str(df_obj['R.A. (J2000)'].iloc[0]).split()
    dec_tokens = str(df_obj['Decl'].iloc[0]).split()
    if len(ra_tokens) >= 3 and len(dec_tokens) >= 3:
        ra_parts = ra_tokens[:3]
        dec_parts = dec_tokens[:3]
    elif len(ra_tokens) >= 4 and len(dec_tokens) >= 2:
        ra_parts = ra_tokens[:3]
        dec_parts = [ra_tokens[3], *dec_tokens[:2]]
    else:
        return None

    try:
        ra = float(ra_parts[0]) + float(ra_parts[1]) / 60 + float(ra_parts[2]) / 3600
        sign = -1 if dec_parts[0].startswith('-') else 1
        degrees = abs(float(dec_parts[0])) + float(dec_parts[1]) / 60 + float(dec_parts[2]) / 3600
        return ra, sign * degrees
    except (TypeError, ValueError):
        return None


def process_mpc_data(
    obs_code=DEFAULT_OBS_CODE,
    obj_type=DEFAULT_OBJ_TYPE,
    interactive_mode=True,
    print_visible=True,
    reference_date=None,
    plot=False,
):
    """Run visibility analysis for today's UTC date by default.

    Args:
        obs_code: MPC observatory code used to retrieve ephemerides.
        obj_type: MPC confirmation page, either NEOCP or PCCP.
        interactive_mode: Prompt for object details when enabled.
        print_visible: Print the summary table when enabled.
        reference_date: UTC calendar date to analyze. Defaults to today in UTC.
        plot: Display the visibility plot when enabled.
    """
    if reference_date is None:
        reference_date = pd.Timestamp.now(tz="UTC").date()

    df_visible = analyze_ephemeris_objects(
        obs_code=obs_code,
        obj_type=obj_type,
        altitude_min=DEFAULT_ALT_MIN,
        duration_min=DEFAULT_DUR_MIN,
        plot=plot,
        print_visible=print_visible,
        reference_date=reference_date,
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
