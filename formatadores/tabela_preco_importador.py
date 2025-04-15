# formatadores/tabela_preco_importador.py

import pandas as pd
import io
import traceback
import re
import unicodedata
import csv

# --- Funções Auxiliares para Busca de Coluna (Robustas) ---

def normalize_text_for_match(text):
    """Normaliza texto para busca: minúsculo, sem acentos, sem não-alfanuméricos."""
    if not isinstance(text, str): text = str(text)
    try:
        # Normaliza para decompor acentos, codifica/decodifica para remover, põe em minúsculo
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        text = text.lower()
        # Remove tudo que não for letra ou número
        text = re.sub(r'[^a-z0-9]', '', text)
        return text.strip()
    except Exception:
        # Fallback muito básico se a normalização falhar
        return str(text).lower().strip().replace(' ', '')

def find_column_flexible(df_columns, concept_keywords, concept_name, required=True):
    """
    Encontra coluna de forma flexível (case-insensitive, accent-insensitive,
    space-insensitive, partial match).
    """
    normalized_input_cols = {normalize_text_for_match(col): col for col in df_columns}
    print(f"  Buscando '{concept_name}': Keywords={concept_keywords}. Colunas Norm.: {list(normalized_input_cols.keys())}") # Debug
    found_col_name = None

    # 1. Match exato normalizado
    for keyword in concept_keywords:
        norm_keyword = normalize_text_for_match(keyword)
        if norm_keyword in normalized_input_cols:
            found_col_name = normalized_input_cols[norm_keyword]
            print(f"    -> Match exato norm. '{norm_keyword}' para '{concept_name}'. Col original: '{found_col_name}'")
            return found_col_name # Retorna imediatamente no match exato

    # 2. Match parcial normalizado (se não houve exato)
    potential_matches = []
    for keyword in concept_keywords:
        norm_keyword = normalize_text_for_match(keyword)
        if not norm_keyword: continue # Pula keywords vazias após normalização

        for norm_col, orig_col in normalized_input_cols.items():
            if not norm_col: continue # Pula colunas vazias após normalização

            # Verifica se a keyword normalizada está contida na coluna normalizada
            if norm_keyword in norm_col:
                 # Prioridade 0 se começa com a keyword, 1 caso contrário
                 priority = 0 if norm_col.startswith(norm_keyword) else 1
                 potential_matches.append((priority, orig_col))
                 # Debug: mostra candidatos
                 # print(f"    -> Match parcial candidato: '{keyword}' em '{orig_col}' (Norm: '{norm_keyword}' em '{norm_col}') Prio:{priority}")

    if potential_matches:
        potential_matches.sort() # Ordena por prioridade (0 vem primeiro)
        found_col_name = potential_matches[0][1] # Pega a melhor correspondência (primeira da lista ordenada)
        print(f"    -> Melhor match parcial para '{concept_name}'. Col original: '{found_col_name}'")
        return found_col_name

    # 3. Erro se obrigatório e não encontrado (nenhum match exato ou parcial)
    if required:
        raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada. Keywords usadas: {concept_keywords}. Colunas originais: {list(df_columns)}")
    else:
        # Se não for obrigatório, apenas informa e retorna None
        print(f"    -> Coluna opcional '{concept_name}' não encontrada.")
        return None

# --- Funções Auxiliares para Formatação ---

def normalize_text(text):
    """Normaliza texto removendo acentos e convertendo para maiúsculas."""
    if not isinstance(text, str): text = str(text)
    try:
        # Tenta normalizar e remover acentos
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        return text.upper().strip()
    except Exception as e:
        # Fallback simples se a normalização falhar
        print(f"Aviso: Falha ao normalizar texto '{text}'. Erro: {e}")
        return str(text).upper().strip()

