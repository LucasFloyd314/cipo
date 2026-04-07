import io
import re
import time
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import requests
from bs4 import BeautifulSoup
from astropy.coordinates import SkyCoord, EarthLocation, AltAz
from astropy.time import Time
import astropy.units as u
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# Configure to show all rows and columns
pd.set_option('display.max_rows', None)      
pd.set_option('display.max_columns', None)   
pd.set_option('display.width', None)         
pd.set_option('display.max_colwidth', None)  

def parse_ra_to_deg(ra_series):
    """Converts a pandas Series of Right Ascension (RA) strings formatted as 'HH MM.m' or 'HH MM SS.s' into decimal degrees. It extracts hours, minutes, and seconds using regular expressions and performs the necessary mathematical conversions."""
    pattern = r'^(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)(?:\s+(\d{1,2}(?:\.\d+)?))?'
    extracted = ra_series.str.extract(pattern, expand=True)
    hours = pd.to_numeric(extracted[0], errors='coerce').fillna(0)
    minutes = pd.to_numeric(extracted[1], errors='coerce').fillna(0)
    seconds = pd.to_numeric(extracted[2], errors='coerce').fillna(0)
    hours_dec = hours + (minutes / 60) + (seconds / 3600)
    return hours_dec * 15.0

def parse_dec_to_deg(dec_series):
    """Converts a pandas Series of Declination (Dec) strings formatted as '±DD MM' or '±DD MM SS' into decimal degrees. It handles positive and negative signs and calculates the absolute decimal value based on degrees, minutes, and seconds."""
    pattern = r'^([+-]?)\s*(\d{1,2})\s+(\d{1,2}(?:\.\d+)?)(?:\s+(\d{1,2}(?:\.\d+)?))?'
    extracted = dec_series.str.extract(pattern, expand=True)
    sign = extracted[0].map({'': 1, '+': 1, '-': -1}).fillna(1).astype(float)
    degrees = pd.to_numeric(extracted[1], errors='coerce').fillna(0)
    minutes = pd.to_numeric(extracted[2], errors='coerce').fillna(0)
    seconds = pd.to_numeric(extracted[3], errors='coerce').fillna(0)
    dec_abs = degrees + (minutes / 60) + (seconds / 3600)
    return sign * dec_abs

def _get_mpc_url(obj_type):
    """Returns the appropriate Minor Planet Center (MPC) URL string depending on the given object type. It accepts "NEOCP" (Near-Earth Object Confirmation Page) or "PCCP" (Possible Comet Confirmation Page) and raises an error if an invalid type is provided."""
    obj_type = obj_type.strip().upper()
    if obj_type == "NEOCP":
        return "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
    elif obj_type == "PCCP":
        return "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"
    else:
        raise ValueError("obj_type must be 'NEOCP' or 'PCCP'")

def _download_mpc_table(obj_type):
    """Fetches the HTML content from the corresponding MPC page, locates the data table, removes hidden sorting elements/checkboxes, and parses the table into a cleaned pandas DataFrame with standardized column names and numeric data types."""
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

def get_observatory_location(obs_code):
    """Retrieves the geographical coordinates (longitude and latitude) of a specific observatory by fetching its MPC code from the official Minor Planet Center observatory list. Returns the location as an astropy EarthLocation object."""
    url_obs = "https://minorplanetcenter.net/iau/lists/ObsCodes.html"
    try:
        r = requests.get(url_obs)
        r.raise_for_status()
    except Exception:
        print("Error accessing observatory list")
        return None

    for line in r.text.split('\n'):
        if line.startswith(obs_code):
            parts = line.split()
            if len(parts) >= 4:
                long_deg = float(parts[1])
                cos_phi = float(parts[2])
                sin_phi = float(parts[3])
                lat_rad = np.arctan2(sin_phi, cos_phi)
                lat_deg = np.degrees(lat_rad)
                return EarthLocation(lat=lat_deg * u.deg, lon=long_deg * u.deg, height=0 * u.m)
    print(f"Code {obs_code} not found.")
    return None

