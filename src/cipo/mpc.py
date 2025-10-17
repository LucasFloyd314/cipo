# src/cipo/neo.py

import re
import time
import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

NEOCP_URL = "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
PCCP_URL = "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"

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
            if current_object and current_block: blocks[current_object] = current_block
            current_object, current_block = line_stripped, []
            continue
        if current_object:
            if "Get the observations" not in line_stripped and line_stripped:
                current_block.append(line_stripped)
    if current_object and current_block: blocks[current_object] = current_block

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