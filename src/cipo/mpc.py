# src/cipo/neo.py

import io
import re
import time
from bs4 import BeautifulSoup
import pandas as pd
import requests
import numpy as np
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

NEOCP_URL = "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
PCCP_URL = "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"

def process_mpc_data(observatory_code, page_type="NEOCP", interactive_mode=True):
    """
    Downloads, processes, and filters MPC data (NEOCP or PCCP).
    
    Args:
        observatory_code (str): Observatory code (e.g., "Y28").
        page_type (str): "NEOCP" or "PCCP".
        interactive_mode (bool): If True, activates the loop to view details.
        
    Returns:
        pd.DataFrame: The filtered DataFrame with visible objects.
    """
    
    # 1. URL Configuration
    page_type = page_type.strip().upper()
    url = "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html" if page_type == "NEOCP" else "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"

    print(f"--- Downloading data from: {page_type} ---")
    headers = {"User-Agent": "Mozilla/5.0"}
    df_raw = None

    # 2. Download and Parsing
    try:
        resp = requests.get(url, headers=headers)
        soup = BeautifulSoup(resp.content, 'html.parser')
        table_html = soup.find('table', {'class': 'tablesorter'})
        
        if table_html:
            # Clean hidden elements and checkboxes
            for hidden in table_html.find_all('span', style=lambda x: x and 'display:none' in x):
                hidden.decompose()
            for chk in table_html.find_all('input'):
                chk.decompose()
            
            # Read into DataFrame
            df_raw = pd.read_html(io.StringIO(str(table_html)), flavor='bs4')[0]
            df_raw.columns = [c.strip() for c in df_raw.columns]
            df_raw = df_raw.dropna(axis=1, how='all')
        else:
            print("HTML table not found.")

    except Exception as e:
        print(f"Download error: {e}")
        return pd.DataFrame() # Return empty DataFrame on error

    df_filtered = pd.DataFrame() 

    # 3. Filtering Logic
    if df_raw is not None and not df_raw.empty:
        # Note: Assumes get_observatory_location and filter_visible_objects 
        # are defined in your global scope or imported.
        local_obs = get_observatory_location(observatory_code)
        
        if local_obs is not None:
            print(f"\nTotal objects downloaded: {len(df_raw)}")
            print(f"Filtering objects with Alt > 10° for ~30 min at {observatory_code}...")
            
            df_filtered = filter_visible_objects(df_raw, local_obs)
            
            if not df_filtered.empty:
                df_filtered = df_filtered.sort_values(by='Max_Alt', ascending=False)
                
                # Display summary table
                cols = ['Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes', 'Max_Alt']
                final_cols = [c for c in cols if c in df_filtered.columns]
                
                print("\n" + "="*60)
                print(f"OBSERVABLE OBJECTS SUMMARY ({observatory_code})")
                print("="*60)
                # Temporary context to display all rows
                with pd.option_context('display.max_rows', None):
                    print(df_filtered[final_cols].to_string(index=False))
                
                # 4. Interactive Mode (Optional)
                if interactive_mode:
                    while True:
                        print("\n" + "-"*60)
                        target = input("Enter the 'Temp Desig' to see full details (or '0' to exit): ").strip()
                        
                        if target == '0':
                            print("Exiting interaction...")
                            break
                        
                        obj_row = df_filtered[df_filtered['Temp Desig'] == target]
                        
                        if not obj_row.empty:
                            print(f"\nDETAILS FOR OBJECT: {target}")
                            print("="*30)
                            print(obj_row.iloc[0]) 
                        else:
                            print(f"Object '{target}' not found via exact match. Check spelling.")

            else:
                print("\nNo objects visible with current criteria.")
        else:
            print("Failed to obtain observatory coordinates.")
    else:
        print("No data downloaded.")
        
    return df_filtered

