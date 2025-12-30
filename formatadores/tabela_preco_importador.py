# formatadores/tabela_preco_importador.py

import pandas as pd
import io
import traceback
import re
import unicodedata
import csv

# --- Funções Auxiliares para Busca de Coluna (Robustas) ---

def parse_numeric(value):
    """Limpa string e tenta converter para float. Retorna NaN em caso de erro."""
    if pd.isna(value) or value == '':
        return pd.NA
    s_val = str(value).strip()
    s_val = re.sub(r'[a-df-zA-DF-Z R$]', '', s_val)
    if ',' in s_val and '.' in s_val:
        s_val = s_val.replace('.', '').replace(',', '.')
    elif ',' in s_val:
        s_val = s_val.replace(',', '.')
    try:
        return float(s_val)
    except (ValueError, TypeError):
        return pd.NA

def normalize_text_for_match(text):
    """Normaliza texto para busca: minúsculo, sem acentos, sem não-alfanuméricos."""
    if not isinstance(text, str): text = str(text)
    try:
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        text = text.lower()
        text = re.sub(r'[^a-z0-9]', '', text)
        return text.strip()
    except Exception:
        return str(text).lower().strip().replace(' ', '')

def find_column_flexible(df_columns, concept_keywords, concept_name, required=True):
    """
    Encontra coluna de forma flexível (case-insensitive, accent-insensitive,
    space-insensitive, partial match).
    """
    normalized_input_cols = {normalize_text_for_match(col): col for col in df_columns}
    print(f"  Buscando '{concept_name}': Keywords={concept_keywords}. Colunas Norm.: {list(normalized_input_cols.keys())}")
    found_col_name = None

    # 1. Match exato normalizado
    for keyword in concept_keywords:
        norm_keyword = normalize_text_for_match(keyword)
        if norm_keyword in normalized_input_cols:
            found_col_name = normalized_input_cols[norm_keyword]
            print(f"    -> Match exato norm. '{norm_keyword}' para '{concept_name}'. Col original: '{found_col_name}'")
            return found_col_name

    # 2. Match parcial normalizado
    potential_matches = []
    for keyword in concept_keywords:
        norm_keyword = normalize_text_for_match(keyword)
        if not norm_keyword: continue
        for norm_col, orig_col in normalized_input_cols.items():
            if not norm_col: continue
            if norm_keyword in norm_col:
                 priority = 0 if norm_col.startswith(norm_keyword) else 1
                 potential_matches.append((priority, orig_col))
    if potential_matches:
        potential_matches.sort()
        found_col_name = potential_matches[0][1]
        print(f"    -> Melhor match parcial para '{concept_name}'. Col original: '{found_col_name}'")
        return found_col_name

    # 3. Erro se obrigatório e não encontrado
    if required:
        raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada. Keywords usadas: {concept_keywords}. Colunas originais: {list(df_columns)}")
    else:
        print(f"    -> Coluna opcional '{concept_name}' não encontrada.")
        return None

# --- Funções Auxiliares para Formatação ---

def normalize_text(text):
    """Normaliza texto removendo acentos e convertendo para maiúsculas."""
    if not isinstance(text, str): text = str(text)
    try:
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        return text.upper().strip()
    except Exception as e:
        print(f"Aviso: Falha ao normalizar texto '{text}'. Erro: {e}")
        return str(text).upper().strip()

# <<< ADICIONADO >>>
# Funções auxiliares portadas do tabela_precos_formatador.py para dar suporte ao modo composto.
def extract_block_number_safe(block_value_str):
    """Extrai o primeiro número de uma string de bloco/quadra/casa."""
    if not isinstance(block_value_str, str): block_value_str = str(block_value_str)
    match = re.search(r'\d+', block_value_str)
    if match:
        try: return int(match.group(0))
        except ValueError: return None
    return None

