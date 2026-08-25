import io
import re
import time

import astropy.units as u
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
from astropy.coordinates import AltAz, EarthLocation, SkyCoord
from astropy.time import Time
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Configure to show all rows and columns
pd.set_option('display.max_rows', None)
pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)
pd.set_option('display.max_colwidth', None)

# === 1. HELPER FUNCTIONS – URL AND PREVIEW TABLE DOWNLOAD ====

def _get_mpc_url(obj_type):
    """
    Returns the appropriate Minor Planet Center (MPC) URL string depending on the given object type.
    It accepts "NEOCP" (Near-Earth Object Confirmation Page) or "PCCP" (Possible Comet Confirmation Page)
    and raises an error if an invalid type is provided.
    """
    obj_type = obj_type.strip().upper()
    if obj_type == "NEOCP":
        return "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
    elif obj_type == "PCCP":
        return "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"
    else:
        raise ValueError("obj_type must be 'NEOCP' or 'PCCP'")

def _download_mpc_table(obj_type):
    """
    Fetches the HTML content from the corresponding MPC preview page, locates the data table,
    removes hidden sorting elements/checkboxes, and parses the table into a cleaned pandas DataFrame
    with standardized column names and numeric data types.
    Returns a DataFrame with basic fields (Temp Desig, R.A., Decl., V, etc.) – no ephemeris data.
    """
    url = _get_mpc_url(obj_type)
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

    # Remove hidden sorting elements and checkboxes
    for hidden in table.find_all('span', style=lambda x: x and 'display:none' in x):
        hidden.decompose()
    for chk in table.find_all('input'):
        chk.decompose()

    try:
        df_list = pd.read_html(io.StringIO(str(table)), flavor='bs4', header=0)
        if not df_list:
            return None
        df = df_list[0]
    except Exception as e:
        print(f"Error in read_html: {e}")
        return None

    df = df.dropna(axis=1, how='all')
    df.columns = [str(col).strip() for col in df.columns]

    expected_cols = [
        'Temp Desig', 'Score', 'Discovery', 'R.A.', 'Decl.', 'V',
        'Updated', 'Note', 'NObs', 'Arc', 'H', 'Not_Seen_dys'
    ]

    if len(df.columns) == len(expected_cols):
        df.columns = expected_cols
    elif len(df.columns) > len(expected_cols):
        df = df.iloc[:, :len(expected_cols)]
        df.columns = expected_cols

    for col in ['Score', 'V', 'NObs', 'Arc', 'H', 'Not_Seen_dys']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')

    if 'Temp Desig' in df.columns:
        df = df[df['Temp Desig'].notna() & (df['Temp Desig'] != '')]

    return df.reset_index(drop=True)

# === 2. SELENIUM EPHEMERIS FETCHER ====

def fetch_mpc_data(obj_type, obs_code):
    """
    Uses Selenium WebDriver in headless mode to navigate the MPC website, automatically fills out
    the ephemeris form (selecting all objects and inputting the provided observatory code),
    submits it, and scrapes the raw text output of the resulting ephemerides page.
    """
    if obj_type.strip().upper() == "NEOCP":
        url = "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
    else:
        url = "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"

    print(f"Starting ephemeris collection via Selenium for {obj_type.upper()} (Obs: {obs_code})...")

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        driver.get(url)

        # Locate and click the "All objects" radio button
        radio_button = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='radio' and @name='W' and @value='a']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", radio_button)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", radio_button)

        # Fill in the observatory code
        obs_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='obscode']"))
        )
        obs_input.clear()
        obs_input.send_keys(obs_code)

        # Click the "Get ephemerides" button
        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']"))
        )
        driver.execute_script("arguments[0].click();", submit_button)

        # Wait for the generated page to load
        time.sleep(5)

        if "No observers have reported" in driver.page_source or "No results found" in driver.page_source:
            print("No objects with ephemerides found for today.")
            return None

        body_element = driver.find_element(By.TAG_NAME, "body")
        return body_element.text

    except Exception as e:
        print(f"Error during Selenium execution: {e}")
        return None

    finally:
        driver.quit()

# === 3. EPHEMERIS TEXT PARSER (CORRECTED – INCLUDES ALTITUDES) ===