def filter_visible_objects(df, location):
    """
    Filter objects based on visibility from a specific location.
    Parameters
    ----------
    df : pandas.DataFrame
        DataFrame containing object data.
    location : astropy.coordinates.EarthLocation
        The location from which visibility is calculated.
    Returns
    -------     
    pandas.DataFrame
        DataFrame of objects that are visible from the given location.
    """
    #print("\n--- Calculating visibility (this may take a while) ---")
    visible_objects = []
    
    # Check next 24h (15 min steps)
    current_time = Time.now()
    delta_time = np.linspace(0, 24, 96) * u.hour 
    times_grid = current_time + delta_time
    
    frame_altaz = AltAz(obstime=times_grid, location=location)

    for index, row in df.iterrows():
        try:
            ra_raw = str(row['R.A.']).strip()
            dec_raw = str(row['Decl.']).strip()
            
            ra_txt = ra_raw.replace(" ", "h", 1) if "h" not in ra_raw else ra_raw
            if "m" not in ra_txt and "h" in ra_txt:
                ra_txt += "m"
            if "h" not in ra_txt:
                ra_txt += "h"

            dec_txt = dec_raw.replace(" ", "d", 1) if "d" not in dec_raw else dec_raw
            if "m" not in dec_txt and "d" in dec_txt:
                dec_txt += "m"
            if "d" not in dec_txt:
                dec_txt += "d"

            coord = SkyCoord(ra=ra_txt, dec=dec_txt, unit=(u.hourangle, u.deg))
            altaz = coord.transform_to(frame_altaz)
            altitudes = altaz.alt.degree
            
            # Logic: > 2 points (approx 30 mins) above 10 degrees
            visible_points = np.sum(altitudes > 10)
            
            if visible_points >= 2:
                row['Visible_Minutes'] = visible_points * 15
                row['Max_Alt'] = round(np.max(altitudes), 1)
                visible_objects.append(row)
                
        except Exception:
            continue 

    return pd.DataFrame(visible_objects)

def get_observatory_location(iau_code):
    r"""
    Given an MPC observatory code, fetch the latitude, longitude and elevation
    of the observatory from the MPC's official list.
    
    Parameters
    ----------
    iau_code : str
        The 3-character MPC observatory code.
    
    Returns
    -------
    EarthLocation or None
        The astropy.coordinates.EarthLocation of the observatory, or None if not found.
    """
    url_obs = "https://minorplanetcenter.net/iau/lists/ObsCodes.html"
    # print(f"--- Downloading official MPC list to search for code {iau_code}... ---")
    r = requests.get(url_obs)
    r.raise_for_status()
    

    for line in r.text.split('\n'):
        if line.startswith(iau_code):
            parts = line.split()
            if len(parts) >= 4:
                long_deg = float(parts[1])
                cos_phi = float(parts[2])
                sin_phi = float(parts[3])
                lat_rad = np.arctan2(sin_phi, cos_phi)
                lat_deg = np.degrees(lat_rad)
                # print(f"Observatory found: Lat {lat_deg:.4f}, Lon {long_deg:.4f}")
                return EarthLocation(lat=lat_deg * u.deg, lon=long_deg * u.deg, height=0 * u.m)
    
    print(f"Code {iau_code} not found.")
    return None

def fetch_mpc_data(which='neocp', obscode='Y28'):
    """
    Fetch data from the MPC page using Selenium.
    Returns the page text or None on failure.

    Parameters
    ----------
    which : str
        Which dataset to fetch. Default is 'neocp'.
        Use 'pccp' for the Possible Comet Confirmation Page.

    obscode : str
        MPC Observatory code. Default is 'Y28'.
    
    Returns
    -------
    str or None
        The page text if successful, None otherwise.
    """
    # Determine URL based on 'which' parameter
    if which == 'neocp':
        MPC_URL = NEOCP_URL
    elif which == 'pccp':
        MPC_URL = PCCP_URL
    else:
        raise ValueError("Parameter 'which' must be either 'neocp' or 'pccp'.")
    # Start Selenium WebDriver
    print(f"Starting data fetch from the {which.upper()} page with Selenium...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options) 
    try:
        driver.get(MPC_URL)
        radio_button = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//input[@type='radio' and @name='W' and @value='a']")))
        driver.execute_script("arguments[0].scrollIntoView(true);", radio_button)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", radio_button)
        obs_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@name='obscode']")))
        obs_input.clear()
        obs_input.send_keys(obscode)
        submit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']")))
        driver.execute_script("arguments[0].click();", submit_button)
        time.sleep(5)

        if "No observers have reported any observations" in driver.page_source or "No results found" in driver.page_source:
            print("No NEO objects found matching today's criteria.")
            return None
        body_element = driver.find_element(By.TAG_NAME, "body")
        page_text = body_element.text
        print("NEO data collected successfully.")
        return page_text
    except Exception as e:
        print(f"An error occurred while fetching NEO data: {e}")
        return None
    finally:
        driver.quit()

