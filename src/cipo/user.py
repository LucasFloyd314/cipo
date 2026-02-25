import io
import re
import time
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from astropy.time import Time
import astropy.units as u
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager


# Configure to show all rows and columns
pd.set_option('display.max_rows', None)      # shows all rows
pd.set_option('display.max_columns', None)   # shows all columns
pd.set_option('display.width', None)         # adjusts width automatically
pd.set_option('display.max_colwidth', None)  # shows full content of each cell

# ----------------------------------------------------------------------
# Internal auxiliary functions
# ----------------------------------------------------------------------

def _get_mpc_url(page_type):
    """Returns the correct URL for NEOCP or PCCP."""
    page_type = page_type.strip().upper()
    if page_type == "NEOCP":
        return "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
    elif page_type == "PCCP":
        return "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"
    else:
        raise ValueError("page_type must be 'NEOCP' or 'PCCP'")

def _download_mpc_table(page_type):
    """
    Downloads the HTML table from the page, uses pandas to read the table,
    removes empty columns and adjusts names to the expected pattern.
    Returns a clean DataFrame.
    """
    url = _get_mpc_url(page_type)
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers)
        resp.raise_for_status()
    except Exception as e:
        print(f"Download error: {e}")
        return None

    soup = BeautifulSoup(resp.content, 'html.parser')
    table = soup.find('table', {'class': 'tablesorter'})
    if not table:
        print("Table not found on the page.")
        return None

    # Remove spans with display:none (sorting data) and checkboxes
    for hidden in table.find_all('span', style=lambda x: x and 'display:none' in x):
        hidden.decompose()
    for chk in table.find_all('input'):
        chk.decompose()

    # Use pandas to read the HTML table (the first row is the header)
    try:
        df_list = pd.read_html(io.StringIO(str(table)), flavor='bs4', header=0)
        if not df_list:
            print("Failed to read the table with pandas.")
            return None
        df = df_list[0]
    except Exception as e:
        print(f"Error in read_html: {e}")
        return None

    # Remove columns that are completely empty (all rows NaN)
    df = df.dropna(axis=1, how='all')

    # Clean column names
    df.columns = [str(col).strip() for col in df.columns]

    # Expected columns (observed on the page)
    expected_cols = [
        'Temp Desig', 'Score', 'Discovery', 'R.A.', 'Decl.', 'V',
        'Updated', 'Note', 'NObs', 'Arc', 'H', 'Not_Seen_dys'
    ]

    # If the number of columns matches, rename to the standard (ignoring order)
    if len(df.columns) == len(expected_cols):
        df.columns = expected_cols
    elif len(df.columns) > len(expected_cols):
        # There may be extra empty columns; we keep the first N
        df = df.iloc[:, :len(expected_cols)]
        df.columns = expected_cols
    else:
        print(f"Unexpected number of columns: {len(df.columns)}. Proceeding with original names.")

    # Convert numeric columns
    for col in ['Score', 'V', 'NObs', 'Arc', 'H', 'Not_Seen_dys']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    # Remove rows without an identifier
    if 'Temp Desig' in df.columns:
        df = df[df['Temp Desig'].notna() & (df['Temp Desig'] != '')]
    else:
        print("Warning: 'Temp Desig' column not found.")

    return df.reset_index(drop=True)

# ----------------------------------------------------------------------
# Public functions
# ----------------------------------------------------------------------

def get_observatory_location(iau_code):
    """Obtains observatory coordinates from the MPC code."""
    url_obs = "https://minorplanetcenter.net/iau/lists/ObsCodes.html"
    try:
        r = requests.get(url_obs)
        r.raise_for_status()
    except Exception as e:
        print(f"Error accessing observatory list: {e}")
        return None

    for line in r.text.split('\n'):
        if line.startswith(iau_code):
            parts = line.split()
            if len(parts) >= 4:
                long_deg = float(parts[1])
                cos_phi = float(parts[2])
                sin_phi = float(parts[3])
                lat_rad = np.arctan2(sin_phi, cos_phi)
                lat_deg = np.degrees(lat_rad)
                return EarthLocation(lat=lat_deg * u.deg,
                                     lon=long_deg * u.deg,
                                     height=0 * u.m)
    print(f"Code {iau_code} not found.")
    return None