def formatar_nome_unidade_composto(row, col_bloco_name, col_quadra_name, col_casa_name):
    """
    Gera o nome da unidade no formato composto (BL/US-QD-CS).
    """
    try:
        bloco_val = str(row.get(col_bloco_name, ''))
        quadra_val = str(row.get(col_quadra_name, ''))
        casa_val = str(row.get(col_casa_name, ''))

        quadra_num = extract_block_number_safe(quadra_val)
        bloco_num = extract_block_number_safe(bloco_val) # Será None para o valor 'US'
        casa_num = extract_block_number_safe(casa_val)

        quadra_str = f"QD{quadra_num:02d}" if quadra_num is not None else "QD??"
        casa_str = f"CS{casa_num:02d}" if casa_num is not None else "CS??"
        
        prefixo_str = ""
        # Regra especial: se o valor do bloco for 'US', o prefixo muda
        if bloco_val.strip().upper() == 'US':
            prefixo_str = f"US{casa_num:02d}" if casa_num is not None else "US??"
        else:
            # Para qualquer outro valor, usa 'BL' com o número do bloco
            prefixo_str = f"BL{bloco_num:02d}" if bloco_num is not None else "BL??"
        
        return f"{prefixo_str}-{quadra_str}-{casa_str}"
    except Exception as e:
        print(f"AVISO: Erro ao gerar nome de unidade composto: {e}")
        return "ERRO_UNIDADE_COMPOSTA"
# <<< FIM ADIÇÃO >>>

def formatar_nome_unidade_generico(row, col_ident_1_name, col_ident_2_name, col_tipologia_name, prefixo_1, prefixo_2):
    """
    Formata o nome da unidade (PREFIXO1 XX - PREFIXO2 YY ou com PCD),
    usando os prefixos e nomes de colunas fornecidos.
    """
    # (Esta função permanece inalterada)
    ident_1_val = row.get(col_ident_1_name, '')
    ident_2_val = row.get(col_ident_2_name, '')
    tipologia_val = row.get(col_tipologia_name, '')
    is_pcd = False
    if pd.notna(tipologia_val) and 'PCD' in normalize_text(str(tipologia_val)): is_pcd = True
    if not is_pcd and pd.notna(ident_2_val) and 'PCD' in normalize_text(str(ident_2_val)): is_pcd = True
    pcd_suffix = " (PCD)" if is_pcd else ""
    if pd.notna(ident_1_val) and str(ident_1_val).strip() and pd.notna(ident_2_val) and str(ident_2_val).strip():
        try:
            ident_1_num_match = re.search(r'\d+', str(ident_1_val)); ident_1_num_str = f"{int(ident_1_num_match.group(0)):02d}" if ident_1_num_match else str(ident_1_val).strip()
            ident_1_str = f"{prefixo_1}{ident_1_num_str}"
            ident_2_num_match = re.search(r'\d+', str(ident_2_val)); ident_2_num_str = f"{int(ident_2_num_match.group(0)):02d}" if ident_2_num_match else str(ident_2_val).strip()
            ident_2_str = f"{prefixo_2} {ident_2_num_str}"
            ident_2_str_cleaned = re.sub(r'\s?\(PCD\)', '', ident_2_str, flags=re.IGNORECASE).strip()
            return f"{ident_1_str} - {ident_2_str_cleaned}{pcd_suffix}"
        except Exception as e:
            print(f"Erro formatar_nome_unidade_generico: {e} para {col_ident_1_name}='{ident_1_val}', {col_ident_2_name}='{ident_2_val}'")
            ident_1_s = str(ident_1_val).strip(); ident_2_s = str(ident_2_val).strip()
            ident_2_s_cleaned = re.sub(r'\s?\(PCD\)', '', ident_2_s, flags=re.IGNORECASE).strip()
            return f"{prefixo_1}{ident_1_s} - {prefixo_2} {ident_2_s_cleaned}{pcd_suffix}"
    return "UNIDADE_ERRO"