# --- formatar_nome_unidade é usada apenas por processar_preco_incorporacao ---
def formatar_nome_unidade(row):
    """Formata o nome da unidade (BLXX - APT YY ou com PCD), verificando PCD em APT e TIPOLOGIA."""
    bloco_val = row.get('BLOCO_INPUT', '')
    apt_val = row.get('APT_INPUT', '')
    tipologia_val = row.get('TIPOLOGIA_INPUT', '') # Usado para checar 'PCD'

    is_pcd = False # Flag para indicar se é PCD
    if pd.notna(tipologia_val):
        tipologia_norm = normalize_text(str(tipologia_val))
        if 'PCD' in tipologia_norm: is_pcd = True
        # print(f"DEBUG PCD Check (Tipo): Bloco='{bloco_val}', Apt='{apt_val}', Tipo Norm='{tipologia_norm}', IsPCD={is_pcd}") # DEBUG
    if not is_pcd and pd.notna(apt_val):
         apt_norm = normalize_text(str(apt_val))
         if 'PCD' in apt_norm: is_pcd = True
         # print(f"DEBUG PCD Check (Apt): Bloco='{bloco_val}', Apt='{apt_val}', Apt Norm='{apt_norm}', IsPCD={is_pcd}") # DEBUG
    pcd_suffix = " (PCD)" if is_pcd else ""

    if pd.notna(bloco_val) and str(bloco_val).strip() and pd.notna(apt_val) and str(apt_val).strip():
        try:
            bloco_num_match = re.search(r'\d+', str(bloco_val)); bloco_num_str = f"{int(bloco_num_match.group(0)):02d}" if bloco_num_match else str(bloco_val).strip() if str(bloco_val).strip() else "??"
            bloco_str = f"BL{bloco_num_str}"
            apt_num_match = re.search(r'\d+', str(apt_val)); apt_num_str = f"{int(apt_num_match.group(0)):02d}" if apt_num_match else str(apt_val).strip() if str(apt_val).strip() else "??"
            apt_str = f"APT {apt_num_str}"
            apt_str_cleaned = re.sub(r'\s?\(PCD\)', '', apt_str, flags=re.IGNORECASE).strip()
            return f"{bloco_str} - {apt_str_cleaned}{pcd_suffix}"
        except Exception as e:
            print(f"Erro formatar_nome_unidade: {e} para Bloco '{bloco_val}', Apt '{apt_val}'")
            bloco_s = str(bloco_val).strip(); apt_s = str(apt_val).strip(); apt_s_cleaned = re.sub(r'\s?\(PCD\)', '', apt_s, flags=re.IGNORECASE).strip(); return f"BL{bloco_s} - APT {apt_s_cleaned}{pcd_suffix}" # Fallback
    return "UNIDADE_ERRO"

def format_brl(value):
    """Converte valor numérico ou string para formato moeda BRL (R$ X.XXX,XX). Retorna '' se inválido."""
    if pd.isna(value) or value == '': return ''
    s_val = str(value).strip()
    if re.search(r'[a-gi-qs-zA-GI-QS-Z]', s_val): print(f"Aviso format_brl: Valor '{value}' contém letras inesperadas. Retornando vazio."); return ''
    s_val = s_val.replace('R$', '').replace('.', '').strip(); s_val = s_val.replace(',', '.')
    try: num = float(s_val); formatted_value = f"{num:_.2f}".replace(".", ",").replace("_", "."); return f"R$ {formatted_value}"
    except (ValueError, TypeError): print(f"Aviso format_brl: Não converteu '{value}' para número. Retornando vazio."); return ''

def format_area(value):
    """Limpa valor de área, converte para float e formata com vírgula decimal."""
    if pd.isna(value) or value == '': return ''
    s_val = str(value).strip(); s_val = re.sub(r'm[²2]?$', '', s_val, flags=re.IGNORECASE).strip()
    s_val = re.sub(r'[^\d,.]', '', s_val)
    if ',' in s_val and '.' in s_val: s_val = s_val.replace('.', '').replace(',', '.')
    elif ',' in s_val: s_val = s_val.replace(',', '.')
    try: num = float(s_val); return f"{num:.2f}".replace('.', ',')
    except (ValueError, TypeError): print(f"Aviso format_area: Não formatou valor '{value}' como área."); return str(value).strip()