def filter_visible_objects(df, location, altitude_min=10, time_min_minutes=30):
    """Filters a DataFrame of celestial objects to find those that are visible from a specific EarthLocation. It calculates the altitude of the objects over a 24-hour period (in 15-minute intervals) and returns only the objects that remain above the altitude_min threshold for at least the time_min_minutes duration."""
    if df is None or df.empty:
        return pd.DataFrame()

    ra_col = next((c for c in df.columns if 'ra' in re.sub(r'[^a-zA-Z]', '', c).lower()), None)
    dec_col = next((c for c in df.columns if 'dec' in re.sub(r'[^a-zA-Z]', '', c).lower()), None)
    
    if not ra_col or not dec_col:
        print("Error: RA and/or Dec columns not found.")
        return pd.DataFrame()

    ra_deg = parse_ra_to_deg(df[ra_col].astype(str))
    dec_deg = parse_dec_to_deg(df[dec_col].astype(str))

    valid = ra_deg.notna() & dec_deg.notna()
    if not valid.all():
        df = df[valid].copy()
        ra_deg = ra_deg[valid]
        dec_deg = dec_deg[valid]

    if df.empty:
        return pd.DataFrame()

    coords = SkyCoord(ra=ra_deg.values * u.deg, dec=dec_deg.values * u.deg)
    current_time = Time.now()
    step_min = 15
    n_steps = int(24 * 60 / step_min) + 1
    deltas = np.linspace(0, 24, n_steps) * u.hour
    times = current_time + deltas

    frame_altaz = AltAz(obstime=times.reshape(-1, 1), location=location)

    try:
        altaz = coords.transform_to(frame_altaz)
        altitudes = altaz.alt.degree   
    except Exception:
        altitudes = np.zeros((n_steps, len(df)))
        for i, t in enumerate(times):
            frame_t = AltAz(obstime=t, location=location)
            altaz_t = coords.transform_to(frame_t)
            altitudes[i, :] = altaz_t.alt.degree

    above_limit = altitudes > altitude_min
    visible_points = np.sum(above_limit, axis=0)
    max_alt = np.max(altitudes, axis=0)

    min_points = int(np.ceil(time_min_minutes / step_min))
    mask = visible_points >= min_points

    if not np.any(mask):
        return pd.DataFrame()

    df_result = df.iloc[mask].copy()
    df_result['Visible_Minutes'] = visible_points[mask] * step_min
    df_result['Max_Alt'] = np.round(max_alt[mask], 1)

    return df_result

def mpc_objects(obj_type):
    """A high-level wrapper function that downloads the raw MPC table for a given object type, prints the total number of downloaded objects to the console, and returns the resulting pandas DataFrame."""
    df = _download_mpc_table(obj_type)
    if df is None or df.empty:
        print("No data obtained.")
        return None
    print(f"Downloaded {len(df)} objects from page {obj_type.upper()}.")
    return df

def process_mpc_data(obs_code, obj_type, interactive_mode=True):
    """Downloads the MPC data, filters it for objects visible from the specified observatory code, and prints a formatted table of the visible objects sorted by their maximum altitude. If interactive_mode is True, it starts a loop allowing the user to type an object's designation to view its specific details."""
    df_raw = _download_mpc_table(obj_type)
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()

    local_obs = get_observatory_location(obs_code)
    if local_obs is None:
        return pd.DataFrame()

    df_filtered = filter_visible_objects(df_raw, local_obs, altitude_min=10, time_min_minutes=30)
    if df_filtered.empty:
        print("\nNo visible objects with current criteria.")
        return df_filtered

    df_filtered = df_filtered.sort_values(by='Max_Alt', ascending=False)
    cols = ['Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes', 'Max_Alt']
    final_cols = [c for c in cols if c in df_filtered.columns]
    
    with pd.option_context('display.max_rows', None):
        print(df_filtered[final_cols].to_string(index=False))

    if interactive_mode:
        while True:
            target = input("Enter 'Temp Desig' to see details (or '0' to exit): ").strip()
            if target == '0':
                break
            obj_row = df_filtered[df_filtered['Temp Desig'] == target]
            if not obj_row.empty:
                print(obj_row.iloc[0])
            else:
                print(f"Object '{target}' not found.")
    return df_filtered

