import math
import re
from datetime import datetime, timedelta, timezone

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .config import DEFAULT_ALT_MIN, DEFAULT_DUR_MIN, DEFAULT_OBJ_TYPE, DEFAULT_OBS_CODE
from .downloader import fetch_mpc_data
from .parser import parse_mpc_data

# === Functions for astronomical calculations ===

def get_observatory_coords(iau_code):
    import urllib.request
    url = "https://www.minorplanetcenter.net/iau/lists/ObsCodes.html"
    try:
        with urllib.request.urlopen(url) as response:
            html = response.read().decode('utf-8')
        match = re.search(f"^{re.escape(iau_code)}.*", html, re.MULTILINE)
        if not match:
            print(f"Código {iau_code} não encontrado.")
            return None
        parts = match.group(0).split(maxsplit=4)
        lon = float(parts[1])
        cos_lat = float(parts[2])
        sin_lat = float(parts[3])
        lat = math.degrees(math.atan2(sin_lat, cos_lat))
        lon = lon if lon <= 180 else lon - 360
        return lat, lon
    except Exception as e:
        print(f"Erro ao buscar coordenadas: {e}")
        return None

def hms_para_graus(ra_str):
    """Converte RA in 'HH MM SS.s' for degrees."""
    try:
        parts = ra_str.strip().split()
        if len(parts) != 3:
            return None
        h, m, s = map(float, parts)
        return (h + m/60 + s/3600) * 15
    except Exception as e:
        return None

def dms_para_graus(dec_str):
    """Converte Dec in '±DD MM SS.s' for degrees."""
    try:
        s = dec_str.strip()
        sign = -1 if s.startswith('-') else 1
        if s.startswith('+') or s.startswith('-'):
            s = s[1:]
        parts = s.split()
        if len(parts) != 3:
            return None
        d, m, s = map(float, parts)
        return sign * (abs(d) + m/60 + s/3600)
    except Exception as e:
        return None

def calcular_altitude_manual(ra_deg, dec_deg, lat_deg, lon_deg, utc_dt):
    if ra_deg is None or dec_deg is None:
        return None
    jd = utc_dt.timestamp() / 86400.0 + 2440587.5
    d = jd - 2451545.0
    gmst = 18.697374558 + 24.06570982441908 * d
    lst = (gmst + (lon_deg / 15)) % 24
    ha_rad = math.radians((lst - (ra_deg / 15)) * 15)
    lat_rad = math.radians(lat_deg)
    dec_rad = math.radians(dec_deg)
    sin_alt = (math.sin(dec_rad) * math.sin(lat_rad) +
               math.cos(dec_rad) * math.cos(lat_rad) * math.cos(ha_rad))
    sin_alt = max(-1.0, min(1.0, sin_alt))
    return math.degrees(math.asin(sin_alt))

def get_celestial_coords_manual(body_name, jd):
    n = jd - 2451545.0
    eclob = 23.439 - 0.0000004 * n
    eclob_rad = math.radians(eclob)
    if body_name == 'sun':
        L = (280.460 + 0.9856474 * n) % 360
        g = math.radians((357.528 + 0.9856003 * n) % 360)
        eclon = L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)
        eclat = 0
    elif body_name == 'moon':
        L = (218.32 + 13.176396 * n) % 360
        M = (134.96 + 13.064993 * n) % 360
        F = (93.27 + 13.229350 * n) % 360
        eclon = L + 6.29 * math.sin(math.radians(M))
        eclat = 5.13 * math.sin(math.radians(F))
    else:
        return None, None
    eclon_rad = math.radians(eclon)
    eclat_rad = math.radians(eclat)
    ra_rad = math.atan2(
        math.sin(eclon_rad) * math.cos(eclob_rad) - math.tan(eclat_rad) * math.sin(eclob_rad),
        math.cos(eclon_rad)
    )
    dec_rad = math.asin(
        math.sin(eclat_rad) * math.cos(eclob_rad) +
        math.cos(eclat_rad) * math.sin(eclob_rad) * math.sin(eclon_rad)
    )
    return math.degrees(ra_rad) % 360, math.degrees(dec_rad)