# --- Função Principal para Tabela Incorporação ---
def processar_preco_incorporacao(input_filepath, selected_valor_column_name):
    """Lê Excel incorporação, processa e retorna StringIO CSV."""
    print(f"(Preço Incorporação) Iniciando: {input_filepath}, Col Valor: '{selected_valor_column_name}'")
    try:
        linhas_para_ignorar = 2
        try: df_input = pd.read_excel(input_filepath, engine='openpyxl', skiprows=linhas_para_ignorar, header=0, dtype=str).dropna(how='all').reset_index(drop=True)
        except Exception as e_read: raise ValueError(f"Falha ao ler Excel.") from e_read
        if df_input.empty: raise ValueError("Arquivo vazio ou sem dados.")
        print(f"(Preço Incorporação) Lidas {len(df_input)} linhas.")
        df_input.columns = df_input.columns.str.strip(); print(f"Colunas: {df_input.columns.tolist()}")
        if selected_valor_column_name not in df_input.columns: raise ValueError(f"Coluna '{selected_valor_column_name}' não encontrada.")
        print("--- Buscando Cols ---"); col_bloco = find_column_flexible(df_input.columns, ['bloco'], 'BLOCO', required=True); col_apt = find_column_flexible(df_input.columns, ['apt', 'apto', 'apartamento'], 'APT', required=True); col_tipologia = find_column_flexible(df_input.columns, ['tipologia', 'tipo da unidade', 'descricao'], 'TIPOLOGIA', required=True); print("--- Fim Busca ---")
        print(f"Aplicando ffill Bloco: '{col_bloco}'"); df_input[col_bloco] = df_input[col_bloco].ffill()
        print(f"Aplicando ffill Tipologia: '{col_tipologia}'"); df_input[col_tipologia] = df_input[col_tipologia].ffill()
        df_output = pd.DataFrame(index=df_input.index)
        bloco_formatado = df_input[col_bloco].fillna('').astype(str).str.extract(r'(\d+)', expand=False).fillna('0').astype(int).apply(lambda x: f"{x:02d}")
        df_output['BLOCO'] = bloco_formatado.apply(lambda x: f'="{x}"')
        df_input['BLOCO_INPUT'] = df_input[col_bloco]; df_input['APT_INPUT'] = df_input[col_apt]; df_input['TIPOLOGIA_INPUT'] = df_input[col_tipologia]
        df_output['UNIDADE'] = df_input.apply(formatar_nome_unidade, axis=1)
        df_output['VALOR DO IMOVEL'] = df_input[selected_valor_column_name].apply(format_brl)
        df_output['ETAPA'] = 'ETAPA 01'
        df_output = df_output[['ETAPA', 'BLOCO', 'UNIDADE', 'VALOR DO IMOVEL']]
        output_csv = io.StringIO(); df_output.to_csv(output_csv, sep=';', encoding='utf-8-sig', index=False, decimal=',', quoting=csv.QUOTE_MINIMAL)
        output_csv.seek(0); print("(Preço Incorporação) Processamento concluído."); return output_csv
    except ValueError as ve: print(f"(Preço Incorporação) ERRO VALIDAÇÃO: {ve}"); traceback.print_exc(); raise ve
    except Exception as e: print(f"(Preço Incorporação) ERRO INESPERADO: {e}"); traceback.print_exc(); raise RuntimeError(f"Erro inesperado: {e}") from e