def format_brl(value):
    """Converte valor numérico ou string para formato moeda BRL (R$ #.###,##) de forma manual."""
    # (Esta função permanece inalterada)
    if pd.isna(value) or value == '': return ''
    s_val = str(value).strip()
    if re.search(r'[a-gi-qs-zA-GI-QS-Z]', s_val): return ''
    s_val = re.sub(r'[^\d,.-]', '', s_val)
    if ',' in s_val and '.' in s_val: s_val = s_val.replace('.', '').replace(',', '.')
    elif ',' in s_val: s_val = s_val.replace(',', '.')
    try:
        num = float(s_val)
        valor_com_decimal = f"{num:.2f}".replace('.', ','); partes = valor_com_decimal.split(',')
        parte_inteira = partes[0]; sinal = ""
        if parte_inteira.startswith('-'): sinal = "-"; parte_inteira = parte_inteira[1:]
        parte_decimal = partes[1]; parte_inteira_com_milhar = ""
        n_digitos = len(parte_inteira)
        for i, digito in enumerate(parte_inteira):
            parte_inteira_com_milhar += digito
            if (n_digitos - 1 - i) > 0 and (n_digitos - 1 - i) % 3 == 0:
                parte_inteira_com_milhar += "."
        return f"R$ {sinal}{parte_inteira_com_milhar},{parte_decimal}"
    except (ValueError, TypeError): return ''

def format_area(value):
    """
    Limpa valor de área, converte para float, formata com vírgula decimal
    e duas casas, e encapsula em '="valor"' para forçar tratamento como texto no Excel.
    """
    if pd.isna(value) or value == '':
        return '' # Retorna vazio para valores nulos ou vazios
    original_value_str = str(value).strip()
    s_val = original_value_str
    # Remove sufixo comum (m², m2)
    s_val = re.sub(r'm[²2]?$', '', s_val, flags=re.IGNORECASE).strip()
    # Remove caracteres não permitidos, mantendo dígitos, vírgula, ponto e sinal negativo
    s_val = re.sub(r'[^\d,.-]', '', s_val)

    # Padroniza separador decimal para ponto (.) antes de converter para float
    if ',' in s_val and '.' in s_val:
        # Assume '.' como separador de milhar e ',' como decimal
        s_val = s_val.replace('.', '').replace(',', '.')
    elif ',' in s_val:
        # Assume ',' como único separador (decimal)
        s_val = s_val.replace(',', '.')
    # Agora s_val deve ter '.' como separador decimal, se houver

    try:
        num = float(s_val)
        # Formata para duas casas decimais e troca ponto por vírgula para o padrão BR
        formatted_area = f"{num:.2f}".replace('.', ',')
        # Encapsula para forçar texto no Excel
        return f'="{formatted_area}"'
    except (ValueError, TypeError):
        # Se a conversão falhar, retorna vazio
        print(f"Aviso format_area: Não converteu valor limpo '{s_val}' (original: '{original_value_str}') para float. Retornando vazio.")
        return ''
    
    # <<< ADICIONADO >>>
# Nova função auxiliar para tratar o nome do bloco de saída, incluindo o caso especial.
def formatar_nome_bloco_saida(bloco_original_valor, prefixo_completo):
    """
    Formata o nome do bloco para a coluna de saída.
    Trata o caso especial 'CASAS SOLTAS' e, caso contrário, formata com prefixo e número.
    """
    # Normaliza o valor de entrada para uma comparação robusta
    valor_normalizado = str(bloco_original_valor).strip().upper()

    # 1. Verifica a condição especial
    if valor_normalizado == 'US':
        # Retorna o valor específico solicitado, forçando como texto no Excel
        return '="UNID. SOLTAS"'
    
    # 2. Se não for a condição especial, aplica a lógica padrão
    else:
        try:
            # Extrai o primeiro número encontrado no valor original
            num_match = re.search(r'\d+', str(bloco_original_valor))
            # Formata o número com 2 dígitos se encontrado, senão usa um placeholder
            num_str = f"{int(num_match.group(0)):02d}" if num_match else "00"
            # Retorna o formato padrão, forçando como texto no Excel
            return f'="{prefixo_completo} {num_str}"'
        except (ValueError, TypeError):
            # Fallback em caso de erro na conversão
            return f'="{prefixo_completo} ERRO"'