def mpc_objects(obj_type):
    """
    1. Downloads the MPC table (NEOCP or PCCP).
    2. Prints the full table to the console.
    3. Returns the Pandas DataFrame for further interaction.
    
    Parameters:
        obj_type (str): 'neocp' or 'pccp'
    """
    #1. Configuration 
    target_type = obj_type.lower().strip()
    
    if target_type == 'neocp':
        url = "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
        print(f"--- Downloading NEOCP data from: {url} ---")
    elif target_type == 'pccp':
        url = "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"
        print(f"--- Downloading PCCP data from: {url} ---")
    else:
        print("Error: Please specify 'neocp' or 'pccp'.")
        return None

     #2. Http Request 
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status() # Check for 404/500 errors
    except Exception as e:
        print(f"Connection error: {e}")
        return None

    #3. Html Cleaning 
    soup = BeautifulSoup(response.content, 'html.parser')
    table = soup.find('table', {'class': 'tablesorter'})

    if not table:
        print("Table not found on the page.")
        return None

    # Remove hidden sorting data 
    for hidden in table.find_all('span', style=lambda x: x and 'display:none' in x):
        hidden.decompose()
        
    # Remove checkboxes
    for checkbox in table.find_all('input'):
        checkbox.decompose()

    #4. Conversion and printing
    try:
        # Read the cleaned HTML table into Pandas
        # Using flavor='bs4' to avoid lxml dependency issues
        df_list = pd.read_html(io.StringIO(str(table)), flavor='bs4')
        
        if df_list:
            df = df_list[0]
            
            # Clean column names and drop empty columns
            df.columns = [c.strip() for c in df.columns]
            df = df.dropna(axis=1, how='all')

            # === STEP A: PRINT (Visualization) ===
            print(f"\nSuccess! {len(df)} objects found.")
            print("="*80)
            
            # Configure Pandas to display all rows and columns
            pd.set_option('display.max_rows', None)
            pd.set_option('display.max_columns', None)
            pd.set_option('display.width', 1000)
            pd.set_option('display.colheader_justify', 'left')
            
            #print(df)
            #print("="*80)
            #print("The table has been printed above and returned to the variable.\n")

            #Step B: Return (Interaction)
            df = df.dropna(subset = ['Temp Desig'])
            return df
            
        else:
            print("Pandas could not read the table data.")
            return None

    except Exception as e:
        print(f"Error processing data: {e}")
        return None
    
def parse_mpc_data(page_text):
    """Process the MPC page text and return a dictionary of pandas DataFrames.

    Parameters
    ----------
    page_text : str
        Full text of the MPC page (as returned by fetch_mpc_data).

    Returns
    -------
    dict
        Mapping from object header to a pandas.DataFrame containing observation rows.
    """
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
        "Date", "UT", "R.A. (J2000)", "Decl", "Elong", "V", 'Motion min', 'Motion PA', 
        "Object Azi", "Object Alt", "Sun Alt", "Moon Phase", "Moon Dist", "Moon Alt"
    ]
    dataframes = {}
    for obj, block_lines in blocks.items():
        rows = []
        for line in block_lines:
            if re.match(r'^\d{4}', line.strip()):
                tokens = line.split()
                if len(tokens) >= 20:
                    rows.append([" ".join(tokens[0:3]), tokens[3], " ".join(tokens[4:7]), " ".join(tokens[7:10]), tokens[10], tokens[11], tokens[12], tokens[13], tokens[14], tokens[15], tokens[16], tokens[17], tokens[18], tokens[19]])
        if rows:
            df = pd.DataFrame(rows, columns=column_names)
            dataframes[obj] = df
    return dataframes