# --- Função para Tabela Lote à Vista (COM DEBUG E pd.to_numeric na Quadra) ---
def processar_preco_lote_avista(input_file_object):
    """
    Lê Excel lote à vista lidando com célula de Quadra mesclada,
    processa, filtra e retorna StringIO CSV.
    """
    print(f"(Preço Lote Avista) Iniciando processamento com leitura revisada.")
    try:
        # 1. Leitura Inicial SEM Cabeçalho/Skip
        try:
            # Lê tudo, sem assumir cabeçalho, convertendo para string
            df_raw = pd.read_excel(input_file_object, engine='openpyxl', header=None, dtype=str)
            print(f"(Preço Lote Avista) Lidas {len(df_raw)} linhas brutas.")
        except Exception as e_read:
            raise ValueError(f"Falha ao ler o stream/objeto Excel inicial.") from e_read

        if df_raw.empty:
             raise ValueError("Arquivo Excel parece estar vazio.")

        # 2. Encontrar Linha do Cabeçalho Real (procurando por 'LOTE' ou 'Tipo')
        header_row_index = -1
        possible_headers = ['lote', 'tipo', 'area', 'valor'] # Keywords para identificar header
        for idx, row in df_raw.head(10).iterrows(): # Procura nas primeiras 10 linhas
            row_values_norm = [normalize_text_for_match(str(v)) for v in row.values if pd.notna(v)]
            # Verifica se a maioria das keywords do header estão na linha
            if sum(h in row_values_norm for h in possible_headers) >= 2: # Exige pelo menos 2 matches
                header_row_index = idx
                print(f"Cabeçalho real encontrado na linha índice: {header_row_index}")
                break
        if header_row_index == -1:
            raise ValueError("Não foi possível encontrar a linha do cabeçalho (procurando por LOTE, Tipo, Area, Valor).")

        # 3. Encontrar Coluna da Quadra nos dados brutos (procurando por 'QUADRA')
        quadra_col_index = -1
        keyword_quadra = normalize_text_for_match('quadra')
        # Procura na linha ANTES do cabeçalho ou na linha do cabeçalho por 'QUADRA'
        search_rows = [header_row_index] if header_row_index == 0 else [header_row_index-1, header_row_index]
        for r_idx in search_rows:
             if r_idx < 0: continue
             for c_idx, val in df_raw.iloc[r_idx].items():
                 if pd.notna(val) and keyword_quadra in normalize_text_for_match(str(val)):
                     quadra_col_index = c_idx
                     print(f"Coluna da Quadra encontrada no índice: {quadra_col_index}")
                     break
             if quadra_col_index != -1: break
        if quadra_col_index == -1:
             raise ValueError("Não foi possível encontrar a coluna que contém 'QUADRA'.")

        # 4. Aplicar ffill na Coluna da Quadra nos Dados Brutos
        print(f"Aplicando ffill na coluna bruta índice {quadra_col_index}")
        df_raw[quadra_col_index] = df_raw[quadra_col_index].ffill()
        # --- DEBUG ---
        print("Valores da coluna Quadra BRUTA após ffill (linhas prox. ao header):")
        print(df_raw[[quadra_col_index]].iloc[header_row_index+1 : header_row_index+6].to_string())
        # --- FIM DEBUG ---

        # 5. Criar DataFrame Limpo (df_input)
        # Pega os nomes das colunas da linha do cabeçalho encontrada
        new_columns = df_raw.iloc[header_row_index].astype(str).str.strip()
        # Cria o novo DataFrame começando da linha APÓS o cabeçalho
        df_input = df_raw.iloc[header_row_index + 1:].copy()
        df_input.columns = new_columns # Define os nomes corretos das colunas
        df_input = df_input.reset_index(drop=True) # Reseta o índice

        # 6. Identificar Colunas Essenciais (AGORA no df_input limpo)
        print("--- Buscando Colunas no DF Limpo ---")
        # Usa o nome da coluna encontrado na etapa 3 como a coluna da quadra
        col_quadra = new_columns[quadra_col_index] # Pega o NOME da coluna Quadra
        col_lote = find_column_flexible(df_input.columns, ['lote', 'lt', 'unidade'], 'LOTE', required=True)
        col_valor = find_column_flexible(df_input.columns, ['valor a vista', 'valor à vista', 'preco a vista', 'preço à vista', 'valor avista', 'valor com registro', 'valor'], 'VALOR À VISTA', required=True)
        print("--- Fim da Busca ---")

        # 7. Remover Linhas Inválidas (onde Lote é NaN/vazio) - APÓS ffill da Quadra
        print(f"Linhas antes de dropna(subset=[{col_lote}]): {len(df_input)}")
        df_input = df_input.dropna(subset=[col_lote]).reset_index(drop=True)
        print(f"Linhas após dropna(subset=[{col_lote}]): {len(df_input)}")
        if df_input.empty:
            raise ValueError("Nenhuma linha com valor na coluna Lote encontrada.")

        # 8. Construir DataFrame de Saída
        df_output = pd.DataFrame(index=df_input.index)

        # 8.1. Coluna BLOCO (formatada "QUADRA XX" e proteção CSV)
        quadra_num_extraido = df_input[col_quadra].fillna('').astype(str).str.extract(r'(\d+)', expand=False)
        quadra_int = pd.to_numeric(quadra_num_extraido, errors='coerce').fillna(0).astype(int)
        quadra_formatada_num = quadra_int.apply(lambda x: f"{x:02d}")
        df_output['BLOCO'] = quadra_formatada_num.apply(lambda x: f'="QUADRA {x}"')

        # 8.2. Coluna UNIDADE (formatada "QDXX - LOTE YY")
        lote_formatado_num = df_input[col_lote].fillna('').astype(str).str.extract(r'(\d+)', expand=False).fillna('0').astype(int).apply(lambda x: f"{x:02d}")
        df_output['UNIDADE'] = "QD" + quadra_formatada_num + " - LOTE " + lote_formatado_num

        # 8.3. Coluna VALOR À VISTA (formatada como moeda BRL)
        df_output['VALOR À VISTA'] = df_input[col_valor].apply(format_brl)

        # 8.4. Coluna ETAPA (fixa)
        df_output['ETAPA'] = 'ETAPA 01'

        # 9. FILTRAGEM FINAL: Remover linhas com Lote '00' E Valor Vazio
        print(f"Linhas antes da filtragem final: {len(df_output)}")
        is_lote_00 = lote_formatado_num == "00"
        is_valor_vazio = df_output['VALOR À VISTA'] == ''
        condicao_excluir = is_lote_00 & is_valor_vazio
        df_output_filtrado = df_output[~condicao_excluir].copy()
        print(f"Linhas após a filtragem final: {len(df_output_filtrado)}")

        # 10. Selecionar e Reordenar Colunas Finais
        df_output_final = df_output_filtrado[['ETAPA', 'BLOCO', 'UNIDADE', 'VALOR À VISTA']]

        # 11. Gerar CSV em memória
        output_csv = io.StringIO()
        df_output_final.to_csv(output_csv, sep=';', encoding='utf-8-sig', index=False, decimal=',', quoting=csv.QUOTE_MINIMAL)
        output_csv.seek(0)

        print("(Preço Lote Avista) Processamento concluído. CSV gerado.")
        return output_csv

    except ValueError as ve: print(f"(Preço Lote Avista) ERRO VALIDAÇÃO: {ve}"); traceback.print_exc(); raise ve
    except Exception as e: print(f"(Preço Lote Avista) ERRO INESPERADO: {e}"); traceback.print_exc(); raise RuntimeError(f"Erro inesperado (Lote Avista): {e}") from e

# --- Função Placeholder para Tabela Lote Parcelado ---
def processar_preco_lote_parcelado(input_filepath):
    """Lê Excel lote parcelado e retorna BytesIO Excel (Placeholder)."""
    print(f"(Preço Lote Parcelado) Iniciando processamento (PLACEHOLDER): {input_filepath}")
    try: df_input = pd.read_excel(input_filepath, engine='openpyxl'); df_output = df_input.copy(); df_output['Processado'] = 'Sim - Lote Parcelado (Placeholder)'; output = io.BytesIO();
    except Exception as e: raise RuntimeError(f"Erro placeholder Lote Parcelado: {e}")
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df_output.to_excel(writer, sheet_name='Precos_Lote_Parcelado', index=False)
    output.seek(0); print("(Preço Lote Parcelado) Processamento (placeholder) concluído."); return output