def filter_visible_objects(df, location, altitude_min=10, time_min_minutes=30):
    """
    Filters visible objects based on minimum altitude and minimum time.
    Vectorized version with safety fallback.
    """
    # --- Identify RA and Dec columns ---
    ra_col = None
    dec_col = None
    for col in df.columns:
        col_clean = re.sub(r'[^a-zA-Z]', '', col).lower()
        if 'ra' in col_clean:
            ra_col = col
        elif 'dec' in col_clean:
            dec_col = col
    if ra_col is None or dec_col is None:
        print("Error: RA and/or Dec columns not found.")
        return pd.DataFrame()

    # --- Parse functions adapted to "HH MM.m" and "±DD MM" format ---
    def _parse_ra_to_deg(ra_series):
        pattern = r'^(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)'
        extracted = ra_series.str.extract(pattern, expand=True)
        hours = pd.to_numeric(extracted[0], errors='coerce')
        minutes = pd.to_numeric(extracted[1], errors='coerce')
        hours_dec = hours + minutes/60
        return hours_dec * 15.0   # degrees

    def _parse_dec_to_deg(dec_series):
        pattern = r'^([+-]?)\s*(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)'
        extracted = dec_series.str.extract(pattern, expand=True)
        sign = extracted[0].map({'': 1, '+': 1, '-': -1}).fillna(1).astype(float)
        degrees = pd.to_numeric(extracted[1], errors='coerce')
        minutes = pd.to_numeric(extracted[2], errors='coerce')
        dec_abs = degrees + minutes/60
        return sign * dec_abs

    # Apply parsing
    ra_deg = _parse_ra_to_deg(df[ra_col].astype(str))
    dec_deg = _parse_dec_to_deg(df[dec_col].astype(str))

    # Remove rows with invalid parsing
    valid = ra_deg.notna() & dec_deg.notna()
    if not valid.all():
        n_inv = (~valid).sum()
        print(f"Warning: {n_inv} objects ignored due to invalid coordinate format.")
        df = df[valid].copy()
        ra_deg = ra_deg[valid]
        dec_deg = dec_deg[valid]

    if df.empty:
        return pd.DataFrame()

    # Create coordinates
    coords = SkyCoord(ra=ra_deg.values * u.deg, dec=dec_deg.values * u.deg)

    # Define times (24h in 15 min steps)
    current_time = Time.now()
    step_min = 15
    n_steps = int(24 * 60 / step_min) + 1
    deltas = np.linspace(0, 24, n_steps) * u.hour
    times = current_time + deltas

    # --- Vectorized transformation with explicit broadcasting ---
    # Reshape obstime to (n_steps, 1) to force correct broadcasting
    frame_altaz = AltAz(obstime=times.reshape(-1, 1), location=location)

    try:
        altaz = coords.transform_to(frame_altaz)
        altitudes = altaz.alt.degree   # shape (n_steps, n_objects)
    except Exception as e:
        # Fallback: loop over times (slower, but compatible)
        print(f"Vectorized transformation failed: {e}. Using fallback loop (may be slower).")
        altitudes = np.zeros((n_steps, len(df)))
        for i, t in enumerate(times):
            frame_t = AltAz(obstime=t, location=location)
            altaz_t = coords.transform_to(frame_t)
            altitudes[i, :] = altaz_t.alt.degree

    # Statistics
    above_limit = altitudes > altitude_min
    visible_points = np.sum(above_limit, axis=0)
    max_alt = np.max(altitudes, axis=0)

    # Minimum time filter
    min_points = int(np.ceil(time_min_minutes / step_min))
    mask = visible_points >= min_points

    if not np.any(mask):
        return pd.DataFrame()

    df_result = df.iloc[mask].copy()
    df_result['Visible_Minutes'] = visible_points[mask] * step_min
    df_result['Max_Alt'] = np.round(max_alt[mask], 1)

    return df_result

def mpc_objects(obj_type):
    """
    Downloads the general table (NEOCP or PCCP) and returns the clean DataFrame.
    The user can display it in the notebook by calling the returned variable.
    """
    df = _download_mpc_table(obj_type)
    if df is None or df.empty:
        print("No data obtained.")
        return None
    print(f"Downloaded {len(df)} objects from page {obj_type.upper()}.")
    return df

