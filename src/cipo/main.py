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
    """
    Master function: fetch, parse, filter, print summary, and optionally plot.
    All parameters are optional; defaults are taken from config.py.
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
    """
    Simplified wrapper (no plot) with optional interactive mode.
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
# Functions below are commented out to avoid polluting the namespace,


# def parse_ra_to_deg(ra_series):
#     pattern = r'^(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)(?:\s+(\d{1,2}(?:\.\d+)?))?'
#     extracted = ra_series.str.extract(pattern, expand=True)
#     hours = pd.to_numeric(extracted[0], errors='coerce').fillna(0)
#     minutes = pd.to_numeric(extracted[1], errors='coerce').fillna(0)
#     seconds = pd.to_numeric(extracted[2], errors='coerce').fillna(0)
#     hours_dec = hours + (minutes / 60) + (seconds / 3600)
#     return hours_dec * 15.0

# def parse_dec_to_deg(dec_series):
#     pattern = r'^([+-]?)\s*(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)(?:\s+(\d{1,2}(?:\.\d+)?))?'
#     extracted = dec_series.str.extract(pattern, expand=True)
#     sign = extracted[0].map({'': 1, '+': 1, '-': -1}).fillna(1).astype(float)
#     degrees = pd.to_numeric(extracted[1], errors='coerce').fillna(0)
#     minutes = pd.to_numeric(extracted[2], errors='coerce').fillna(0)
#     seconds = pd.to_numeric(extracted[3], errors='coerce').fillna(0)
#     dec_abs = degrees + (minutes / 60) + (seconds / 3600)
#     return sign * dec_abs

# def get_observatory_location(obs_code):
#     import requests
#     from astropy.coordinates import EarthLocation
#     import astropy.units as u
#     url_obs = "https://minorplanetcenter.net/iau/lists/ObsCodes.html"
#     try:
#         r = requests.get(url_obs, timeout=15)
#         r.raise_for_status()
#     except Exception:
#         print("Error accessing observatory list")
#         return None
#     for line in r.text.split('\n'):
#         if line.startswith(obs_code):
#             parts = line.split()
#             if len(parts) >= 4:
#                 long_deg = float(parts[1])
#                 cos_phi = float(parts[2])
#                 sin_phi = float(parts[3])
#                 lat_rad = np.arctan2(sin_phi, cos_phi)
#                 lat_deg = np.degrees(lat_rad)
#                 return EarthLocation(lat=lat_deg * u.deg, lon=long_deg * u.deg, height=0 * u.m)
#     print(f"Code {obs_code} not found.")
#     return None

# def mpc_objects(obj_type):
#     df = _download_mpc_table(obj_type)
#     if df is None or df.empty:
#         print("No data obtained.")
#         return None
#     print(f"Downloaded {len(df)} objects from page {obj_type.upper()}.")
#     return df

# Para manter compatibilidade com importações antigas, exponha funções principais
#__all__ = [
#    '_download_mpc_table',
#    '_get_mpc_url',  # noqa: F822
#    'analyze_ephemeris_objects',
#    'fetch_mpc_data',
#    'filter_visible_objects',
#    'parse_mpc_data',
#    'process_mpc_data'
#]