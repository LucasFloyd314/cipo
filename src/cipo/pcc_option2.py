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

# Configurações do Pandas
pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 50)
pd.set_option('display.width', 1000)

def parse_extended_line(line):
    # ... (cole sua função parse_extended_line aqui, sem alterações) ...
    tokens = line.split()
    if len(tokens) < 20:
        return None
    
    parts = {
        "date_val": " ".join(tokens[0:3]), "ut_val": tokens[3], "ra_val": " ".join(tokens[4:7]),
        "decl_val": " ".join(tokens[7:10]), "elong_val": tokens[10], "v_val": tokens[11],
        "motion_min": tokens[12], "motion_PA": tokens[13], "obj_azi": tokens[14],
        "obj_alt": tokens[15], "sun_alt": tokens[16], "moon_phase": tokens[17],
        "moon_dist": tokens[18], "moon_alt": tokens[19]
    }
    return list(parts.values())


def fetch_data_pcc_2():
    # ... (cole toda a lógica de coleta com Selenium aqui) ...
    print("Iniciando a busca de dados no Minor Planet Center...")
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    page_text = ""
    try:
        driver.get("https://minorplanetcenter.net/iau/NEO/toconfirm_tabular.html")
        radio_button = WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.XPATH, "//input[@type='radio' and @name='W' and @value='a']")))
        driver.execute_script("arguments[0].scrollIntoView(true);", radio_button)
        time.sleep(1)
        driver.execute_script("arguments[0].click();", radio_button)
        obs_input = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//input[@name='obscode']")))
        obs_input.clear()
        obs_input.send_keys("Y28")
        submit_button = WebDriverWait(driver, 10).until(EC.element_to_be_clickable((By.XPATH, "//input[@type='submit']")))
        driver.execute_script("arguments[0].click();", submit_button)
        time.sleep(5)
        body_element = driver.find_element(By.TAG_NAME, "body")
        page_text = body_element.text
        print("Dados coletados com sucesso.")
    finally:
        driver.quit()
    return page_text

def process_data_pcc_2(page_text):
    # ... (cole a lógica de processamento de texto aqui) ...
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
                parsed = parse_extended_line(line)
                if parsed is not None: rows.append(parsed)
        if rows:
            df = pd.DataFrame(rows, columns=column_names)
            dataframes[obj] = df
    return dataframes

def interaction_menu_pcc_2(df, obj_name):
    # ... (cole sua função interaction_menu aqui, sem alterações) ...
    while True:
        print("\n" + "="*40)
        print(f"--- Análise Interativa do Objeto: {obj_name} ---")
        print(f"(Tabela com {len(df)} linhas e {len(df.columns)} colunas)")
        print("\nOpções:")
        print("1. Mostrar a tabela completa")
        print("2. Visualizar uma coluna inteira")
        print("3. Visualizar uma linha específica (pelo índice)")
        print("4. Obter um valor específico (célula)")
        print("0. Voltar ao menu principal de objetos")
        
        choice = input("\nEscolha sua opção: ")
        # ... resto da função ...
        if choice == '1':
            print(f"\n--- Tabela Completa: {obj_name} ---")
            print(df)
        elif choice == '2':
            print("\nColunas disponíveis:", list(df.columns))
            col_name = input("Digite o nome da coluna que deseja ver: ")
            if col_name in df.columns:
                print(f"\n--- Dados da Coluna '{col_name}' ---")
                print(df[col_name])
            else:
                print("ERRO: Nome da coluna inválido.")
        elif choice == '3':
            try:
                idx = int(input(f"Digite o índice da linha (0 a {len(df)-1}): "))
                print(f"\n--- Dados da Linha {idx} ---")
                print(df.iloc[idx])
            except (ValueError, IndexError):
                print("ERRO: Índice inválido ou fora do alcance.")
        elif choice == '4':
            try:
                idx = int(input(f"Digite o índice da linha (0 a {len(df)-1}): "))
                print("\nColunas disponíveis:", list(df.columns))
                col_name = input("Agora, digite o nome da coluna: ")
                if col_name in df.columns:
                    value = df.loc[df.index[idx], col_name]
                    print("\n" + "-"*20)
                    print(f"Valor na linha {idx}, coluna '{col_name}': {value}")
                    print("-" * 20)
                else:
                    print("ERRO: Nome da coluna inválido.")
            except (ValueError, IndexError):
                print("ERRO: Índice inválido ou fora do alcance.")
        elif choice == '0':
            print(f"Retornando ao menu principal.")
            break
        else:
            print("Opção inválida. Tente novamente.")

def main_menu_pcc_2(dataframes):
    # ... (cole sua função main_menu aqui, com uma pequena alteração) ...
    if not dataframes:
        print("\nNenhum objeto foi encontrado para o observatório Y28 hoje.")
        return

    object_list = list(dataframes.keys())
    while True:
        print("\n" + "="*40)
        print("--- OBJETOS ENCONTRADOS ---")
        for i, obj_name in enumerate(object_list):
            print(f"{i + 1}. {obj_name}")
        print("0. Sair")
        try:
            choice = int(input("\nDigite o número do objeto que deseja analisar: "))
            if choice == 0:
                print("Encerrando o programa.")
                break
            elif 1 <= choice <= len(object_list):
                selected_obj_name = object_list[choice - 1]
                selected_df = dataframes[selected_obj_name]
                interaction_menu_pcc_2(selected_df, selected_obj_name)
            else:
                print("Número inválido. Por favor, escolha um número da lista.")
        except ValueError:
            print("Entrada inválida. Por favor, digite um número.")


def start_pcc_2():
    """Função principal que inicia todo o processo."""
    page_text = fetch_data_pcc_2()
    if page_text:
        dataframes = process_data_pcc_2(page_text)
        main_menu_pcc_2(dataframes)

if __name__ == "__main__":
    start_pcc_2()