def parse_mpc_data(page_text):
    """
    Parses the raw ephemeris text obtained from the MPC.
    Returns a dict { designation: DataFrame } with columns:
        Date, UT, R.A. (J2000), Decl, Elong, V,
        Object Alt, Sun Alt, Motion min, Motion PA
    """
    if not page_text:
        return {}

    lines = page_text.split('\n')
    ephemeris_dict = {}
    i = 0
    n_lines = len(lines)

    while i < n_lines:
        line = lines[i].strip()
        # Look for the start of a new object block
        if line.startswith('Get the observations or orbits.'):
            # The object name is on the previous line
            obj_name = lines[i-1].strip().split()[0] if i > 0 else None
            i += 1
            # Now find the header line (the one containing 'Date' and 'UT' and 'R.A.')
            header_line = None
            header_idx = None
            while i < n_lines:
                if 'Date' in lines[i] and 'UT' in lines[i] and 'R.A.' in lines[i]:
                    header_line = lines[i]
                    header_idx = i
                    break
                i += 1
            if header_line is None:
                # No header found, skip this block
                continue

            # Determine column start positions from the header
            # We'll find the start of each key column by looking for the column names
            # Use a simple approach: find the positions of the column names in the header
            col_positions = {}
            # Important columns we want to extract:
            target_cols = ['Date', 'UT', 'R.A. (J2000)', 'Decl.', 'Elong.', 'V', 'Motion', 'Object', 'Sun']
            # The header may have extra spaces; we'll search for each keyword
            header_str = header_line
            for col in target_cols:
                # Find the starting index of this column name in the header
                # We need to be careful: 'R.A.' appears as 'R.A. (J2000)'
                if col == 'R.A. (J2000)':
                    search = 'R.A. (J2000)'
                else:
                    search = col
                pos = header_str.find(search)
                if pos != -1:
                    col_positions[col] = pos
                else:
                    # fallback: try to find just the first word
                    first_word = col.split()[0]
                    pos = header_str.find(first_word)
                    if pos != -1:
                        col_positions[col] = pos

            # If we couldn't find all necessary columns, skip this block
            required = ['Date', 'UT', 'R.A. (J2000)', 'Decl.', 'Elong.', 'V', 'Object', 'Sun']
            if not all(k in col_positions for k in required):
                # Maybe the header is different; let's just use a default mapping based on position
                # As a fallback, we'll use the order as they appear in the header
                # But we'll try to be smarter: we'll use the header to split into columns by spaces
                # A simpler fallback: split the header by multiple spaces
                import re
                header_parts = re.split(r'\s{2,}', header_line.strip())
                # Map each part to its starting position (cumulative sum of lengths + 1)
                # This is approximate but can work
                col_positions = {}
                start = 0
                for part in header_parts:
                    # find the position of this part in the header
                    pos = header_line.find(part, start)
                    if pos != -1:
                        col_positions[part.strip()] = pos
                        start = pos + len(part)
                # Then we need to map these parts to our desired columns
                # This is complex; we'll do a simpler approach below

            # After determining positions, we now parse the data lines
            # Move i to the first line after the header (skip blank lines)
            i = header_idx + 1
            # Skip blank lines
            while i < n_lines and lines[i].strip() == '':
                i += 1

            data_rows = []
            # Now collect data rows until we hit the next object block or end of text
            while i < n_lines:
                line_stripped = lines[i].strip()
                # If we encounter a line that starts with a year (4 digits) and contains '...' skip it?
                if line_stripped.startswith('...'):
                    i += 1
                    continue
                # Check if we reached the next object block (starts with 'Get the observations')
                if line_stripped.startswith('Get the observations'):
                    # We'll let the outer loop handle it, but we need to break out
                    # and not increment i here, because the outer loop will process it
                    break
                # Also, if the line is empty or is a header (like 'Date       UT'), skip
                if line_stripped == '' or line_stripped.startswith('Date'):
                    i += 1
                    continue
                # Check if this is a data row: starts with a year
                if re.match(r'^\d{4}', line_stripped):
                    # Extract fields using col_positions
                    # We'll try to extract each desired field by slicing the line
                    fields = {}
                    # Get the full line (original, not stripped) to preserve positions
                    full_line = lines[i]
                    # Ensure the line is long enough; pad if necessary
                    if len(full_line) < max(col_positions.values()) + 20:
                        full_line = full_line.ljust(max(col_positions.values()) + 20)
                    for col, pos in col_positions.items():
                        # Determine the end of the column by looking at the next column's start
                        next_cols = [p for p in col_positions.values() if p > pos]
                        if next_cols:
                            end = min(next_cols)
                        else:
                            end = len(full_line)
                        raw = full_line[pos:end].strip()
                        fields[col] = raw
                    # Now extract the specific values we need
                    date = fields.get('Date', '').strip()
                    ut = fields.get('UT', '').strip()
                    # If there is an asterisk in the UT field, remove it (it's just a marker)
                    ut = ut.replace('*', '').strip()
                    ra = fields.get('R.A. (J2000)', '').strip()
                    decl = fields.get('Decl.', '').strip()
                    elong = fields.get('Elong.', '').strip()
                    v_mag = fields.get('V', '').strip()
                    motion = fields.get('Motion', '').strip()
                    # motion is like "1.58  099.6" -> motion min and PA
                    motion_parts = motion.split()
                    if len(motion_parts) >= 2:
                        mot_min = motion_parts[0]
                        mot_pa = motion_parts[1]
                    else:
                        mot_min = motion
                        mot_pa = ''
                    # Object column: contains two numbers (Azi and Alt)
                    obj_str = fields.get('Object', '').strip()
                    obj_parts = obj_str.split()
                    if len(obj_parts) >= 2:
                        obj_alt = obj_parts[1]  # second is Alt
                    else:
                        obj_alt = ''
                    # Sun column: contains at least Alt (maybe also something else)
                    sun_str = fields.get('Sun', '').strip()
                    sun_parts = sun_str.split()
                    if len(sun_parts) >= 1:
                        sun_alt = sun_parts[0]  # usually the Alt is first
                    else:
                        sun_alt = ''

                    # Build row
                    row = [date, ut, ra, decl, elong, v_mag, obj_alt, sun_alt, mot_min, mot_pa]
                    data_rows.append(row)

                i += 1

            # After collecting data rows, create DataFrame
            if data_rows:
                column_names = [
                    "Date", "UT", "R.A. (J2000)", "Decl", "Elong", "V",
                    "Object Alt", "Sun Alt", "Motion min", "Motion PA"
                ]
                df = pd.DataFrame(data_rows, columns=column_names)
                ephemeris_dict[obj_name] = df

            # Continue loop; i is already at the next position (either at a new object block or end)
            continue

        i += 1

    return ephemeris_dict