# --- Função Principal para Tabela Incorporação (MODIFICADA) ---
def processar_preco_incorporacao(input_filepath, selected_valor_column_name):
    """
    Lê Excel incorporação, processa, e retorna StringIO CSV.
    MODIFICADO: Detecta modo composto e trata o caso especial 'CASAS SOLTAS' para a coluna BLOCO.
    """
    print(f"(Preço Incorporação) Iniciando: {input_filepath}, Col Valor: '{selected_valor_column_name}'")
    try:
        # 1. Leitura do Excel
        header_row = 2
        try:
            df_input = pd.read_excel(input_filepath, engine='openpyxl', header=header_row, dtype=str)
            df_input = df_input.dropna(how='all').reset_index(drop=True)
            # df_input = df_input.dropna(axis=1, how='all') # REMOVIDO: Isso removia a coluna de valor se ela estivesse vazia (ex: planilha modelo)
        except Exception as e_read:
            raise ValueError(f"Falha ao ler Excel (linha cabeçalho={header_row}). Verifique o arquivo.") from e_read

        if df_input.empty: raise ValueError("Arquivo vazio ou sem dados após leitura inicial.")
        print(f"(Preço Incorporação) Lidas {len(df_input)} linhas válidas.")
        df_input.columns = df_input.columns.str.strip(); print(f"Colunas: {df_input.columns.tolist()}")
        # 2. Busca Flexível se a coluna selecionada não for encontrada
        if selected_valor_column_name not in df_input.columns:
            print(f"(Preço Incorporação) Aviso: Coluna selecionada '{selected_valor_column_name}' não encontrada. Buscando alternativa contendo 'valor'...")
            alternatives = [c for c in df_input.columns if 'valor' in str(c).lower()]
            if alternatives:
                print(f"(Preço Incorporação) Alternativas encontradas: {alternatives}")
                # Prioriza 'Valor do imóvel padrão' se existir nas alternativas, senão pega a primeira
                selected_valor_column_name = next((c for c in alternatives if 'imóvel padrão' in str(c).lower()), alternatives[0])
                print(f"(Preço Incorporação) Usando coluna alternativa: '{selected_valor_column_name}'")
            else:
                # Se não encontrar nada, cria uma coluna vazia para não quebrar o processo
                print("(Preço Incorporação) AVISO CRÍTICO: Nenhuma coluna de valor encontrada. Criando coluna vazia.")
                # Usa o nome original solicitado ou um genérico
                if not selected_valor_column_name: selected_valor_column_name = "Valor do imóvel padrão"
                df_input[selected_valor_column_name] = ""

        # Garante que a coluna existe no DataFrame final (mesmo que vazia)
        if selected_valor_column_name not in df_input.columns:
             df_input[selected_valor_column_name] = ""

        # 2. DETECÇÃO DE MODO: Padrão vs. Composto
        print("--- Verificando modo de operação (Padrão vs. Composto) ---")
        col_bloco_comp = find_column_flexible(df_input.columns, ['bloco'], 'BLOCO (modo composto)', required=False)
        col_quadra_comp = find_column_flexible(df_input.columns, ['quadra'], 'QUADRA (modo composto)', required=False)
        col_casa_comp = find_column_flexible(df_input.columns, ['casa'], 'CASA (modo composto)', required=False)
        
        is_composite_mode = all([col_bloco_comp, col_quadra_comp, col_casa_comp])

        if is_composite_mode:
            print(">>> MODO COMPOSTO DETECTADO (BL-QD-CS).")
            df_input[col_bloco_comp] = df_input[col_bloco_comp].ffill()
            df_input[col_quadra_comp] = df_input[col_quadra_comp].ffill()
            
            primary_unit_col = col_casa_comp
            print(f"Linhas antes de dropna em '{primary_unit_col}': {len(df_input)}")
            df_input = df_input.dropna(subset=[primary_unit_col])
            df_input = df_input[df_input[primary_unit_col].astype(str).str.strip() != '']
            df_input = df_input.reset_index(drop=True)
            print(f"Linhas após dropna em '{primary_unit_col}': {len(df_input)}")
            if df_input.empty: raise ValueError(f"Nenhuma linha válida encontrada sem valor em '{primary_unit_col}'.")
            
            df_output = pd.DataFrame(index=df_input.index)

            # <<< MODIFICADO >>>
            # Usa a nova função para formatar a coluna BLOCO
            df_output['BLOCO'] = df_input[col_bloco_comp].apply(
                formatar_nome_bloco_saida,
                prefixo_completo="BLOCO" # No modo composto, o prefixo padrão é sempre BLOCO
            )
            # <<< FIM DA MODIFICAÇÃO >>>

            df_output['UNIDADE'] = df_input.apply(
                formatar_nome_unidade_composto,
                axis=1,
                args=(col_bloco_comp, col_quadra_comp, col_casa_comp)
            )

        else: # MODO PADRÃO
            print(">>> MODO PADRÃO DETECTADO.")
            col_ident_1 = find_column_flexible(df_input.columns, ['bloco', 'quadra'], 'IDENTIFICADOR 1 (Bloco/Quadra)', required=True)
            col_ident_2 = find_column_flexible(df_input.columns, ['apt', 'apto', 'apartamento', 'unidade', 'casa'], 'IDENTIFICADOR 2 (Apto/Casa/Unidade)', required=True)
            col_tipologia = find_column_flexible(df_input.columns, ['tipologia', 'tipo da unidade', 'descricao', 'descrição'], 'TIPOLOGIA', required=True)

            norm_col_ident_1 = normalize_text_for_match(col_ident_1)
            norm_col_ident_2 = normalize_text_for_match(col_ident_2)
            prefixo_unidade_ident_1 = "QD" if 'quadra' in norm_col_ident_1 else "BL"
            prefixo_unidade_ident_2 = "CASA" if 'casa' in norm_col_ident_2 else "APT"
            
            # <<< MODIFICAÇÃO: Define o nome da coluna de saída baseado no input >>>
            # Se a coluna original encontrada contiver 'quadra', o cabeçalho de saída será 'QUADRA'
            prefixo_coluna_bloco_completo = "QUADRA" if 'quadra' in norm_col_ident_1 else "BLOCO"
            
            print(f"  >> Prefixo para coluna BLOCO de saída: '{prefixo_coluna_bloco_completo}'")
            print(f"  >> Formato da unidade (interno): {prefixo_unidade_ident_1}xx - {prefixo_unidade_ident_2} yy")

            df_input[col_ident_1] = df_input[col_ident_1].ffill()
            df_input[col_tipologia] = df_input[col_tipologia].ffill()

            primary_unit_col = col_ident_2
            print(f"Linhas antes de dropna em '{primary_unit_col}': {len(df_input)}")
            df_input = df_input.dropna(subset=[primary_unit_col])
            df_input = df_input[df_input[primary_unit_col].astype(str).str.strip() != '']
            df_input = df_input.reset_index(drop=True)
            print(f"Linhas após dropna em '{primary_unit_col}': {len(df_input)}")
            if df_input.empty: raise ValueError(f"Nenhuma linha válida encontrada sem valor em '{primary_unit_col}'.")
            
            df_output = pd.DataFrame(index=df_input.index)

            # <<< MODIFICADO >>>
            # Usa a nova função para formatar a coluna BLOCO
            df_output['BLOCO'] = df_input[col_ident_1].apply(
                formatar_nome_bloco_saida,
                prefixo_completo=prefixo_coluna_bloco_completo
            )
            # <<< FIM DA MODIFICAÇÃO >>>

            df_output['UNIDADE'] = df_input.apply(
                formatar_nome_unidade_generico,
                axis=1,
                args=(col_ident_1, col_ident_2, col_tipologia, prefixo_unidade_ident_1, prefixo_unidade_ident_2)
            )

        # Processamento Comum para Ambos os Modos
        df_output['VALOR DO IMOVEL'] = df_input[selected_valor_column_name].apply(format_brl)
        df_output['ETAPA'] = 'ETAPA 01'
        df_output = df_output[['ETAPA', 'BLOCO', 'UNIDADE', 'VALOR DO IMOVEL']]

        print(f"Linhas antes de filtrar erros de unidade: {len(df_output)}")
        df_output = df_output[~df_output['UNIDADE'].str.contains("ERRO", na=False)]
        print(f"Linhas após filtrar erros de unidade: {len(df_output)}")
        if df_output.empty: raise ValueError("Nenhuma unidade pôde ser formatada corretamente.")
        
        output_csv = io.StringIO()
        df_output.to_csv(output_csv, sep=';', encoding='utf-8-sig', index=False, decimal=',', quoting=csv.QUOTE_MINIMAL)
        output_csv.seek(0)
        print("(Preço Incorporação) Processamento concluído.")
        return output_csv

    except ValueError as ve:
        print(f"(Preço Incorporação) ERRO VALIDAÇÃO: {ve}")
        traceback.print_exc()
        raise ve
    except Exception as e:
        print(f"(Preço Incorporação) ERRO INESPERADO: {e}")
        traceback.print_exc()
        raise RuntimeError(f"Erro inesperado no processamento Incorporação: {e}") from e


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
        col_area = find_column_flexible(df_input.columns, ['area', 'área', 'area privativa', 'área privativa', 'metragem'], 'ÁREA', required=True)
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

        # 8.3. Coluna VALOR À VISTA (formatada como moeda BRL) e ÁREA PRIVATIVA
        df_output['ÁREA PRIVATIVA'] = df_input[col_area].apply(format_area)
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
        colunas_finais = ['ETAPA', 'BLOCO', 'UNIDADE', 'ÁREA PRIVATIVA', 'VALOR À VISTA']
        df_output_final = df_output_filtrado[colunas_finais]
        print(f"Colunas finais selecionadas: {df_output_final.columns.tolist()}")

        # 11. Gerar CSV em memória
        output_csv = io.StringIO()
        # --- MODIFICADO: Voltar para QUOTE_MINIMAL, pois format_area agora força texto com ="..." ---
        df_output_final.to_csv(output_csv, sep=';', encoding='utf-8-sig', index=False, decimal=',', quoting=csv.QUOTE_MINIMAL)
        # --- FIM MODIFICADO ---
        output_csv.seek(0)

        print("(Preço Lote Avista) Processamento concluído. CSV gerado.")
        return output_csv

    except ValueError as ve: print(f"(Preço Lote Avista) ERRO VALIDAÇÃO: {ve}"); traceback.print_exc(); raise ve
    except Exception as e: print(f"(Preço Lote Avista) ERRO INESPERADO: {e}"); traceback.print_exc(); raise RuntimeError(f"Erro inesperado (Lote Avista): {e}") from e