def process_mpc_data(observatory_code, page_type="NEOCP", interactive_mode=True):
    """
    Simplified version that downloads, filters (alt >10°, >30 min) and enters interactive mode.
    Maintained for compatibility.
    """
    df_raw = _download_mpc_table(page_type)
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()

    local_obs = get_observatory_location(observatory_code)
    if local_obs is None:
        return pd.DataFrame()

    print(f"\nTotal objects downloaded: {len(df_raw)}")
    print(f"Filtering objects with Alt > 10° for ~30 min at {observatory_code}...")
    df_filtered = filter_visible_objects(df_raw, local_obs,
                                         altitude_min=10, time_min_minutes=30)

    if df_filtered.empty:
        print("\nNo visible objects with current criteria.")
        return df_filtered

    df_filtered = df_filtered.sort_values(by='Max_Alt', ascending=False)
    cols = ['Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes', 'Max_Alt']
    final_cols = [c for c in cols if c in df_filtered.columns]
    print("\n" + "=" * 60)
    print(f"VISIBLE OBJECTS AT {observatory_code}")
    print("=" * 60)
    with pd.option_context('display.max_rows', None):
        print(df_filtered[final_cols].to_string(index=False))

    if interactive_mode:
        while True:
            print("\n" + "-" * 60)
            target = input("Enter 'Temp Desig' to see details (or '0' to exit): ").strip()
            if target == '0':
                break
            obj_row = df_filtered[df_filtered['Temp Desig'] == target]
            if not obj_row.empty:
                print(f"\nOBJECT DETAILS: {target}")
                print("=" * 30)
                print(obj_row.iloc[0])
            else:
                print(f"Object '{target}' not found.")
    return df_filtered

def fetch_mpc_data(which='neocp', obscode='Y28'):
    """Obtains the detailed ephemeris page via Selenium."""
    MPC_URL = _get_mpc_url(which)

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()),
                              options=chrome_options)
    try:
        print(f"Starting ephemeris collection from page {which.upper()}...")
        driver.get(MPC_URL)

        radio_button = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='radio' and @name='W' and @value='a']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", radio_button)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", radio_button)

        obs_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='obscode']"))
        )
        obs_input.clear()
        obs_input.send_keys(obscode)

        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']"))
        )
        driver.execute_script("arguments[0].click();", submit_button)
        time.sleep(5)

        if "No observers have reported any observations" in driver.page_source or \
           "No results found" in driver.page_source:
            print("No objects found with ephemerides.")
            return None

        body_element = driver.find_element(By.TAG_NAME, "body")
        page_text = body_element.text
        print("Ephemeris collected successfully.")
        return page_text
    except Exception as e:
        print(f"Error during ephemeris collection: {e}")
        return None
    finally:
        driver.quit()

def parse_mpc_data(page_text):
    """Processes the ephemeris page text and returns a dict of DataFrames."""
    lines = page_text.splitlines()
    blocks = {}
    current_object, current_block = None, []

    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if line_stripped and (i + 1 < len(lines)) and ("Get the observations" in lines[i+1]):
            if current_object and current_block:
                blocks[current_object] = current_block
            current_object, current_block = line_stripped, []
            continue
        if current_object:
            if "Get the observations" not in line_stripped and line_stripped:
                current_block.append(line_stripped)

    if current_object and current_block:
        blocks[current_object] = current_block

    column_names = [
        "Date", "UT", "R.A. (J2000)", "Decl", "Elong", "V",
        "Motion min", "Motion PA", "Object Azi", "Object Alt",
        "Sun Alt", "Moon Phase", "Moon Dist", "Moon Alt"
    ]

    dataframes = {}
    for obj, block_lines in blocks.items():
        rows = []
        for line in block_lines:
            if re.match(r'^\d{4}', line.strip()):
                tokens = line.split()
                if len(tokens) >= 20:
                    rows.append([
                        " ".join(tokens[0:3]),   # Date
                        tokens[3],                # UT
                        " ".join(tokens[4:7]),    # R.A.
                        " ".join(tokens[7:10]),   # Decl
                        tokens[10], tokens[11], tokens[12], tokens[13],
                        tokens[14], tokens[15], tokens[16], tokens[17],
                        tokens[18], tokens[19]
                    ])
        if rows:
            df = pd.DataFrame(rows, columns=column_names)
            for col in ['V', 'Object Alt', 'Sun Alt', 'Moon Alt']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            dataframes[obj] = df
    return dataframes