"""Advanced visualization and plotting utilities for CIPO ephemeris data.

This module provides tools for generating detailed altitude curves and visibility
plots with Sun/Moon overlays. All astronomical calculations use Astropy for
consistency and accuracy.

Note:
    This module extends the main analysis pipeline with advanced plotting.
    For basic visibility analysis, use main.py functions instead.
"""

from datetime import date, datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from astropy import units as u
from astropy.coordinates import AltAz, EarthLocation, SkyCoord, get_body
from astropy.time import Time

from .config import (
    DEFAULT_ALT_MIN,
    DEFAULT_DUR_MIN,
    DEFAULT_OBJ_TYPE,
    DEFAULT_OBS_CODE,
    SUN_ALT_LIMIT,
)
from .downloader import fetch_mpc_data
from .parser import parse_mpc_data

# ============================================================================
# Coordinate Conversion Utilities
# ============================================================================

def hms_to_degrees(ra_str):
    """Convert RA string in 'HH MM SS.s' or 'HH:MM:SS.s' format to degrees.

    Args:
        ra_str: Right Ascension as sexagesimal data.

    Returns:
        float: RA in degrees (0-360), or None if parsing fails.
    """
    try:
        normalized = str(ra_str).strip().replace(':', ' ')
        parts = normalized.split()
        if len(parts) != 3:
            return None
        h, m, s = map(float, parts)
        return (h + m / 60 + s / 3600) * 15
    except (ValueError, TypeError):
        return None


def dms_to_degrees(dec_str):
    """Convert Dec string in '±DD MM SS.s' or '±DD:MM:SS.s' format to degrees.

    Args:
        dec_str: Declination as sexagesimal data.

    Returns:
        float: Dec in degrees (-90 to +90), or None if parsing fails.
    """
    try:
        s = str(dec_str).strip().replace(':', ' ')
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
    show_object_names=False,
    plot_sun_moon=True,
    start_hour=0,
    n_hours=24,
    step_minutes=10,
    plot_all=False,
    ephem_dict=None,
):
    """Generate an altitude plot for unconfirmed objects with Sun/Moon overlays.

    Uses the supplied parsed ephemerides when available; otherwise fetches and
    parses MPC data. Generates a visibility plot with optional Sun and Moon
    altitude curves. All calculations use Astropy.

    Args:
        obs_code: Three-character MPC observatory code (default from config).
        obj_type: 'NEOCP' or 'PCCP' (default from config).
        alt_min: Minimum altitude to consider visible (degrees).
        dur_min: Minimum continuous duration above alt_min (minutes).
        plot_legend: If True, display legend on plot.
        show_object_names: If True, include object names in the plot legend.
        plot_sun_moon: If True, overlay Sun and Moon altitude curves.
        start_hour: Start time for plot in UTC hours (0-23).
        n_hours: Duration of plot window (hours).
        step_minutes: Time step for ephemeris grid (minutes).
        plot_all: If True, plot all objects; if False, apply altitude/duration filter.
        ephem_dict: Optional parsed MPC ephemerides. When supplied, avoids a
            second network request and plots these already selected data.

    Returns:
        tuple: (df_summary, time_points) where:
        - df_summary: DataFrame with object summaries (Temp Desig, Max_Alt, Max_Alt_Time_UTC)
        - time_points: List of datetime objects for x-axis

    Side effects:
        May perform a network request, prints status messages, and displays a
        matplotlib plot.

    Raises:
        ImportError: If Astropy is not installed.

    Notes:
        - All times are UTC
        - Altitude is topocentric (observer's horizon)
        - Sun/Moon altitudes use Astropy's built-in ephemerides
    """
    if ephem_dict is None:
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
    _plot_altitudes(
        filtered_objects, time_points, obs_code, obj_type, alt_min, dur_min,
        plot_all, plot_legend, show_object_names, plot_sun_moon,
    )

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