# --- Função Placeholder para Tabela Lote Parcelado ---
def processar_preco_lote_parcelado(input_file_object, num_meses, juros_anual_perc, num_anos_parcelas): # <<< Assinatura Atualizada
    """
    Lê Excel lote parcelado, calcula parcelas até o ano especificado pelo usuário,
    filtra e retorna StringIO CSV.
    """
    print(f"(Preço Lote Parcelado) Iniciando. Meses: {num_meses}, Juros: {juros_anual_perc}%, Anos Parcelas: {num_anos_parcelas}")
    try:
        # Validação inicial dos parâmetros numéricos
        if num_meses <= 0:
            raise ValueError("Quantidade de meses deve ser maior que zero.")
        if juros_anual_perc < 0:
            raise ValueError("Porcentagem de juros anual não pode ser negativa.")
        if num_anos_parcelas <= 0:
            raise ValueError("Número de anos das parcelas deve ser maior que zero.")
        # Converte juros para multiplicador (ex: 10% -> 1.10)
        juros_multiplier = 1.0 + (juros_anual_perc / 100.0)
        print(f"Multiplicador de juros anual calculado: {juros_multiplier:.4f}")

        # 1. Leitura do Excel (leitura revisada para merged cells)
        linhas_para_ignorar = 2
        try:
            df_raw = pd.read_excel(input_file_object, engine='openpyxl', header=None, dtype=str)
            if df_raw.empty: raise ValueError("Arquivo Excel parece estar vazio.")
            print(f"(Preço Lote Parcelado) Lidas {len(df_raw)} linhas brutas.")
        except Exception as e_read:
            raise ValueError(f"Falha ao ler o stream/objeto Excel inicial (Lote Parcelado).") from e_read

        # 2. Encontrar Linha do Cabeçalho e Coluna Quadra
        header_row_index = -1
        possible_headers = ['lote', 'tipo', 'area', 'valor', 'entrada'] # Keywords para header
        for idx, row in df_raw.head(10).iterrows():
            row_values_norm = [normalize_text_for_match(str(v)) for v in row.values if pd.notna(v)]
            if sum(h in row_values_norm for h in possible_headers) >= 3: header_row_index = idx; break
        if header_row_index == -1: raise ValueError("Não foi possível encontrar a linha do cabeçalho.")
        print(f"Cabeçalho encontrado índice: {header_row_index}")

        quadra_col_index = -1; keyword_quadra = normalize_text_for_match('quadra')
        search_rows = [header_row_index] if header_row_index == 0 else [header_row_index-1, header_row_index]
        for r_idx in search_rows:
             if r_idx < 0: continue
             for c_idx, val in df_raw.iloc[r_idx].items():
                 if pd.notna(val) and keyword_quadra in normalize_text_for_match(str(val)): quadra_col_index = c_idx; break
             if quadra_col_index != -1: break
        if quadra_col_index == -1: raise ValueError("Não foi possível encontrar a coluna 'QUADRA'.")
        print(f"Coluna Quadra índice: {quadra_col_index}")

        # 3. Aplicar ffill na Quadra nos Dados Brutos
        print(f"Aplicando ffill na coluna bruta índice {quadra_col_index}")
        df_raw[quadra_col_index] = df_raw[quadra_col_index].ffill()

        # 4. Criar DataFrame Limpo (df_input)
        new_columns = df_raw.iloc[header_row_index].astype(str).str.strip(); df_input = df_raw.iloc[header_row_index + 1:].copy(); df_input.columns = new_columns; df_input = df_input.reset_index(drop=True)
        print(f"Colunas limpas: {df_input.columns.tolist()}")

        # 5. Identificar Colunas Essenciais no DF Limpo
        print("--- Buscando Colunas (Lote Parcelado) ---")
        col_quadra = new_columns[quadra_col_index] # Pega o nome da coluna Quadra
        col_lote = find_column_flexible(df_input.columns, ['lote', 'lt', 'unidade'], 'LOTE', required=True)
        # Busca coluna de VALOR (total) - pode ser só "Valor"
        col_valor_total = find_column_flexible(df_input.columns, ['valor'], 'VALOR (Total)', required=True)
        col_entrada = find_column_flexible(df_input.columns, ['entrada', 'sinal'], 'ENTRADA', required=True)
        print("--- Fim da Busca ---")

        # 6. Remover Linhas Inválidas (sem Lote)
        print(f"Linhas antes dropna(lote): {len(df_input)}")
        df_input = df_input.dropna(subset=[col_lote]).reset_index(drop=True)
        print(f"Linhas após dropna(lote): {len(df_input)}")
        if df_input.empty: raise ValueError("Nenhuma linha com Lote encontrada.")
        # Preenche NaNs restantes na Quadra (se houver)
        if df_input[col_quadra].isnull().any():
            print(f"AVISO: Preenchendo NaNs restantes em '{col_quadra}'")
            df_input[col_quadra] = df_input[col_quadra].fillna('QUADRA_DESCONHECIDA')

        # 7. Construir DataFrame de Saída e Calcular Parcelas
        df_output = pd.DataFrame(index=df_input.index)

        # 7.1 Colunas Fixas/Formatadas
        df_output['ETAPA'] = 'ETAPA 01'
        quadra_num_extraido = df_input[col_quadra].fillna('').astype(str).str.extract(r'(\d+)', expand=False)
        quadra_int = pd.to_numeric(quadra_num_extraido, errors='coerce').fillna(0).astype(int); quadra_formatada_num = quadra_int.apply(lambda x: f"{x:02d}")
        df_output['BLOCO'] = quadra_formatada_num.apply(lambda x: f'="QUADRA {x}"')
        lote_formatado_num = df_input[col_lote].fillna('').astype(str).str.extract(r'(\d+)', expand=False).fillna('0').astype(int).apply(lambda x: f"{x:02d}")
        df_output['UNIDADE'] = "QD" + quadra_formatada_num + " - LOTE " + lote_formatado_num
        df_output['VALOR DO IMOVEL'] = df_input[col_valor_total].apply(format_brl) # Usa format_brl corrigido
        df_output['SINAL 1'] = df_input[col_entrada].apply(format_brl) # Usa format_brl corrigido

        # 7.2 Cálculos de Parcelas
        # Obter valores NUMÉRICOS para cálculo
        valor_numeric = df_input[col_valor_total].apply(parse_numeric)
        entrada_numeric = df_input[col_entrada].apply(parse_numeric)
        # Tratar casos onde valor ou entrada não puderam ser convertidos (pd.NA)
        valor_numeric = valor_numeric.fillna(0)
        entrada_numeric = entrada_numeric.fillna(0)
        print("Valores numéricos para cálculo (primeiras linhas):")
        print(pd.DataFrame({'Valor': valor_numeric, 'Entrada': entrada_numeric}).head().to_string())

        # Calcular Mensal Ano 01
        saldo_devedor = valor_numeric - entrada_numeric
        # Evitar divisão por zero
        mensal_ano_01_numeric = (saldo_devedor / num_meses if num_meses != 0 else 0).round(2)
        df_output['MENSAL ANO 01'] = mensal_ano_01_numeric.apply(format_brl) # Usa format_brl

        # --- LOOP MODIFICADO para usar num_anos_parcelas ---
        mensal_anterior_numeric = mensal_ano_01_numeric
        print(f"Calculando parcelas mensais de ano 02 até {num_anos_parcelas}...")
        # O loop agora vai de 2 até o número de anos informado + 1 (para incluir o último ano)
        for i in range(2, num_anos_parcelas + 1):
            mensal_atual_numeric = (mensal_anterior_numeric * juros_multiplier).round(2)
            col_name = f"MENSAL ANO {i:02d}" # Cria nome da coluna ex: MENSAL ANO 02
            df_output[col_name] = mensal_atual_numeric.apply(format_brl) # Usa format_brl
            mensal_anterior_numeric = mensal_atual_numeric # Atualiza para o próximo cálculo
        # --- FIM LOOP MODIFICADO ---

        # 8. FILTRAGEM FINAL: Remover linhas com Lote '00' E VALOR TOTAL vazio/inválido
        print(f"Linhas antes da filtragem final: {len(df_output)}")
        is_lote_00 = lote_formatado_num == "00"
        # Checa se VALOR DO IMOVEL (formatado) é vazio
        is_valor_total_vazio = df_output['VALOR DO IMOVEL'] == ''
        condicao_excluir = is_lote_00 & is_valor_total_vazio
        df_output_filtrado = df_output[~condicao_excluir].copy()
        print(f"Linhas após a filtragem final: {len(df_output_filtrado)}")

        # 9. Selecionar e Reordenar Colunas Finais (MODIFICADO)
        # Gera a lista de colunas MENSAL ANO dinamicamente até o ano especificado
        colunas_mensais = [f'MENSAL ANO {i:02d}' for i in range(1, num_anos_parcelas + 1)]
        colunas_finais_desejadas = [
            'ETAPA', 'BLOCO', 'UNIDADE', 'VALOR DO IMOVEL', 'SINAL 1'
        ] + colunas_mensais

        # Garante que todas as colunas calculadas realmente existam no df antes de selecionar
        colunas_existentes = [col for col in colunas_finais_desejadas if col in df_output_filtrado.columns]
        df_output_final = df_output_filtrado[colunas_existentes]
        print(f"Colunas finais selecionadas: {df_output_final.columns.tolist()}")

        # 10. Gerar CSV em memória
        output_csv = io.StringIO()
        df_output_final.to_csv(output_csv, sep=';', encoding='utf-8-sig', index=False, decimal=',', quoting=csv.QUOTE_MINIMAL)
        output_csv.seek(0)

        print("(Preço Lote Parcelado) Processamento concluído. CSV gerado.")
        return output_csv # Retorna StringIO para a rota tratar

    except ValueError as ve: print(f"(Preço Lote Parcelado) ERRO VALIDAÇÃO: {ve}"); traceback.print_exc(); raise ve
    except Exception as e: print(f"(Preço Lote Parcelado) ERRO INESPERADO: {e}"); traceback.print_exc(); raise RuntimeError(f"Erro inesperado (Lote Parc): {e}") from e