# === Main Function to Plot Visibility ===

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
    """
    Plot visibility of objects from MPC data for a given observatory code and object type.
    """
    # --- 1) Get data ---
    print(f"Getting  {obj_type} (obs: {obs_code})...")
    text = fetch_mpc_data(obj_type, obs_code)
    if not text:
        print("Failed to fetch data.")
        return pd.DataFrame(), []

    ephem_dict = parse_mpc_data(text)
    if not ephem_dict:
        print("No data parsed.")
        return pd.DataFrame(), []

    print(f" {len(ephem_dict)} Objects.")

    # --- 2) Get observatory coordinates ---
    coords = get_observatory_coords(obs_code)
    if not coords:
        print(f"Observatory {obs_code} not found.")
        return pd.DataFrame(), []
    lat_deg, lon_deg = coords
    print(f"Observatory: {obs_code}  Lat={lat_deg:.4f}° Lon={lon_deg:.4f}°")

    # --- 3) Define time grid ---
    first_obj = list(ephem_dict.keys())[0]
    first_date_str = ephem_dict[first_obj]['Date'].iloc[0]
    try:
        data_ref = datetime.strptime(first_date_str, '%Y %m %d')
    except:
        data_ref = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    start_time = data_ref.replace(hour=start_hour, minute=0, second=0, microsecond=0, tzinfo=timezone.utc)
    n_steps = int(n_hours * 60 / step_minutes) + 1
    time_points = [start_time + timedelta(minutes=step_minutes * i) for i in range(n_steps)]
    print(f"Grade: {len(time_points)} pontos de {start_time.strftime('%H:%M')} a {time_points[-1].strftime('%H:%M')} UTC")

    # --- 4) Convert RA/Dec to Altitude for each object at each time point ---
    use_astropy = True
    try:
        from astropy.coordinates import SkyCoord, EarthLocation, AltAz
        from astropy.time import Time
        import astropy.units as u
        location = EarthLocation(lat=lat_deg*u.deg, lon=lon_deg*u.deg, height=0*u.m)
        time_utc = Time(time_points)
    except ImportError:
        use_astropy = False
        print("Astropy not available, using manual calculations for altitudes.")

    altitudes_dict = {}
    for obj_name, df in ephem_dict.items():
        ra_str = df['R.A. (J2000)'].iloc[0].strip()
        dec_str = df['Decl'].iloc[0].strip()
        # Converte para graus
        ra_deg = hms_para_graus(ra_str)
        dec_deg = dms_para_graus(dec_str)
        if ra_deg is None or dec_deg is None:
            print(f"  Object {obj_name}: error in RA/Dec conversion")
            continue

        if use_astropy:
            try:
                coord = SkyCoord(ra=ra_deg*u.deg, dec=dec_deg*u.deg)
                altaz = coord.transform_to(AltAz(obstime=time_utc, location=location))
                altitudes_dict[obj_name] = altaz.alt.deg
            except Exception as e:
                print(f"  Object {obj_name}: error in astropy, using manual: {e}")
                # Fallback manual
                alts = [calcular_altitude_manual(ra_deg, dec_deg, lat_deg, lon_deg, t) for t in time_points]
                altitudes_dict[obj_name] = [a if a is not None else -999 for a in alts]
        else:
            alts = [calcular_altitude_manual(ra_deg, dec_deg, lat_deg, lon_deg, t) for t in time_points]
            altitudes_dict[obj_name] = [a if a is not None else -999 for a in alts]

    if not altitudes_dict:
        print("ERROR: No altitudes calculated.")
        return pd.DataFrame(), time_points

    print(f"Altitudes calculated for {len(altitudes_dict)} objects.")

    # --- 5) Filter ---
    if plot_all:
        filtered_objects = altitudes_dict
        print("Plotting all objects.")
    else:
        min_steps = int(dur_min / step_minutes) if step_minutes > 0 else 1
        filtered_objects = {}
        for obj, alts in altitudes_dict.items():
            consecutive = 0
            for alt in alts:
                if alt >= alt_min:
                    consecutive += 1
                    if consecutive >= min_steps:
                        filtered_objects[obj] = alts
                        break
                else:
                    consecutive = 0
        print(f"{len(filtered_objects)} objects meet the criteria (Alt ≥ {alt_min}° for ≥ {dur_min} min).")

    if not filtered_objects:
        print("No objects to plot. Try plot_all=True.")
        return pd.DataFrame(), time_points

    # --- 6) Summary ---
    rows = []
    for obj, alts in filtered_objects.items():
        if not alts:
            continue
        max_alt = max(alts)
        idx_max = np.argmax(alts)
        max_time = time_points[idx_max]
        rows.append({
            'Temp Desig': obj,
            'Max_Alt': round(max_alt, 1),
            'Max_Alt_Time_UTC': max_time
        })
    df_visible = pd.DataFrame(rows)

    # --- 7) Plotagem ---
    print("Generating plot...")
    fig, ax = plt.subplots(figsize=(15, 7))

    for obj, alts in filtered_objects.items():
        ax.plot(time_points, alts, color='steelblue', linestyle='-', linewidth=1.2, alpha=0.6, marker='.')

    if not plot_all:
        ax.axhline(alt_min, color='red', linestyle='--', linewidth=2, label=f'Limit {alt_min}°')

    # Sol e Lua (opcional)
    if plot_sun_moon:
        print("Calculating Sun and Moon altitudes...")
        jd0 = time_points[0].timestamp() / 86400.0 + 2440587.5
        sun_alts, moon_alts = [], []
        for i, t in enumerate(time_points):
            jd = jd0 + i * (step_minutes / 1440.0)
            sun_ra, sun_dec = get_celestial_coords_manual('sun', jd)
            moon_ra, moon_dec = get_celestial_coords_manual('moon', jd)
            sun_alt = calcular_altitude_manual(sun_ra, sun_dec, lat_deg, lon_deg, t)
            moon_alt = calcular_altitude_manual(moon_ra, moon_dec, lat_deg, lon_deg, t)
            sun_alts.append(sun_alt if sun_alt is not None else -999)
            moon_alts.append(moon_alt if moon_alt is not None else -999)

        ax.plot(time_points, sun_alts, color='gold', linestyle='--', linewidth=2, label='Sun')
        ax.plot(time_points, moon_alts, color='gray', linestyle='--', linewidth=2, label='Moon')

        # Sunrise/Sunset
        for i in range(1, len(sun_alts)):
            if sun_alts[i-1] < 0 and sun_alts[i] >= 0:
                ax.axvline(time_points[i], color='orange', linestyle=':', linewidth=1.5, label='Sunrise')
            elif sun_alts[i-1] > 0 and sun_alts[i] <= 0:
                ax.axvline(time_points[i], color='red', linestyle=':', linewidth=1.5, label='Sunset ')

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

    return df_visible, time_points