def _calculate_object_altitude_curve(dataframe, time_points, location):
    """Calculate a smooth OASI altitude curve from changing MPC RA/Dec rows.

    MPC ephemerides provide position samples at separate UTC times. This helper
    interpolates RA and declination over the requested timeline, unwraps right
    ascension near 360 degrees, creates an Astropy SkyCoord, and transforms it
    into the observer's AltAz frame.
    """
    if dataframe is None or dataframe.empty:
        return np.full(len(time_points), np.nan)

    row_times = []
    right_ascensions = []
    declinations = []
    reference_epoch = time_points[0].replace(tzinfo=timezone.utc)

    for _, row in dataframe.iterrows():
        try:
            date_parts = str(row['Date']).strip().replace('-', ' ').split()
            ut_text = str(row['UT']).strip().replace('*', '')
            if ':' in ut_text:
                hour_text, minute_text = ut_text.split(':', 1)
                hour_value, minute_value = int(hour_text), int(minute_text)
            else:
                digits = ''.join(character for character in ut_text if character.isdigit())
                if len(digits) == 1:
                    digits = digits + '00'
                hour_value = int(digits[:2]) if len(digits) >= 2 else 0
                minute_value = int(digits[2:].zfill(2)) if len(digits) > 2 else 0

            row_time = datetime(
                int(date_parts[0]), int(date_parts[1]), int(date_parts[2]),
                hour_value, minute_value, tzinfo=timezone.utc,
            )
            ra_deg = hms_to_degrees(row['R.A. (J2000)'])
            dec_deg = dms_to_degrees(row['Decl'])
            if ra_deg is None or dec_deg is None:
                continue
            row_times.append((row_time - reference_epoch).total_seconds())
            right_ascensions.append(ra_deg)
            declinations.append(dec_deg)
        except (KeyError, TypeError, ValueError, IndexError):
            continue

    if len(row_times) < 1:
        return np.full(len(time_points), np.nan)

    grid_seconds = np.array([
        (moment.replace(tzinfo=timezone.utc) - reference_epoch).total_seconds()
        for moment in time_points
    ])

    if len(row_times) == 1:
        interpolated_ra = np.full(len(time_points), right_ascensions[0])
        interpolated_dec = np.full(len(time_points), declinations[0])
    else:
        ra_array = np.asarray(right_ascensions)
        ra_unwrapped = np.rad2deg(np.unwrap(np.deg2rad(ra_array)))
        interpolated_ra = np.interp(grid_seconds, row_times, ra_unwrapped)
        interpolated_dec = np.interp(grid_seconds, row_times, np.asarray(declinations))

    astropy_times = Time(time_points)
    coordinates = SkyCoord(
        ra=np.asarray(interpolated_ra) * u.deg,
        dec=np.asarray(interpolated_dec) * u.deg,
        frame='icrs',
    )
    altaz = coordinates.transform_to(AltAz(obstime=astropy_times, location=location))
    return altaz.alt.deg


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


def _compute_night_bounds(time_points, obs_code, sun_alt_limit):
    """Return the interval in UTC when astronomical night is active.

    The start of night is the first time when the Sun crosses the configured
    altitude limit from above to below. The end is the later crossing back to
    daylight. The interval is then used to center the plot on the night.
    """
    if not time_points:
        return None, None

    location = EarthLocation(
        lat=-22.5 * u.deg,
        lon=-43.5 * u.deg,
        height=0 * u.m,
    )
    time_utc = Time(time_points)
    sun = get_body('sun', time_utc, location)
    sun_altaz = sun.transform_to(AltAz(obstime=time_utc, location=location))
    sun_alt = sun_altaz.alt.deg

    crossings = []
    for i in range(1, len(sun_alt)):
        prev_alt = float(sun_alt[i - 1])
        curr_alt = float(sun_alt[i])
        if prev_alt >= sun_alt_limit > curr_alt:
            crossings.append((time_points[i], 'start'))
        elif prev_alt <= sun_alt_limit < curr_alt:
            crossings.append((time_points[i], 'end'))

    if not crossings:
        return None, None

    night_start = None
    night_end = None
    for moment, kind in crossings:
        if kind == 'start' and night_start is None:
            night_start = moment
        if kind == 'end' and night_start is not None and night_end is None:
            night_end = moment

    if night_start is not None and night_end is None and len(time_points) > 1:
        night_end = time_points[-1]
    if night_start is None and night_end is not None and len(time_points) > 1:
        night_start = time_points[0]

    return night_start, night_end