# === 4. VISIBILITY FILTER ====

def filter_visible_objects(ephem_dict, altitude_min=10, time_min_minutes=30):
    """
    Takes a dictionary of ephemeris DataFrames (as produced by parse_mpc_data) and filters
    objects that are observable from the given site. For each object, it identifies continuous
    windows where Object Alt >= altitude_min and Sun Alt <= -18° (astronomical night).
    It returns a summary DataFrame containing:
        Temp Desig, R.A., Decl., V, Visible_Minutes, Max_Alt, Max_Alt_Time_UTC.
    """
    if not ephem_dict:
        return pd.DataFrame()

    summary = []

    for obj_name, df in ephem_dict.items():
        df_proc = df.copy()

        # Clean the UT column (remove spaces/dots and pad to 4 digits)
        ut_clean = df_proc['UT'].astype(str).str.replace(r'[\s\.]', '', regex=True).str.zfill(4)
        df_proc['Datetime_UTC'] = pd.to_datetime(
            df_proc['Date'].astype(str) + ' ' + ut_clean,
            format='%Y %m %d %H%M',
            errors='coerce'
        )

        # Convert altitude columns to numeric
        df_proc['Object Alt'] = pd.to_numeric(df_proc['Object Alt'], errors='coerce')
        df_proc['Sun Alt'] = pd.to_numeric(df_proc['Sun Alt'], errors='coerce')

        # Drop rows with missing essential data
        df_proc = df_proc.dropna(subset=['Datetime_UTC', 'Object Alt', 'Sun Alt', 'R.A. (J2000)', 'Decl', 'V'])
        if df_proc.empty:
            continue

        # Apply visibility criteria: object above minimum altitude and Sun below -18°
        df_vis = df_proc[(df_proc['Object Alt'] >= altitude_min) & (df_proc['Sun Alt'] <= -18)].copy()
        if df_vis.empty:
            continue

        # Identify continuous visibility windows (gap > 2 hours separates windows)
        df_vis['Window_ID'] = (df_vis['Datetime_UTC'].diff() > pd.Timedelta(hours=2)).cumsum()

        total_min = 0
        best_idx = None

        for _, group in df_vis.groupby('Window_ID'):
            duration = (group['Datetime_UTC'].max() - group['Datetime_UTC'].min()).total_seconds() / 60.0
            if duration >= time_min_minutes:
                total_min += duration
                # Find the time of maximum altitude within this window
                idx_max = group['Object Alt'].idxmax()
                if best_idx is None or group.loc[idx_max, 'Object Alt'] > df_vis.loc[best_idx, 'Object Alt']:
                    best_idx = idx_max

        if best_idx is not None:
            summary.append({
                'Temp Desig': obj_name,
                'R.A.': df_vis.loc[best_idx, 'R.A. (J2000)'],
                'Decl.': df_vis.loc[best_idx, 'Decl'],
                'V': df_vis.loc[best_idx, 'V'],
                'Visible_Minutes': int(total_min),
                'Max_Alt': round(df_vis.loc[best_idx, 'Object Alt'], 1),
                'Max_Alt_Time_UTC': df_vis.loc[best_idx, 'Datetime_UTC']
            })

    return pd.DataFrame(summary)

