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


def filter_visible_objects(dataframes_dict, altitude_min=10, time_min_minutes=30):
    """
    Filtra objetos celestes. 
    Se receber a tabela de preview (DataFrame), retorna apenas o que foi enviado (modo passivo).
    Se receber efemérides (Dicionário), realiza o cálculo matemático de visibilidade.
    """
    # Se for o DataFrame de preview (sem colunas de tempo), retorna ele mesmo sem filtrar 
    # (Evita o KeyError: 'UT' e permite que o código siga em frente)
    if isinstance(dataframes_dict, pd.DataFrame):
        if 'UT' not in dataframes_dict.columns:
            return dataframes_dict
        # Se por acaso for um DataFrame com UT, transforma em dict para o loop abaixo
        obj_label = dataframes_dict['Temp Desig'].iloc[0] if 'Temp Desig' in dataframes_dict.columns else "Object"
        dataframes_dict = {obj_label: dataframes_dict}

    summary_results = []

    for obj_name, df in dataframes_dict.items():
        df_proc = df.copy()
        
        # Limpeza robusta da coluna UT (trata espaços, pontos e preenche zeros)
        ut_clean = df_proc['UT'].astype(str).str.replace(r'[\s\.]', '', regex=True).str.zfill(4)
        
        df_proc['Datetime_UTC'] = pd.to_datetime(
            df_proc['Date'].astype(str) + ' ' + ut_clean, 
            format='%Y %m %d %H%M', errors='coerce'
        )
        
        ra_col = 'R.A. (J2000)' if 'R.A. (J2000)' in df_proc.columns else 'R.A.'
        dec_col = 'Decl' if 'Decl' in df_proc.columns else 'Decl.'
        
        df_proc = df_proc.dropna(subset=['Datetime_UTC', ra_col, dec_col])
        if df_proc.empty: continue

        # Só filtra se houver dados de altitude (Object Alt)
        if 'Object Alt' not in df_proc.columns:
            continue

        df_proc['Object Alt'] = pd.to_numeric(df_proc['Object Alt'], errors='coerce')
        df_proc['Sun Alt'] = pd.to_numeric(df_proc['Sun Alt'], errors='coerce')

        # Filtro de visibilidade real
        df_vis = df_proc[(df_proc['Object Alt'] >= altitude_min) & (df_proc['Sun Alt'] <= -18)].copy()
        if df_vis.empty: continue

        df_vis['Window_ID'] = (df_vis['Datetime_UTC'].diff() > pd.Timedelta(hours=2)).cumsum()
        
        total_min = 0
        best_idx = None
        
        for _, group in df_vis.groupby('Window_ID'):
            duration = (group['Datetime_UTC'].max() - group['Datetime_UTC'].min()).total_seconds() / 60.0
            if duration >= time_min_minutes:
                total_min += duration
                curr_max = group['Object Alt'].idxmax()
                if best_idx is None or group.loc[curr_max, 'Object Alt'] > df_vis.loc[best_idx, 'Object Alt']:
                    best_idx = curr_max

        if best_idx is not None:
            summary_results.append({
                'Temp Desig': obj_name,
                'R.A.': df_vis.loc[best_idx, ra_col],
                'Decl.': df_vis.loc[best_idx, dec_col],
                'V': df_vis.loc[best_idx, 'V'],
                'Visible_Minutes': int(total_min),
                'Max_Alt': round(df_vis.loc[best_idx, 'Object Alt'], 1),
                'Max_Alt_Time_UTC': df_vis.loc[best_idx, 'Datetime_UTC']
            })

    return pd.DataFrame(summary_results)

def mpc_objects(obj_type):
    """A high-level wrapper function that downloads the raw MPC table for a given object type, prints the total number of downloaded objects to the console, and returns the resulting pandas DataFrame."""
    df = _download_mpc_table(obj_type)
    if df is None or df.empty:
        print("No data obtained.")
        return None
    print(f"Downloaded {len(df)} objects from page {obj_type.upper()}.")
    return df

def process_mpc_data(obs_code, obj_type, interactive_mode=True):
    """Downloads the MPC data, filters it, and prints visible objects."""
    df_raw = _download_mpc_table(obj_type)
    if df_raw is None or df_raw.empty:
        return pd.DataFrame()

    # Chamada corrigida (removido local_obs e ajustado para o novo filtro)
    df_filtered = filter_visible_objects(df_raw, altitude_min=10, time_min_minutes=30)
    
    if df_filtered.empty:
        print("\nNo visible objects with current criteria.")
        return df_filtered

    if 'Max_Alt' in df_filtered.columns:
        df_filtered = df_filtered.sort_values(by='Max_Alt', ascending=False)
    
    cols = ['Temp Desig', 'R.A.', 'Decl.', 'V', 'Visible_Minutes', 'Max_Alt']
    final_cols = [c for c in cols if c in df_filtered.columns]
    
    print(df_filtered[final_cols].to_string(index=False))

    if interactive_mode:
        while True:
            target = input("Enter 'Temp Desig' to see details (or '0' to exit): ").strip()
            if target == '0': break
            obj_row = df_filtered[df_filtered['Temp Desig'] == target]
            if not obj_row.empty: print(obj_row.iloc[0])
            else: print(f"Object '{target}' not found.")
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
    """Função mestre para análise profunda via Selenium."""
    text = fetch_mpc_data(obj_type, obs_code)
    ephem_dict = parse_mpc_data(text)
    if not ephem_dict: return pd.DataFrame()
    
    df_visible = filter_visible_objects(ephem_dict, altitude_min, duration_min)

    if df_visible.empty:
        print("Nenhum objeto visível encontrado.")
        return df_visible

    print(df_visible.sort_values('Max_Alt', ascending=False).to_string(index=False))

    if plot:
        # (O código de plotagem permanece o mesmo do seu arquivo)
        plt.figure(figsize=(10, 5))
        now_dt = pd.to_datetime(Time.now().datetime)
        for obj in df_visible['Temp Desig']:
            df_obj = ephem_dict[obj].copy()
            ut_c = df_obj['UT'].astype(str).str.replace(r'[\s\.]', '', regex=True).str.zfill(4)
            df_obj['Datetime_UTC'] = pd.to_datetime(df_obj['Date'] + ' ' + ut_c, format='%Y %m %d %H%M', errors='coerce')
            df_obj = df_obj.dropna(subset=['Datetime_UTC'])
            times_hours = (df_obj['Datetime_UTC'] - now_dt).dt.total_seconds() / 3600
            plt.plot(times_hours, pd.to_numeric(df_obj['Object Alt'], errors='coerce'), label=obj)
        plt.axhline(altitude_min, color='red', linestyle='--')
        plt.ylim(0, 90)
        plt.xlabel('Horas a partir de agora (UTC)')
        plt.ylabel('Altitude (°)')
        plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
        plt.grid(True)
        plt.tight_layout()
        plt.show()
    
    return df_visible