def _plot_altitudes(filtered_objects, time_points, obs_code, obj_type, alt_min, dur_min,
                   plot_all, plot_legend, show_object_names, plot_sun_moon):
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
    fig, ax = plt.subplots(figsize=(15, 8), facecolor='white')
    fig.patch.set_facecolor('white')
    ax.set_facecolor('#f4f7fb')

    # Plot object altitudes
    colors = plt.get_cmap('tab20', max(len(filtered_objects), 1))
    for color_index, (obj_name, alts) in enumerate(filtered_objects.items()):
        ax.plot(
            time_points,
            alts,
            color=colors(color_index),
            linestyle='-',
            linewidth=1.5,
            alpha=0.75,
            marker='.',
            markersize=2,
            label=obj_name if show_object_names else None,
            zorder=3,
        )

    # Plot altitude threshold
    if not plot_all:
        ax.axhline(alt_min, color='crimson', linestyle='--', linewidth=2, label=f'Limite {alt_min}°', zorder=2)

    # Plot Sun and Moon if requested
    if plot_sun_moon:
        _overlay_sun_moon(ax, time_points, obs_code)

    night_start, night_end = _compute_night_bounds(time_points, obs_code, SUN_ALT_LIMIT)
    if night_start is not None and night_end is not None:
        ax.axvspan(night_start, night_end, facecolor='#1f2d3d', alpha=0.12, zorder=1)
        ax.axvline(night_start, color='#0f172a', linestyle='--', linewidth=1.5, alpha=0.9, zorder=4)
        ax.axvline(night_end, color='#0f172a', linestyle='--', linewidth=1.5, alpha=0.9, zorder=4)
        ax.annotate(
            'Night begins\n' + night_start.strftime('%Y/%m/%d %H:%M UTC'),
            xy=(night_start, 0),
            xytext=(10, 18),
            textcoords='offset points',
            fontsize=9,
            color='#0f172a',
            bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='0.7', alpha=0.8),
            rotation=0,
            va='bottom',
        )
        ax.annotate(
            'Fim da noite\n' + night_end.strftime('%Y/%m/%d %H:%M UTC'),
            xy=(night_end, 0),
            xytext=(10, -30),
            textcoords='offset points',
            fontsize=9,
            color='#0f172a',
            bbox=dict(boxstyle='round,pad=0.25', fc='white', ec='0.7', alpha=0.8),
            rotation=0,
            va='top',
        )
        ax.set_xlim(night_start - timedelta(hours=1), night_end + timedelta(hours=1))

    # Format plot
    ax.set_ylim(-10, 90)
    ax.set_xlabel('Time (UTC)', fontsize=12)
    ax.set_ylabel('Altitude (°)', fontsize=12)

    title = f'Curvas de altitude - {obj_type} (obs. {obs_code})'
    if not plot_all:
        title += f'\nObjects above {alt_min}° during astronomical night'
    else:
        title += '\nAll objects (unfiltered)'
    ax.set_title(title, fontsize=14, weight='bold')

    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y/%m/%d %H:%M'))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
    fig.autofmt_xdate()

    if plot_legend or show_object_names:
        ax.legend(loc='upper right', frameon=True, fontsize=8)
    else:
        if ax.get_legend() is not None:
            ax.get_legend().remove()

    ax.grid(True, alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    plt.tight_layout()
    plt.show()


def get_object_ephemeris(object_name, obs_code=DEFAULT_OBS_CODE, obj_type=DEFAULT_OBJ_TYPE,
                         reference_date=None, use_cache=False):
    """Retrieve and return one object's complete MPC ephemeris DataFrame.

    The selected object must be present in an observatory-specific MPC response.
    When ``reference_date`` is supplied, rows outside that UTC calendar date
    are excluded. The function intentionally returns a copy without changing
    the temporary designation or treating it as a confirmed orbit.
    """
    text = fetch_mpc_data(obj_type, obs_code, use_cache=use_cache)
    if not text:
        raise ValueError("The MPC ephemeris request returned no data.")

    ephemerides = parse_mpc_data(text)
    normalized_name = str(object_name).strip().upper()
    for name, dataframe in ephemerides.items():
        if str(name).strip().upper() == normalized_name:
            result = dataframe.copy()
            if reference_date is not None:
                if hasattr(reference_date, "date"):
                    reference_date = reference_date.date()
                elif isinstance(reference_date, datetime):
                    reference_date = reference_date.date()
                result = result.loc[
                    result["Date"].apply(
                        lambda value: str(value).replace("-", " ").strip()
                    ).eq(reference_date.strftime("%Y %m %d"))
                ].copy()
            return result.reset_index(drop=True)

    raise KeyError(f"Object {object_name!r} was not found in the MPC ephemeris response.")


def plot_object_altitude(object_name, obs_code=DEFAULT_OBS_CODE,
                         obj_type=DEFAULT_OBJ_TYPE, reference_date=None,
                         ephemeris_dataframe=None, use_cache=False,
                         step_minutes=10):
    """Plot one object's altitude and Sun/Moon comparison for OASI.

    The object's curve uses the changing MPC RA/Dec ephemeris rows and is
    transformed to OASI AltAz coordinates. Values are interpolated to a fine
    UTC timeline, so the curve is smooth without inventing object altitude
    values or treating ``Object Alt`` as a continuous measurement. Solar
    twilight determines the exact shaded astronomical-night interval; the Moon
    altitude is calculated by Astropy at OASI (Y28). The shaded
    period marks astronomical night (Sun altitude <= -18 degrees), while
    vertical dashed markers show sunrise and sunset.

    Args:
        object_name: Temporary MPC designation, such as ``CEXJ3W2``.
        obs_code: MPC observatory code; Y28 identifies OASI.
        obj_type: MPC confirmation page, either NEOCP or PCCP.
        reference_date: UTC date represented as date, datetime, or YYYY/MM/DD string.
        ephemeris_dataframe: Optional complete ephemeris for one object. Supplying
            this value avoids a network request.
        use_cache: Whether to use the downloader cache when fetching.
        step_minutes: Synthetic plot-grid interval in minutes.

    Returns:
        matplotlib.figure.Figure: The generated figure.

    Raises:
        ValueError: If no usable object rows or observatory location exist.
        KeyError: If ephemeris_dataframe is omitted and object_name is not in MPC.
    """
    if ephemeris_dataframe is None:
        ephemeris_dataframe = get_object_ephemeris(
            object_name=object_name,
            obs_code=obs_code,
            obj_type=obj_type,
            reference_date=None,
            use_cache=use_cache,
        )

    if not isinstance(ephemeris_dataframe, pd.DataFrame) or ephemeris_dataframe.empty:
        raise ValueError("The object ephemeris contains no rows.")

    if reference_date is None:
        reference_date = pd.Timestamp.now(tz="UTC").date()
    elif isinstance(reference_date, str):
        reference_date = datetime.strptime(reference_date.replace("-", "/"), "%Y/%m/%d").date()
    elif hasattr(reference_date, "date"):
        reference_date = reference_date.date()

    locations = {'Y28': EarthLocation(lat=-22.5 * u.deg, lon=-43.5 * u.deg, height=0 * u.m)}
    if obs_code not in locations:
        raise ValueError(f"Observatory {obs_code!r} has no OASI/known coordinates in this function.")
    location = locations[obs_code]

    night_grid_start = datetime(reference_date.year, reference_date.month, reference_date.day, 12,
                                tzinfo=timezone.utc)
    night_grid = []
    moment = night_grid_start
    while moment <= night_grid_start + timedelta(hours=24):
        night_grid.append(moment)
        moment += timedelta(minutes=max(step_minutes, 5))

    night_start, night_end = _compute_night_bounds(
        night_grid, obs_code, float(SUN_ALT_LIMIT)
    )
    if night_start is None or night_end is None:
        raise ValueError(
            "Astronomical night could not be determined for the OASI date. "
            "Check the requested UTC date and observatory coordinates."
        )

    plot_start = night_start - timedelta(hours=1)
    plot_end = night_end + timedelta(hours=1)
    plot_times = []
    moment = plot_start
    plot_step = timedelta(minutes=max(step_minutes, 5))
    while moment <= plot_end:
        plot_times.append(moment)
        moment += plot_step

    object_altitudes_in_night = _calculate_object_altitude_curve(
        ephemeris_dataframe, plot_times, location
    )

    moon_times = plot_times
    astropy_moon_times = Time(moon_times)
    moon = get_body('moon', astropy_moon_times, location).transform_to(
        AltAz(obstime=astropy_moon_times, location=location)
    )
    moon_altitudes = moon.alt.deg

    fig, ax = plt.subplots(figsize=(15, 8), facecolor='white')
    ax.set_facecolor('#eef1f4')

    ax.axvspan(night_start, night_end, facecolor='#7f8c9a', alpha=0.58,
               label='Astronomical night (Sun <= -18 degrees)', zorder=0)
    ax.axvline(night_start, color='#344054', linestyle='--', linewidth=1.5,
               label='Astronomical night begins')
    ax.axvline(night_end, color='#344054', linestyle='--', linewidth=1.5,
               label='Astronomical night ends')

    ax.plot(plot_times, object_altitudes_in_night,
            color='#2563eb', linewidth=2.0, marker=None,
            linestyle='-', label=f"{object_name} altitude", zorder=3)
    ax.plot(moon_times, moon_altitudes, color='#4b5563', linestyle='--', linewidth=2,
            label='Moon altitude', zorder=2)
    ax.axhline(10, color='crimson', linestyle=':', linewidth=1.5,
               label='10-degree altitude limit', zorder=2)

    ax.set_ylim(0, 90)
    ax.set_xlim(plot_start, plot_end)
    ax.set_xlabel('UTC time')
    ax.set_ylabel('Altitude (degrees)')
    ax.set_title(
        f'{object_name} astronomical-night altitude - OASI ({obs_code}) - '
        f'{reference_date.strftime("%Y/%m/%d")}'
    )
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y/%m/%d %H:%M', tz=timezone.utc))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=1, tz=timezone.utc))
    ax.grid(True, alpha=0.3)
    ax.legend(loc='upper right', frameon=True, fontsize=8)
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.show()
    return fig


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