# === 5. MAIN USER-FACING FUNCTIONS ===

def analyze_ephemeris_objects(obs_code, obj_type, altitude_min=10, duration_min=30, plot=True):
    """
    Master function for a full analysis:
        - Fetches ephemeris data via Selenium.
        - Filters visible objects using filter_visible_objects.
        - Prints a summary table (sorted by maximum altitude).
        - Optionally plots altitude curves for all visible objects.
    Returns the summary DataFrame of visible objects.
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

    # Sort by maximum altitude (highest first)
    df_visible = df_visible.sort_values('Max_Alt', ascending=False)

    print("\n=== VISIBLE OBJECTS ===")
    cols = ['Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes', 'Max_Alt', 'Max_Alt_Time_UTC']
    print(df_visible[cols].to_string(index=False))

    if plot:
        plt.figure(figsize=(12, 6))
        now_dt = pd.to_datetime(Time.now().datetime)

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
            plt.plot(times_hours, df_obj['Object Alt'], label=obj, marker='.', linestyle='-', linewidth=1)

        plt.axhline(altitude_min, color='red', linestyle='--', label=f'Limit {altitude_min}°')
        plt.ylim(0, 90)
        plt.xlabel('Hours from now (UTC)')
        plt.ylabel('Altitude (°)')
        plt.title(f'Altitude curves for visible objects (obs. {obs_code})')
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.show()

    return df_visible

def process_mpc_data(obs_code, obj_type, interactive_mode=True):
    """
    Simplified wrapper that calls analyze_ephemeris_objects without plotting,
    and then allows interactive selection of an object to view its full details.
    """
    df_visible = analyze_ephemeris_objects(obs_code, obj_type, plot=False)
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

# === 6. DEPRECATED / OPTIONAL FUNCTIONS (KEPT FOR REFERENCE, NOT ACTIVELY USED) ===
"""
The functions below are not called anywhere in the main workflow, but are preserved
here in case they are needed for other purposes.

# def parse_ra_to_deg(ra_series):
#     """
#     Converts a pandas Series of Right Ascension (RA) strings formatted as 'HH MM.m' or 'HH MM SS.s'
#     into decimal degrees. It extracts hours, minutes, and seconds using regular expressions and
#     performs the necessary mathematical conversions.
#     """
#     pattern = r'^(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)(?:\s+(\d{1,2}(?:\.\d+)?))?'
#     extracted = ra_series.str.extract(pattern, expand=True)
#     hours = pd.to_numeric(extracted[0], errors='coerce').fillna(0)
#     minutes = pd.to_numeric(extracted[1], errors='coerce').fillna(0)
#     seconds = pd.to_numeric(extracted[2], errors='coerce').fillna(0)
#     hours_dec = hours + (minutes / 60) + (seconds / 3600)
#     return hours_dec * 15.0

# def parse_dec_to_deg(dec_series):
#     """
#     Converts a pandas Series of Declination (Dec) strings formatted as '±DD MM' or '±DD MM SS'
#     into decimal degrees. It handles positive and negative signs and calculates the absolute
#     decimal value based on degrees, minutes, and seconds.
#     """
#     pattern = r'^([+-]?)\s*(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)(?:\s+(\d{1,2}(?:\.\d+)?))?'
#     extracted = dec_series.str.extract(pattern, expand=True)
#     sign = extracted[0].map({'': 1, '+': 1, '-': -1}).fillna(1).astype(float)
#     degrees = pd.to_numeric(extracted[1], errors='coerce').fillna(0)
#     minutes = pd.to_numeric(extracted[2], errors='coerce').fillna(0)
#     seconds = pd.to_numeric(extracted[3], errors='coerce').fillna(0)
#     dec_abs = degrees + (minutes / 60) + (seconds / 3600)
#     return sign * dec_abs

# def get_observatory_location(obs_code):
#     """
#     Retrieves the geographical coordinates (longitude and latitude) of a specific observatory
#     by fetching its MPC code from the official Minor Planet Center observatory list.
#     Returns the location as an astropy EarthLocation object.
#     """
#     url_obs = "https://minorplanetcenter.net/iau/lists/ObsCodes.html"
#     try:
#         r = requests.get(url_obs)
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
#     """
#     A high-level wrapper function that downloads the raw MPC preview table for a given object type,
#     prints the total number of downloaded objects to the console, and returns the resulting
#     pandas DataFrame.
#     """
#     df = _download_mpc_table(obj_type)
#     if df is None or df.empty:
#         print("No data obtained.")
#         return None
#     print(f"Downloaded {len(df)} objects from page {obj_type.upper()}.")
#     return df