def fetch_mpc_data(obj_type, obs_code):
    """Uses Selenium WebDriver in headless mode to navigate the MPC website, automatically fills out the ephemeris form (selecting all objects and inputting the provided observatory code), submits it, and scrapes the raw text output of the resulting ephemerides page."""
    # 1. Configura a URL dinamicamente
    if obj_type.strip().upper() == "NEOCP":
        url = "https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html"
    else:
        url = "https://minorplanetcenter.net/iau/NEO/pccp_tabular.html"

    print(f"Iniciando coleta de efemérides via Selenium para {obj_type.upper()} (Obs: {obs_code})...")

    # Configura o navegador para rodar em modo headless
    chrome_options = Options()
    chrome_options.add_argument("--headless")  # Executa sem abrir a janela
    chrome_options.add_argument("--disable-gpu")  # Desativa a aceleração gráfica
    chrome_options.add_argument("--window-size=1920,1080")  # Define o tamanho da janela
    chrome_options.add_argument("--no-sandbox")  # Útil em ambientes Linux
    chrome_options.add_argument("--disable-dev-shm-usage") # Dica: Evita o crash de "Stacktrace" por falta de memória
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

    # Inicializa o driver
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

    try:
        # Abre a página do MPC
        driver.get(url)
        
        # Localiza o radio button "All objects", rola a página e clica
        radio_button = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, "//input[@type='radio' and @name='W' and @value='a']"))
        )
        driver.execute_script("arguments[0].scrollIntoView(true);", radio_button)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", radio_button)
        
        # Localiza o campo do observatório e insere o código passado na função
        obs_input = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[@name='obscode']"))
        )
        obs_input.clear()
        obs_input.send_keys(obs_code)
        
        # Localiza e clica no botão "Get ephemerides"
        submit_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']"))
        )
        driver.execute_script("arguments[0].click();", submit_button)
        
        # Aguarda carregar a nova página gerada
        time.sleep(5)
        
        # Verifica se o site retornou vazio
        if "No observers have reported" in driver.page_source or "No results found" in driver.page_source:
            print("Nenhum objeto encontrado com efemérides para hoje.")
            return None
        
        # Extrai o texto final
        body_element = driver.find_element(By.TAG_NAME, "body")
        page_text = body_element.text
        return page_text
        
    except Exception as e:
        print(f"Erro durante a execução do Selenium: {e}")
        return None
        
    finally:
        # Garante que o Chrome invisível seja fechado para não travar o PC
        driver.quit()

def parse_mpc_data(page_text):
    """Parses the raw ephemeris text string obtained from the MPC website. It iterates through the text line by line, identifies individual objects, accounts for optional interference asterisks, and extracts the coordinate and motion data into a dictionary of pandas DataFrames (where keys are the object designations)."""
    if not page_text:
        return {}
        
    ephemeris_dict = {}
    lines = page_text.split('\n')
    current_obj = None
    current_data = []
    
    # Exatamente as colunas úteis da sua imagem
    column_names = [
        "Date", "UT", "R.A. (J2000)", "Decl", "Elong", "V", "Motion min", "Motion PA"
    ]
    
    for i, line in enumerate(lines):
        line_stripped = line.strip()
        if not line_stripped:
            continue
            
        # Quando achamos essa frase, sabemos que a linha anterior era o nome do objeto
        if "Get the observations" in line_stripped:
            if current_obj and current_data:
                ephemeris_dict[current_obj] = pd.DataFrame(current_data, columns=column_names)
            
            # Pega o nome do objeto da linha anterior
            current_obj = lines[i-1].strip().split()[0]
            current_data = []
            continue
            
        # Captura as linhas de coordenadas (que começam com o Ano, ex: 2026)
        if current_obj and re.match(r'^\d{4}', line_stripped):
            tokens = line_stripped.split()
            
            # Verifica se o asterisco '*' está presente (ele empurra as colunas 1 casa pra frente)
            offset = 1 if tokens[4] == '*' else 0
            
            # Verifica se tem o número correto de dados da tabela da imagem (14 sem asterisco, 15 com)
            if len(tokens) >= 14 + offset: 
                date = f"{tokens[0]} {tokens[1]} {tokens[2]}"
                ut = tokens[3]
                ra = f"{tokens[4+offset]} {tokens[5+offset]} {tokens[6+offset]}"
                decl = f"{tokens[7+offset]} {tokens[8+offset]} {tokens[9+offset]}"
                elong = tokens[10+offset]
                v_mag = tokens[11+offset]
                mot_min = tokens[12+offset]
                mot_pa = tokens[13+offset]
                
                row = [date, ut, ra, decl, elong, v_mag, mot_min, mot_pa]
                current_data.append(row)
                
    # Salva o último objeto processado do laço
    if current_obj and current_data:
        ephemeris_dict[current_obj] = pd.DataFrame(current_data, columns=column_names)
        
    return ephemeris_dict

