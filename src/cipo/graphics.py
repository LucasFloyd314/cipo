"""Advanced visualization and plotting utilities for CIPO ephemeris data.

This module provides tools for generating detailed altitude curves and visibility
plots with Sun/Moon overlays. All astronomical calculations use Astropy for
consistency and accuracy.

Note:
    This module extends the main analysis pipeline with advanced plotting.
    For basic visibility analysis, use main.py functions instead.
"""

from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time
from astropy import units as u

from .config import DEFAULT_ALT_MIN, DEFAULT_DUR_MIN, DEFAULT_OBJ_TYPE, DEFAULT_OBS_CODE
from .downloader import fetch_mpc_data
from .parser import parse_mpc_data


# ============================================================================
# Coordinate Conversion Utilities
# ============================================================================

def hms_to_degrees(ra_str):
    """Convert RA string in 'HH MM SS.s' format to degrees.

    Args:
        ra_str: Right Ascension as 'HH MM SS.s' (sexagesimal).

    Returns:
        float: RA in degrees (0-360), or None if parsing fails.

    Example:
        >>> hms_to_degrees('12 34 56.7')
        188.7362...
    """
    try:
        parts = ra_str.strip().split()
        if len(parts) != 3:
            return None
        h, m, s = map(float, parts)
        return (h + m / 60 + s / 3600) * 15
    except (ValueError, TypeError):
        return None


def dms_to_degrees(dec_str):
    """Convert Dec string in '±DD MM SS.s' format to degrees.

    Args:
        dec_str: Declination as '±DD MM SS.s' (sexagesimal).

    Returns:
        float: Dec in degrees (-90 to +90), or None if parsing fails.

    Example:
        >>> dms_to_degrees('-45 30 15.2')
        -45.5042...
    """
    try:
        s = dec_str.strip()
        sign = -1 if s.startswith('-') else 1
        if s.startswith(('+', '-')):
            s = s[1:]
        parts = s.split()
        if len(parts) != 3:
            return None
        d, m, s = map(float, parts)
        return sign * (abs(d) + m / 60 + s / 3600)
    except (ValueError, TypeError):
        return None


# ============================================================================
# Main Plotting Function
# ============================================================================