def analyze_ephemeris_objects(obs_code, obj_type, altitude_min=10, duration_min=30, plot=True):
    """An orchestration function that executes the full pipeline: it fetches the observatory location, scrapes the ephemeris data using Selenium, parses the text into DataFrames, filters the objects based on visibility criteria (altitude and duration), and returns a dictionary with the results. If plot is True, it also generates and displays a Matplotlib graph showing the altitude curves of the visible objects over the next 24 hours."""
    resultado_padrao = {'visible_objects': pd.DataFrame(), 'altitude_curves': {}, 'times': None}

    location = get_observatory_location(obs_code)
    if location is None:
        return resultado_padrao

    page_text = fetch_mpc_data(obj_type, obs_code)
    if page_text is None:
        return resultado_padrao

    ephemeris_dict = parse_mpc_data(page_text)
    if not ephemeris_dict:
        print("Nenhum dado de efemérides foi parseado com sucesso.")
        return resultado_padrao

    rows = []
    for obj_name, df_ephem in ephemeris_dict.items():
        if df_ephem.empty:
            continue
        ra = df_ephem.iloc[0]['R.A. (J2000)']
        dec = df_ephem.iloc[0]['Decl']
        v_mag = df_ephem.iloc[0]['V'] if 'V' in df_ephem.columns else np.nan
        rows.append({'Temp Desig': obj_name, 'R.A.': ra, 'Decl.': dec, 'V': v_mag})
        
    df_objects = pd.DataFrame(rows)
    if df_objects.empty:
        return resultado_padrao

    df_visible = filter_visible_objects(df_objects, location, altitude_min=altitude_min, time_min_minutes=duration_min)

    if df_visible.empty:
        print("Objetos encontrados, mas nenhum atinge a altitude mínima e o tempo mínimo exigidos.")
        return resultado_padrao

    resultado_padrao['visible_objects'] = df_visible

    if plot:
        step_min = 15
        n_steps = int(24 * 60 / step_min) + 1
        times_hours = np.linspace(0, 24, n_steps)

        ra_vis = []
        dec_vis = []
        for idx, row in df_visible.iterrows():
            ra_deg = parse_ra_to_deg(pd.Series([row['R.A.']]))[0]
            dec_deg = parse_dec_to_deg(pd.Series([row['Decl.']]))[0]
            ra_vis.append(ra_deg)
            dec_vis.append(dec_deg)

        coords_vis = SkyCoord(ra=np.array(ra_vis)*u.deg, dec=np.array(dec_vis)*u.deg)

        current_time = Time.now()
        deltas = times_hours * u.hour
        times = current_time + deltas

        frame_altaz = AltAz(obstime=times.reshape(-1,1), location=location)
        altaz_vis = coords_vis.transform_to(frame_altaz)
        altitudes_vis = altaz_vis.alt.degree

        altitude_curves = {}
        for i, obj_name in enumerate(df_visible['Temp Desig']):
            altitude_curves[obj_name] = altitudes_vis[:, i]

        resultado_padrao['altitude_curves'] = altitude_curves
        resultado_padrao['times'] = times_hours

        plt.figure(figsize=(12,6))
        for obj_name in altitude_curves:
            plt.plot(times_hours, altitude_curves[obj_name], label=obj_name)
        plt.axhline(y=altitude_min, color='r', linestyle='--', label=f'Altitude mínima ({altitude_min}°)')
        plt.xlabel('Tempo a partir de agora (horas)')
        plt.ylabel('Altitude (graus)')
        plt.title(f'Curvas de altitude - Visíveis no obs {obs_code}')
        
        if len(altitude_curves) > 15:
            plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left', fontsize='small', ncol=2)
        else:
            plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
            
        plt.tight_layout()
        plt.grid(True)
        plt.show()

    return resultado_padrao