def plot_visibility_from_mpc(
    obs_code=DEFAULT_OBS_CODE,
    obj_type=DEFAULT_OBJ_TYPE,
    alt_min=DEFAULT_ALT_MIN,
    dur_min=DEFAULT_DUR_MIN,
    plot_legend=False,
    plot_sun_moon=True,
    start_hour=0,
    n_hours=24,
    step_minutes=10,
    plot_all=False
):
    """Generate detailed altitude plot for unconfirmed objects with Sun/Moon overlays.

    Fetches ephemeris data from MPC and generates a comprehensive visibility plot
    with optional Sun and Moon altitude curves. All calculations use Astropy for
    astronomical accuracy.

    Args:
        obs_code: Three-character MPC observatory code (default from config).
        obj_type: 'NEOCP' or 'PCCP' (default from config).
        alt_min: Minimum altitude to consider visible (degrees).
        dur_min: Minimum continuous duration above alt_min (minutes).
        plot_legend: If True, display legend on plot.
        plot_sun_moon: If True, overlay Sun and Moon altitude curves.
        start_hour: Start time for plot in UTC hours (0-23).
        n_hours: Duration of plot window (hours).
        step_minutes: Time step for ephemeris grid (minutes).
        plot_all: If True, plot all objects; if False, apply altitude/duration filter.

    Returns:
        tuple: (df_summary, time_points) where:
        - df_summary: DataFrame with object summaries (Temp Desig, Max_Alt, Max_Alt_Time_UTC)
        - time_points: List of datetime objects for x-axis

    Side effects:
        Performs network request, prints status messages, and displays matplotlib plot.

    Raises:
        ImportError: If Astropy is not installed.

    Notes:
        - All times are UTC
        - Altitude is topocentric (observer's horizon)
        - Sun/Moon altitudes use Astropy's built-in ephemerides
    """
    print(f"Fetching {obj_type} data for observatory {obs_code}...")
    text = fetch_mpc_data(obj_type, obs_code)
    if not text:
        print("Failed to fetch data.")
        return pd.DataFrame(), []

    ephem_dict = parse_mpc_data(text)
    if not ephem_dict:
        print("No ephemeris data parsed.")
        return pd.DataFrame(), []

    print(f"Parsed {len(ephem_dict)} objects.")

    # Define time grid
    first_obj = next(iter(ephem_dict.keys()))
    first_date_str = ephem_dict[first_obj]['Date'].iloc[0]
    try:
        data_ref = datetime.strptime(first_date_str, '%Y %m %d').replace(tzinfo=timezone.utc)
    except (ValueError, IndexError):
        data_ref = datetime.now(tz=timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    start_time = data_ref.replace(hour=start_hour, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    n_steps = int(n_hours * 60 / step_minutes) + 1
    time_points = [start_time + timedelta(minutes=step_minutes * i) for i in range(n_steps)]

    print(f"Time grid: {len(time_points)} points from {start_time.strftime('%H:%M')} to {time_points[-1].strftime('%H:%M')} UTC")

    # Calculate altitudes for each object
    altitudes_dict = _calculate_altitudes_astropy(ephem_dict, obs_code, time_points)

    if not altitudes_dict:
        print("ERROR: No altitudes calculated.")
        return pd.DataFrame(), time_points

    print(f"Calculated altitudes for {len(altitudes_dict)} objects.")

    # Filter objects
    filtered_objects = (altitudes_dict if plot_all 
                       else _filter_objects_by_visibility(altitudes_dict, alt_min, dur_min, step_minutes))

    if not filtered_objects:
        print("No objects meet the criteria. Try plot_all=True or lower the thresholds.")
        return pd.DataFrame(), time_points

    print(f"{len(filtered_objects)} objects to plot.")

    # Generate summary
    df_summary = _generate_summary(filtered_objects, time_points)

    # Create plot
    _plot_altitudes(filtered_objects, time_points, obs_code, obj_type, alt_min, dur_min, 
                    plot_all, plot_legend, plot_sun_moon)

    return df_summary, time_points


# ============================================================================
# Helper Functions
# ============================================================================

def _calculate_altitudes_astropy(ephem_dict, obs_code, time_points):
    """Calculate altitudes for all objects using Astropy.

    Args:
        ephem_dict: Dictionary mapping object names to ephemeris DataFrames.
        obs_code: Observatory code for coordinate lookup.
        time_points: List of datetime objects.

    Returns:
        dict: Maps object name to array of altitudes (degrees).
    """
    # Get observatory location (hardcoded for now; can be extended to database lookup)
    locations = {
        'Y28': {'lat': -22.5, 'lon': -43.5, 'name': 'OASI (Brazil)'},
        # Add more observatories as needed
    }

    if obs_code not in locations:
        print(f"Warning: Observatory {obs_code} not in location database. Using default coordinates.")
        lat_deg, lon_deg = -22.5, -43.5
    else:
        lat_deg = locations[obs_code]['lat']
        lon_deg = locations[obs_code]['lon']

    print(f"Observatory: {obs_code} (Lat={lat_deg:.4f}°, Lon={lon_deg:.4f}°)")

    location = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg, height=0 * u.m)
    time_utc = Time(time_points)

    altitudes_dict = {}

    for obj_name, df in ephem_dict.items():
        try:
            ra_str = df['R.A. (J2000)'].iloc[0].strip()
            dec_str = df['Decl'].iloc[0].strip()

            ra_deg = hms_to_degrees(ra_str)
            dec_deg = dms_to_degrees(dec_str)

            if ra_deg is None or dec_deg is None:
                print(f"  Warning: {obj_name}: Could not parse RA/Dec")
                continue

            # Create sky coordinate and transform to AltAz
            coord = SkyCoord(ra=ra_deg * u.deg, dec=dec_deg * u.deg)
            altaz = coord.transform_to(AltAz(obstime=time_utc, location=location))
            altitudes_dict[obj_name] = altaz.alt.deg

        except (ValueError, IndexError, KeyError) as e:
            print(f"  Warning: {obj_name}: {type(e).__name__}: {e}")

    return altitudes_dict


def _filter_objects_by_visibility(altitudes_dict, alt_min, dur_min, step_minutes):
    """Filter objects by minimum altitude and duration criteria.

    Args:
        altitudes_dict: Dict mapping object names to altitude arrays.
        alt_min: Minimum altitude (degrees).
        dur_min: Minimum duration (minutes).
        step_minutes: Time step between points (minutes).

    Returns:
        dict: Filtered subset of altitudes_dict.
    """
    min_consecutive_steps = int(dur_min / step_minutes) if step_minutes > 0 else 1
    filtered = {}

    for obj, alts in altitudes_dict.items():
        consecutive = 0
        for alt in alts:
            if alt >= alt_min:
                consecutive += 1
                if consecutive >= min_consecutive_steps:
                    filtered[obj] = alts
                    break
            else:
                consecutive = 0

    return filtered


def _generate_summary(filtered_objects, time_points):
    """Generate summary DataFrame for filtered objects.

    Args:
        filtered_objects: Dict mapping object names to altitude arrays.
        time_points: List of datetime objects.

    Returns:
        pandas.DataFrame: Summary with Temp Desig, Max_Alt, Max_Alt_Time_UTC.
    """
    rows = []

    for obj, alts in filtered_objects.items():
        if not alts or len(alts) == 0:
            continue

        max_alt = np.max(alts)
        idx_max = np.argmax(alts)
        max_time = time_points[idx_max]

        rows.append({
            'Temp Desig': obj,
            'Max_Alt': round(max_alt, 1),
            'Max_Alt_Time_UTC': max_time
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _plot_altitudes(filtered_objects, time_points, obs_code, obj_type, alt_min, dur_min,
                   plot_all, plot_legend, plot_sun_moon):
    """Create and display altitude plot.

    Args:
        filtered_objects: Dict mapping object names to altitude arrays.
        time_points: List of datetime objects.
        obs_code: Observatory code.
        obj_type: Object type (NEOCP/PCCP).
        alt_min: Minimum altitude threshold (degrees).
        dur_min: Minimum duration (minutes).
        plot_all: Whether all objects or filtered subset.
        plot_legend: Whether to show legend.
        plot_sun_moon: Whether to overlay Sun/Moon.
    """
    fig, ax = plt.subplots(figsize=(15, 7))

    # Plot object altitudes
    for alts in filtered_objects.values():
        ax.plot(time_points, alts, color='steelblue', linestyle='-', linewidth=1.2, 
               alpha=0.6, marker='.')

    # Plot altitude threshold
    if not plot_all:
        ax.axhline(alt_min, color='red', linestyle='--', linewidth=2, label=f'Limit {alt_min}°')

    # Plot Sun and Moon if requested
    if plot_sun_moon:
        _overlay_sun_moon(ax, time_points, obs_code)

    # Format plot
    ax.set_ylim(-10, 90)
    ax.set_xlabel('Date/Time (UTC)', fontsize=12)
    ax.set_ylabel('Altitude (°)', fontsize=12)

    title = f'Object Visibility - {obj_type} (obs. {obs_code})'
    if not plot_all:
        title += f'\nObjects above {alt_min}° for ≥ {dur_min} min'
    else:
        title += '\nAll objects (no filter)'
    ax.set_title(title, fontsize=14)

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=3))
    fig.autofmt_xdate()

    if plot_legend:
        ax.legend(loc='upper right')
    else:
        if ax.get_legend() is not None:
            ax.get_legend().remove()

    ax.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


def _overlay_sun_moon(ax, time_points, obs_code):
    """Overlay Sun and Moon altitude curves on plot.

    Args:
        ax: Matplotlib axis.
        time_points: List of datetime objects.
        obs_code: Observatory code.
    """
    # Observatory locations (same as in _calculate_altitudes_astropy)
    locations = {
        'Y28': {'lat': -22.5, 'lon': -43.5},
    }

    if obs_code not in locations:
        print("Warning: Observatory not in location database. Skipping Sun/Moon overlay.")
        return

    lat_deg = locations[obs_code]['lat']
    lon_deg = locations[obs_code]['lon']
    location = EarthLocation(lat=lat_deg * u.deg, lon=lon_deg * u.deg, height=0 * u.m)
    time_utc = Time(time_points)

    print("Computing Sun and Moon altitudes...")

    try:
        # Get Sun and Moon altitudes
        sun = get_body('sun', time_utc, location)
        moon = get_body('moon', time_utc, location)

        sun_altaz = sun.transform_to(AltAz(obstime=time_utc, location=location))
        moon_altaz = moon.transform_to(AltAz(obstime=time_utc, location=location))

        sun_alts = sun_altaz.alt.deg
        moon_alts = moon_altaz.alt.deg

        # Plot Sun and Moon
        ax.plot(time_points, sun_alts, color='gold', linestyle='--', linewidth=2, label='Sun')
        ax.plot(time_points, moon_alts, color='gray', linestyle='--', linewidth=2, label='Moon')

        # Mark sunrise/sunset
        for i in range(1, len(sun_alts)):
            if sun_alts[i - 1] < 0 <= sun_alts[i]:
                ax.axvline(time_points[i], color='orange', linestyle=':', linewidth=1.5, alpha=0.7)
            elif sun_alts[i - 1] >= 0 > sun_alts[i]:
                ax.axvline(time_points[i], color='red', linestyle=':', linewidth=1.5, alpha=0.7)

    except (ValueError, IndexError, TypeError) as e:
        print(f"Warning: Could not compute Sun/Moon altitudes: {type(e).__name__}: {e}")
