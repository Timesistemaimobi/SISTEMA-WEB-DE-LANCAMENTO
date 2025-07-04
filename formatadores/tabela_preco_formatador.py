# formatadores/tabela_precos_formatador.py

import pandas as pd
import numpy as np
import io
import traceback
import openpyxl
from openpyxl.styles import PatternFill, Font, Border, Side, Alignment, Color
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
import unicodedata
import re
from collections import defaultdict
from openpyxl.utils.cell import range_boundaries

# --- Funções Auxiliares (sem alterações significativas, apenas a adição de .strip() em map_etapa abaixo) ---
def normalize_text_for_match(text):
    """Normaliza texto para busca: minúsculo, sem acentos, sem não-alfanuméricos."""
    if not isinstance(text, str): text = str(text)
    try:
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        text = text.lower()
        text = re.sub(r'[^a-z0-9]', '', text)
        return text.strip()
    except Exception:
        # Fallback para casos onde a normalização ASCII falha
        text = str(text).lower()
        text = re.sub(r'\s+', '', text) # Remove espaços
        text = re.sub(r'[^a-z0-9]', '', text) # Remove não alfanuméricos restantes
        return text.strip()

def find_column_flexible(df_columns, concept_keywords, concept_name, required=True):
    """Encontra a coluna de forma flexível por keywords."""
    normalized_input_cols = {normalize_text_for_match(col): col for col in df_columns}
    # print(f"  Buscando '{concept_name}': Keywords={concept_keywords}. Colunas Norm.: {list(normalized_input_cols.keys())}") # Debug
    found_col_name = None
    # 1. Match exato normalizado
    for keyword in concept_keywords:
        norm_keyword = normalize_text_for_match(keyword)
        if norm_keyword in normalized_input_cols:
            found_col_name = normalized_input_cols[norm_keyword]
            # print(f"    -> Match exato norm. '{norm_keyword}' para '{concept_name}'. Col original: '{found_col_name}'") # Debug
            return found_col_name
    # 2. Match parcial normalizado (prioriza início)
    potential_matches = []
    for keyword in concept_keywords:
        norm_keyword = normalize_text_for_match(keyword)
        for norm_col, orig_col in normalized_input_cols.items():
            if norm_keyword in norm_col:
                 priority = 0 if norm_col.startswith(norm_keyword) else 1
                 potential_matches.append((priority, orig_col))
                 # print(f"    -> Match parcial candidato: '{keyword}' em '{orig_col}' (Norm: '{norm_keyword}' em '{norm_col}') Prio:{priority}") # Debug
    if potential_matches:
        potential_matches.sort()
        found_col_name = potential_matches[0][1]
        # print(f"    -> Melhor match parcial para '{concept_name}'. Col original: '{found_col_name}'") # Debug
        return found_col_name
    if required:
        raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada. Keywords usadas: {concept_keywords}. Colunas disponíveis: {df_columns.tolist()}")
    else:
        # print(f"    -> Coluna opcional '{concept_name}' não encontrada.") # Debug
        return None

def extract_block_number_safe(block_value_str):
    """Extrai o primeiro número de uma string de bloco/quadra."""
    if not isinstance(block_value_str, str): block_value_str = str(block_value_str)
    match = re.search(r'\d+', block_value_str)
    if match:
        try: return int(match.group(0))
        except ValueError: return None
    return None

def parse_flexible_float(value_str):
    """Tenta converter uma string (com R$, m², ',', '.') para float."""
    if value_str is None: return None
    text = str(value_str).strip()
    if not text: return None

    # Limpeza inicial para remover símbolos comuns não numéricos
    cleaned_text = text.upper().replace('R$', '').replace('M²', '').replace('M2','').strip()

    # Verifica se contém letras após a limpeza inicial (exceto E para notação científica)
    if re.search(r'[A-DF-Z]', cleaned_text, re.IGNORECASE):
         return None # Contém letras não permitidas

    # Remove espaços internos que podem atrapalhar a conversão
    parse_ready_text = cleaned_text.replace(' ', '')

    # Lógica de conversão baseada no último separador (vírgula ou ponto)
    last_dot = parse_ready_text.rfind('.')
    last_comma = parse_ready_text.rfind(',')

    try:
        if last_comma > last_dot: # Provável decimal BR (,) - ex: 1.234,56
            num_str = parse_ready_text.replace('.', '').replace(',', '.')
        elif last_dot > last_comma: # Provável decimal US (.) - ex: 1,234.56
            num_str = parse_ready_text.replace(',', '')
        # Casos onde só há um tipo de separador ou nenhum
        elif last_comma != -1 and last_dot == -1: # Só vírgula
             # Trata múltiplos como separador de milhar US (ex: 1,234,567)
             if parse_ready_text.count(',') > 1:
                 num_str = parse_ready_text.replace(',', '')
             else: # Trata como decimal BR (ex: 1,5)
                 num_str = parse_ready_text.replace(',', '.')
        elif last_dot != -1 and last_comma == -1: # Só ponto
              # Trata múltiplos como separador de milhar BR (ex: 1.234.567)
              if parse_ready_text.count('.') > 1:
                  num_str = parse_ready_text.replace('.', '')
              else: # Trata como decimal US (ex: 1.5)
                  num_str = parse_ready_text
        else: # Nenhum separador decimal claro ou apenas dígitos
            num_str = parse_ready_text

        # Remove qualquer caractere não numérico restante exceto '-' no início e 'E'/'e' para notação científica
        num_str = re.sub(r'[^-0-9.eE]', '', num_str)

        result = float(num_str)
        return result
    except (ValueError, TypeError):
        # print(f"AVISO: Falha na conversão final de '{text}' para float.") # Debug
        return None

def format_garagem_vagas(original_value_str, numeric_value):
    """Formata informação de garagem (faixas por m² ou texto original)."""
    original_clean_str = str(original_value_str).strip()
    if not original_clean_str or original_clean_str.lower() == 'none': return "01 VAGA" # Considera 'none' como 1 vaga
    if numeric_value is not None:
        try:
            gn = numeric_value
            if gn > 35: return "04 VAGAS"
            elif gn > 25: return "03 VAGAS"
            elif gn > 15: return "02 VAGAS"
            elif gn >= 0: return "01 VAGA"
            else: return "01 VAGA" # Fallback para valores negativos?
        except Exception as e:
            print(f"AVISO: Erro ao categorizar garagem com valor numérico {numeric_value}: {e}")
            return original_clean_str # Retorna original em caso de erro na lógica
    else:
        # Se não for numérico e não for vazio/'none', retorna o texto original
        return original_clean_str

def extract_stage_number(stage_name_str):
    """Extrai o primeiro número de uma string de etapa."""
    if not isinstance(stage_name_str, str): stage_name_str = str(stage_name_str)
    match = re.search(r'\d+', stage_name_str)
    if match:
        try: return int(match.group(0))
        except ValueError: return float('inf') # Retorna infinito se não converter
    return float('inf') # Retorna infinito se não achar número

def format_area_m2(numeric_value):
    """Formata um valor numérico como 'XXX,XX m²'. Retorna '--' se None, 0 ou inválido."""
    if numeric_value is None or pd.isna(numeric_value):
        return "--"
    try:
        val = float(numeric_value)
        # Usar np.isclose para comparar float com zero de forma segura
        if np.isclose(val, 0):
            return "--"
        # Usa formatação de string f para garantir duas casas decimais e substitui ponto por vírgula
        return f"{val:.2f}".replace('.', ',') + " m²"
    except (ValueError, TypeError):
        print(f"AVISO: Erro ao formatar valor de área {numeric_value}. Retornando '--'.")
        return "--"

# <<< INÍCIO DA MODIFICAÇÃO: Nova função auxiliar para o formato composto >>>
def format_composite_unit_name(row):
    """Gera o nome da unidade no formato BL/US-QD-CS, lendo direto do DataFrame intermediário."""
    try:
        # Lê os valores das colunas usando os nomes dos CONCEITOS
        quadra_val = str(row.get('QUADRA_COMPOSITE', ''))
        bloco_val = str(row.get('BLOCO_COMPOSITE', ''))
        casa_val = str(row.get('CASA_COMPOSITE', ''))

        quadra_num = extract_block_number_safe(quadra_val)
        bloco_num = extract_block_number_safe(bloco_val)
        casa_num = extract_block_number_safe(casa_val)

        quadra_str = f"QD{quadra_num:02d}" if quadra_num is not None else "QD??"
        casa_str = f"CS{casa_num:02d}" if casa_num is not None else "CS??"
        
        prefixo_str = ""
        # Verifica se o valor da coluna Bloco é exatamente 'US' (ignorando case e espaços)
        if bloco_val.strip().upper() == 'US':
            # Se for 'US', o número vem da casa
            prefixo_str = f"US{casa_num:02d}" if casa_num is not None else "US??"
        else:
            # Para qualquer outro valor (número do bloco), usa 'BL'
            prefixo_str = f"BL{bloco_num:02d}" if bloco_num is not None else "BL??"
        
        return f"{prefixo_str}-{quadra_str}-{casa_str}"

    except Exception as e:
        print(f"AVISO: Erro ao gerar nome de unidade composto: {e}")
        return "ERRO_UNIDADE"


# --- Função Principal de Processamento (REVISADA) ---

def processar_tabela_precos_web(input_filepath, block_etapa_mapping):
    """
    Processa a tabela de preços, adaptando a saída para loteamentos e incluindo colunas extras,
    com formatação Excel aprimorada usando Table Styles.

    Args:
        input_filepath (str): Caminho para o arquivo Excel ou CSV de entrada.
        block_etapa_mapping (dict): Dicionário mapeando nome original do bloco/quadra para nome da etapa.

    Returns:
        io.BytesIO: Stream de bytes contendo o arquivo Excel (.xlsx) formatado.

    Raises:
        ValueError: Se colunas obrigatórias não forem encontradas ou se o arquivo for ilegível.
        RuntimeError: Para erros inesperados durante o processamento.
    """
    print(f"(Tabela Preços Formatador - v_Lote_Extras_Refined) Iniciando: {input_filepath}")

    try:
        # 1. Leitura Robusta do Arquivo (Excel/CSV)
        df_input = None
        file_type_used = None
        try:
            df_input = pd.read_excel(input_filepath, engine='openpyxl', skiprows=2, header=0, dtype=str)
            file_type_used = "Excel (header linha 3)"
        except Exception as e_excel_h3:
            # print(f"  Falha ao ler como Excel (header linha 3): {e_excel_h3}. Tentando header linha 1.") # Debug
            try:
                df_input = pd.read_excel(input_filepath, engine='openpyxl', header=0, dtype=str)
                file_type_used = "Excel (header linha 1)"
            except Exception as e_excel_h1:
                 # print(f"  Falha ao ler como Excel (header linha 1): {e_excel_h1}. Tentando CSV.") # Debug
                 try:
                    # Tenta CSV com separador ';' e decimal ',' (Comum no Brasil)
                    df_input = pd.read_csv(input_filepath, sep=';', decimal=',', encoding='utf-8', header=0, dtype=str, skipinitialspace=True)
                    file_type_used = "CSV (sep=';', dec=',', enc='utf-8')"
                 except Exception as e_csv_1:
                    # print(f"  Falha ao ler como CSV padrão BR: {e_csv_1}. Tentando CSV com ',' e '.'.") # Debug
                    try:
                        # Tenta CSV com separador ',' e decimal '.' (Mais comum internacionalmente)
                        df_input = pd.read_csv(input_filepath, sep=',', decimal='.', encoding='utf-8', header=0, dtype=str, skipinitialspace=True)
                        file_type_used = "CSV (sep=',', dec='.', enc='utf-8')"
                    except Exception as e_csv_2:
                        raise ValueError(f"Não foi possível ler o arquivo '{input_filepath}' como Excel (headers linha 1 ou 3) ou CSV (padrões testados). Verifique o formato. Erro final CSV: {e_csv_2}")

        print(f"  Arquivo lido com sucesso como: {file_type_used}")

        # As colunas que são tipicamente mescladas (bloco, quadra) precisam ser preenchidas para baixo.
        # Primeiro, identificamos os nomes originais dessas colunas no DataFrame.
        cols_to_ffill = []
        # Usamos `find_column_flexible` para encontrar os nomes reais das colunas de bloco e quadra.
        bloco_col_ffill = find_column_flexible(df_input.columns, ['bloco'], 'Bloco for ffill', required=False)
        quadra_col_ffill = find_column_flexible(df_input.columns, ['quadra'], 'Quadra for ffill', required=False)
        
        if bloco_col_ffill: cols_to_ffill.append(bloco_col_ffill)
        if quadra_col_ffill: cols_to_ffill.append(quadra_col_ffill)

        if cols_to_ffill:
            print(f"  Aplicando forward-fill (preenchimento de células mescladas) para as colunas: {cols_to_ffill}")
            # Substituímos strings vazias por NaN para que ffill funcione em ambos os casos.
            df_input[cols_to_ffill] = df_input[cols_to_ffill].replace('', np.nan)
            # Aplicamos o preenchimento progressivo.
            df_input[cols_to_ffill] = df_input[cols_to_ffill].ffill()
            
        df_input = df_input.fillna('') # Garante que não há NaNs literais, substituindo por string vazia
        df_input.columns = df_input.columns.str.strip() # Limpa nomes das colunas

        # Remove linhas completamente vazias que podem ter sido lidas
        df_input.dropna(how='all', inplace=True)
        if df_input.empty:
            raise ValueError("O arquivo parece estar vazio ou não contém dados após a leitura.")

        print("--- Mapeamento de Colunas (Etapa 1: Detecção de Modo) ---")
        found_columns_map = {}
        
        # 2.1. ETAPA 1: Tenta encontrar as colunas do modo composto primeiro.
        composite_concepts_to_check = {
            'QUADRA_COMPOSITE': ['quadra'],
            'BLOCO_COMPOSITE': ['bloco'],
            'CASA_COMPOSITE': ['casa'],
        }
        for concept, keywords in composite_concepts_to_check.items():
            found_name = find_column_flexible(df_input.columns, keywords, concept, required=False)
            if found_name:
                found_columns_map[concept] = found_name

        # Decide se o modo composto está ativo
        is_composite_unit_mode = all(k in found_columns_map for k in composite_concepts_to_check.keys())
        if is_composite_unit_mode:
            print(">>> DETECTADO: Modo de Unidade Composta (QUADRA, BLOCO, CASA) ativado.")
            # A coluna de agrupamento principal será a de Bloco do modo composto
            found_columns_map['BLOCO'] = found_columns_map['BLOCO_COMPOSITE']
        
        print("--- Mapeamento de Colunas (Etapa 2: Mapeamento Padrão) ---")
        # 2.2. ETAPA 2: Mapeia as colunas padrão, ajustando as keywords e requisitos com base no modo detectado.
        
        # Define os conceitos padrão
        standard_concepts = {
            'BLOCO': (['bloco', 'blk'], True),
            'UNIDADE': (['apt', 'apto', 'apartamento', 'unidade', 'unid', 'ap'], True), # Keywords base
            'TIPOLOGIA': (['tipologia', 'tipo', 'descricao', 'descrição'], False),
            'AREA_CONSTRUIDA': (['area construida', 'área construída', 'areaconstruida', 'area util', 'área útil', 'area privativa', 'área privativa', 'área'], True),
            'QUINTAL': (['quintal', 'jardim'], False),
            'GARAGEM': (['garagem', 'vaga'], False),
            'VALOR': (['valor', 'preco', 'preço'], False)
        }

        # Condicionalmente adiciona 'casa' e 'lote' às keywords de UNIDADE
        if not is_composite_unit_mode:
            print("   -> Modo padrão. 'casa' e 'lote' são keywords válidas para UNIDADE.")
            standard_concepts['UNIDADE'][0].extend(['casa', 'lote'])

        # Loop para mapear os conceitos padrão
        for concept, (keywords, is_required) in standard_concepts.items():
            # Pula o mapeamento de conceitos que já foram definidos pelo modo composto (ex: BLOCO)
            if concept in found_columns_map:
                continue

            # Ajusta a obrigatoriedade da coluna UNIDADE
            final_requirement = is_required
            if concept == 'UNIDADE' and is_composite_unit_mode:
                final_requirement = False # No modo composto, a coluna UNIDADE padrão não é obrigatória

            found_name = find_column_flexible(df_input.columns, keywords, concept, required=final_requirement)
            if found_name:
                found_columns_map[concept] = found_name
        
        # Validação final de colunas obrigatórias
        if is_composite_unit_mode:
            # Já validado pela detecção
            pass
        elif 'UNIDADE' not in found_columns_map:
             raise ValueError("Coluna 'UNIDADE' (ou apt, casa, lote, etc.) é obrigatória e não foi encontrada.")
        if 'BLOCO' not in found_columns_map:
             raise ValueError("Coluna 'BLOCO' (ou quadra) é obrigatória e não foi encontrada.")

        print("--- Mapeamento de Colunas Padrão Encontradas ---")
        print(found_columns_map)
        print("-" * 30)

        # --- Identificar Colunas Extras (não mapeadas como padrão) ---
        mapped_original_names = set(found_columns_map.values())
        extra_col_names = [
            col for col in df_input.columns if col not in mapped_original_names and col
        ]
        if extra_col_names:
            print(f"--- Colunas Extras Identificadas ---")
            print(extra_col_names)
            print("-" * 30)

        # --- Detecção de Lote (Baseado na coluna UNIDADE encontrada) ---
        col_unidade_nome = found_columns_map.get('UNIDADE')
        is_lote_file = False
        # <<< INÍCIO DA MODIFICAÇÃO: A detecção de lote só ocorre se não estivermos no modo composto >>>
        if not is_composite_unit_mode and col_unidade_nome and col_unidade_nome in df_input.columns:
            if df_input[col_unidade_nome].astype(str).str.contains('lote', case=False, na=False).any():
                is_lote_file = True
                print(">>> DETECTADO: Arquivo parece ser de LOTEAMENTO (encontrado 'lote' na coluna Unidade). Saída será adaptada.")
        elif not is_composite_unit_mode:
             print("AVISO: Coluna 'UNIDADE' não encontrada ou não mapeada corretamente. Não é possível detectar modo Lote automaticamente.")
        # <<< FIM DA MODIFICAÇÃO >>>


        # 3. Preparar DataFrame Intermediário (Incluindo Dados Extras)
        df_intermediate = pd.DataFrame()
        for concept, original_col_name in found_columns_map.items():
             df_intermediate[concept] = df_input[original_col_name].astype(str).copy()
        for extra_col_name in extra_col_names:
            df_intermediate[extra_col_name] = df_input[extra_col_name].astype(str).copy()

        col_bloco_orig_found = found_columns_map.get('BLOCO')
        if not col_bloco_orig_found: raise ValueError("Coluna Bloco/Quadra obrigatória não foi encontrada.")

        if col_bloco_orig_found not in df_input.columns:
             raise ValueError(f"Erro interno: Coluna de bloco '{col_bloco_orig_found}' mapeada mas não encontrada no DataFrame de entrada.")

        df_intermediate['BLOCO_ORIGINAL'] = df_input[col_bloco_orig_found].astype(str)
        df_intermediate['BLOCO_ORIGINAL'] = df_intermediate['BLOCO_ORIGINAL'].replace('', np.nan).ffill()
        df_intermediate.dropna(subset=['BLOCO_ORIGINAL'], inplace=True)

        # <<< INÍCIO DA MODIFICAÇÃO: A validação de UNIDADE muda >>>
        # Se não for modo composto, a unidade é obrigatória. Se for, a casa é obrigatória.
        if is_composite_unit_mode:
            if 'CASA_COMPOSITE' not in df_intermediate.columns:
                raise ValueError("Modo Composto ativo, mas coluna 'CASA_COMPOSITE' não foi encontrada no df_intermediate.")
            df_intermediate = df_intermediate[df_intermediate['CASA_COMPOSITE'].astype(str).str.strip() != '']
        else:
            if 'UNIDADE' not in df_intermediate.columns:
                 raise ValueError("Coluna 'UNIDADE' é obrigatória e não foi encontrada ou mapeada.")
            df_intermediate = df_intermediate[df_intermediate['UNIDADE'].astype(str).str.strip() != '']
        
        if df_intermediate.empty:
            raise ValueError("Não foram encontrados dados válidos (com Bloco e Unidade/Casa preenchidos) no arquivo.")
        # <<< FIM DA MODIFICAÇÃO >>>

        def map_etapa(bloco_original):
            bloco_str = str(bloco_original).strip()
            if not bloco_str or bloco_str.lower() == 'nan': return "ETAPA_NAO_MAPEADA"
            return block_etapa_mapping.get(bloco_str, "ETAPA_NAO_MAPEADA")

        df_intermediate['ETAPA_MAPEADA'] = df_intermediate['BLOCO_ORIGINAL'].apply(map_etapa)
        unmapped_blocks = df_intermediate[df_intermediate['ETAPA_MAPEADA'] == "ETAPA_NAO_MAPEADA"]['BLOCO_ORIGINAL'].unique()
        if len(unmapped_blocks) > 0:
            print(f"AVISO: Os seguintes Blocos/Quadras não foram encontrados no mapeamento de etapas: {list(unmapped_blocks)}")

        # 4. Agrupar e Ordenar Blocos por Etapa
        etapas_agrupadas = defaultdict(list)
        valid_blocks = df_intermediate[['BLOCO_ORIGINAL', 'ETAPA_MAPEADA']].dropna().drop_duplicates()
        for _, row in valid_blocks.iterrows():
            etapa, bloco = row['ETAPA_MAPEADA'], row['BLOCO_ORIGINAL']
            if pd.notna(bloco) and str(bloco).strip().lower() != 'nan' and str(bloco).strip() != '':
                 etapas_agrupadas[etapa].append(str(bloco).strip())
            else:
                 print(f"Aviso: Bloco inválido ('{bloco}') encontrado para etapa '{etapa}', ignorando agrupamento.")

        etapas_ordenadas = sorted(etapas_agrupadas.keys(), key=lambda e: (extract_stage_number(e), e))
        blocos_ordenados_por_etapa = {}
        for etapa in etapas_ordenadas:
            blocos_da_etapa = list(set(etapas_agrupadas[etapa]))
            blocos_ordenados_por_etapa[etapa] = sorted(
                blocos_da_etapa,
                key=lambda b: (extract_block_number_safe(b) if extract_block_number_safe(b) is not None else float('inf'), b)
            )

        # 5. Construir Estrutura de Dados para Saída Excel
        print(f"--- Montando Saída (Modo Lote: {is_lote_file}, Modo Composto: {is_composite_unit_mode}, Extras: {bool(extra_col_names)}) ---")
        
        if is_lote_file:
            output_concepts_base = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA']
            if 'VALOR' in found_columns_map: output_concepts_base.append('VALOR')
        else:
            # <<< INÍCIO DA MODIFICAÇÃO: A coluna 'UNIDADE' é sempre a primeira, seja ela composta ou simples >>>
            standard_concepts_order = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
            # Se em modo composto, garantimos que 'UNIDADE' estará na saída.
            # As colunas de composição não precisam estar na lista, pois não serão exibidas individualmente.
            output_concepts_base = []
            
            # Adiciona 'UNIDADE' primeiro. No modo composto, ela será gerada dinamicamente.
            output_concepts_base.append('UNIDADE')

            # Adiciona os outros conceitos se foram encontrados
            for c in standard_concepts_order:
                if c != 'UNIDADE' and c in found_columns_map:
                    output_concepts_base.append(c)
            # <<< FIM DA MODIFICAÇÃO >>>

        final_output_identifiers = output_concepts_base + extra_col_names

        header_map = {
            'UNIDADE': 'UNIDADE', 'TIPOLOGIA': 'TIPOLOGIA', 'AREA_CONSTRUIDA': 'ÁREA CONSTRUÍDA', # Corrigido para acento
            'QUINTAL': 'QUINTAL', 'GARAGEM': 'GARAGEM', 'VALOR': 'VALOR DO IMÓVEL'
        }
        output_headers = [header_map.get(identifier, identifier) for identifier in final_output_identifiers]
        
        print(f"   Colunas Finais de Saída: {output_headers}")
        num_cols = len(output_headers)
        if num_cols == 0: raise ValueError("Nenhuma coluna selecionada para a saída.")

        final_sheet_data = []
        final_sheet_data.extend([([None] * num_cols)] * 2)
        output_title = "TABELA DE PREÇOS"
        final_sheet_data.append([output_title] + [None] * (num_cols - 1))
        final_sheet_data.append([None] * num_cols)
        row_map = {'title': 3, 'etapas': {}}
        current_excel_row = len(final_sheet_data) + 1

        for etapa_idx, etapa_nome in enumerate(etapas_ordenadas):
            etapa_header_excel_row = current_excel_row
            row_map['etapas'][etapa_nome] = {'header_row': etapa_header_excel_row, 'blocks': {}}
            final_sheet_data.append([etapa_nome] + [None] * (num_cols - 1))
            final_sheet_data.append([None] * num_cols); current_excel_row += 2

            blocos_desta_etapa = blocos_ordenados_por_etapa.get(etapa_nome, [])
            for bloco_idx, bloco_val_orig in enumerate(blocos_desta_etapa):
                bloco_header_excel_row = current_excel_row
                data_header_excel_row = current_excel_row + 2
                block_num = extract_block_number_safe(bloco_val_orig)
                block_display_name = f"BLOCO {block_num:02d}" if block_num is not None else str(bloco_val_orig).upper()
                final_sheet_data.append([block_display_name] + [None] * (num_cols - 1))
                final_sheet_data.append([None] * num_cols);
                final_sheet_data.append(output_headers)
                current_excel_row += 3

                df_bloco_data = df_intermediate[df_intermediate['BLOCO_ORIGINAL'] == bloco_val_orig].copy()
                
                def extract_unit_sort_key(unit_str):
                    unit_str = str(unit_str)
                    numbers = re.findall(r'\d+', unit_str)
                    try:
                        num_part = int(numbers[0]) if numbers else float('inf')
                    except ValueError:
                        num_part = float('inf')
                    return (num_part, unit_str)

                # <<< INÍCIO DA MODIFICAÇÃO: Ordenar pela coluna correta >>>
                if is_composite_unit_mode:
                    # No modo composto, ordenamos pelo número da CASA
                    sort_col = 'CASA_COMPOSITE'
                else:
                    # No modo padrão, ordenamos pela UNIDADE
                    sort_col = 'UNIDADE'

                if sort_col in df_bloco_data.columns:
                    df_bloco_data = df_bloco_data.sort_values(by=sort_col, key=lambda col: col.apply(extract_unit_sort_key))
                # <<< FIM DA MODIFICAÇÃO >>>


                formatted_data_rows = []
                for _, row in df_bloco_data.iterrows():
                    processed_row = []
                    
                    # <<< INÍCIO DA MODIFICAÇÃO: Lógica de UNIDADE condicional >>>
                    for identifier in final_output_identifiers:
                        processed_val = '' # Valor padrão

                        if identifier == 'UNIDADE' and is_composite_unit_mode:
                            # Se for modo composto, gera o nome da unidade dinamicamente
                            processed_val = format_composite_unit_name(row)
                        else:
                            # Comportamento padrão para todas as outras colunas (incluindo UNIDADE no modo normal)
                            original_value_str = str(row.get(identifier, ''))
                            processed_val = original_value_str

                            # --- Lógica de formatação e override condicional ---
                            if identifier == 'TIPOLOGIA' and is_lote_file:
                                processed_val = "LOTEAMENTO"
                            elif identifier in ['AREA_CONSTRUIDA', 'QUINTAL']:
                                numeric_value = parse_flexible_float(original_value_str)
                                processed_val = format_area_m2(numeric_value)
                            elif identifier == 'GARAGEM':
                                numeric_value = parse_flexible_float(original_value_str)
                                processed_val = format_garagem_vagas(original_value_str, numeric_value)
                            elif identifier == 'VALOR' or identifier in extra_col_names:
                                numeric_value = parse_flexible_float(original_value_str)
                                if numeric_value is not None:
                                    processed_val = numeric_value
                                elif original_value_str.strip():
                                    processed_val = original_value_str.strip()
                                else:
                                    processed_val = None
                        
                        processed_row.append(processed_val)
                    # <<< FIM DA MODIFICAÇÃO >>>

                    formatted_data_rows.append(processed_row)

                final_sheet_data.extend(formatted_data_rows)

                data_start_excel_row = data_header_excel_row + 1
                data_end_excel_row = data_start_excel_row + len(formatted_data_rows) -1
                row_map['etapas'][etapa_nome]['blocks'][bloco_val_orig] = {
                    'bloco_header': bloco_header_excel_row,
                    'data_header': data_header_excel_row,
                    'data_start': data_start_excel_row,
                    'data_end': data_end_excel_row
                }
                current_excel_row = data_end_excel_row + 1

                if bloco_idx < len(blocos_desta_etapa) - 1:
                    final_sheet_data.append([None] * num_cols)
                    current_excel_row += 1

            if etapa_idx < len(etapas_ordenadas) - 1:
                final_sheet_data.append([None] * num_cols)
                current_excel_row += 1

        # 6. Escrever no Excel e Aplicar Estilos Visuais
        # O restante do código de estilização permanece IDÊNTICO, pois ele opera sobre a
        # estrutura final `final_sheet_data` e `row_map`, que foram construídos corretamente.
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_final_sheet = pd.DataFrame(final_sheet_data)
            df_final_sheet.to_excel(writer, sheet_name='Tabela Formatada', index=False, header=False)

            workbook = writer.book
            worksheet = writer.sheets['Tabela Formatada']
            print("  Aplicando estilos visuais...")

            # --- Definição de Estilos ---
            header_bg_color = "FFFFFF" # Azul claro suave
            header_font_color = "000000" # Preto
            title_bg_color = "FFFFFF" # Azul mais escuro
            title_font_color = "000000" # Branco

            title_fill = PatternFill(start_color=title_bg_color, fill_type="solid")
            header_fill = PatternFill(start_color=header_bg_color, fill_type="solid")
            title_font = Font(name='Calibri', size=11, bold=True, color=title_font_color)
            etapa_bloco_header_font = Font(name='Calibri', size=11, bold=True, color=header_font_color)
            data_header_font = Font(name='Calibri', size=11, bold=True, color=header_font_color)
            data_font = Font(name='Calibri', size=11, bold=False, color="000000")
            center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
            left_align = Alignment(horizontal='left', vertical='center', wrap_text=True)
            right_align = Alignment(horizontal='right', vertical='center', wrap_text=False)
            thin_border_side = Side(style='thin', color="B2B2B2")
            medium_border_side = Side(style='medium', color="000000")
            outer_border = Border(left=medium_border_side, right=medium_border_side, top=medium_border_side, bottom=medium_border_side)
            data_header_border = Border(left=thin_border_side, right=thin_border_side, top=medium_border_side, bottom=medium_border_side)
            data_cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
            brl_currency_format = 'R$ #,##0.00'
            text_format = '@'

            def style_merged_range(ws, cell_range_str, fill=None, font=None, alignment=None, border=None):
                min_col, min_row, max_col, max_row = range_boundaries(cell_range_str)
                top_left_cell = ws.cell(row=min_row, column=min_col)
                if fill: top_left_cell.fill = fill
                if font: top_left_cell.font = font
                if alignment: top_left_cell.alignment = alignment
                if border:
                    for row_idx in range(min_row, max_row + 1):
                        for col_idx in range(min_col, max_col + 1):
                            cell = ws.cell(row=row_idx, column=col_idx)
                            current_border = cell.border.copy()
                            if row_idx == min_row and border.top: current_border.top = border.top
                            if row_idx == max_row and border.bottom: current_border.bottom = border.bottom
                            if col_idx == min_col and border.left: current_border.left = border.left
                            if col_idx == max_col and border.right: current_border.right = border.right
                            cell.border = current_border

            title_row = row_map['title']
            title_range_str = f"A{title_row}:{get_column_letter(num_cols)}{title_row}"
            if num_cols > 0:
                worksheet.merge_cells(title_range_str)
                style_merged_range(worksheet, title_range_str, fill=title_fill, font=title_font, alignment=center_align, border=outer_border)

            currency_col_indices_1based = []
            text_col_indices_1based = []
            numeric_col_indices_1based = []
            alignment_map = {}

            for i, header_name in enumerate(output_headers):
                identifier = final_output_identifiers[i]
                col_idx_1based = i + 1
                if identifier == 'VALOR' or identifier in extra_col_names:
                    currency_col_indices_1based.append(col_idx_1based)
                    alignment_map[col_idx_1based] = right_align
                elif identifier in ['AREA_CONSTRUIDA', 'QUINTAL']:
                     text_col_indices_1based.append(col_idx_1based)
                     alignment_map[col_idx_1based] = center_align
                elif identifier in ['UNIDADE', 'TIPOLOGIA', 'GARAGEM']:
                     text_col_indices_1based.append(col_idx_1based)
                     alignment_map[col_idx_1based] = left_align if identifier in ['TIPOLOGIA'] else center_align
                if col_idx_1based not in alignment_map:
                    alignment_map[col_idx_1based] = center_align

            print(f"   Índices (1-based) Formato Moeda: {currency_col_indices_1based}")
            print(f"   Índices (1-based) Formato Texto: {text_col_indices_1based}")

            table_counter = 1
            for etapa_nome, etapa_info in row_map['etapas'].items():
                etapa_header_r = etapa_info['header_row']
                etapa_range_str = f"A{etapa_header_r}:{get_column_letter(num_cols)}{etapa_header_r}"
                if num_cols > 0:
                    worksheet.merge_cells(etapa_range_str)
                    style_merged_range(worksheet, etapa_range_str, fill=header_fill, font=etapa_bloco_header_font, alignment=center_align, border=outer_border)

                for bloco_val_orig, rows_info in etapa_info['blocks'].items():
                    bloco_header_r = rows_info['bloco_header']
                    data_header_r = rows_info['data_header']
                    data_start_r = rows_info['data_start']
                    data_end_r = rows_info['data_end']

                    bloco_range_str = f"A{bloco_header_r}:{get_column_letter(num_cols)}{bloco_header_r}"
                    if num_cols > 0:
                        worksheet.merge_cells(bloco_range_str)
                        style_merged_range(worksheet, bloco_range_str, fill=header_fill, font=etapa_bloco_header_font, alignment=center_align, border=outer_border)

                    if data_start_r <= data_end_r:
                        start_col_letter = get_column_letter(1)
                        end_col_letter = get_column_letter(num_cols)
                        table_range = f"{start_col_letter}{data_header_r}:{end_col_letter}{data_end_r}"
                        table_name = f"Tabela_{table_counter}"
                        table_counter += 1
                        tab = Table(displayName=table_name, ref=table_range)
                        style = TableStyleInfo(name="TableStyleLight1", showFirstColumn=False, showLastColumn=False, showRowStripes=True, showColumnStripes=False)
                        tab.tableStyleInfo = style
                        worksheet.add_table(tab)
                        print(f"   Aplicado Estilo Tabela '{style.name}' range {table_range} (Nome: {table_name})")

                    for c_idx_1based in range(1, num_cols + 1):
                        cell = worksheet.cell(row=data_header_r, column=c_idx_1based)
                        cell.font = data_header_font
                        cell.alignment = alignment_map.get(c_idx_1based, center_align)
                    
                    for r in range(data_start_r, data_end_r + 1):
                        for c_idx_1based in range(1, num_cols + 1):
                            cell = worksheet.cell(row=r, column=c_idx_1based)
                            cell.font = data_font
                            cell.alignment = alignment_map.get(c_idx_1based, center_align)
                            if c_idx_1based in currency_col_indices_1based and isinstance(cell.value, (int, float, np.number)):
                                cell.number_format = brl_currency_format
                            elif c_idx_1based in text_col_indices_1based:
                                 cell.number_format = text_format

                    if data_start_r <= data_end_r and num_cols > 0:
                        outer_border_start_row = data_header_r
                        outer_border_end_row = data_end_r
                        for row_idx in range(outer_border_start_row, outer_border_end_row + 1):
                            for col_idx_1based in range(1, num_cols + 1):
                                cell = worksheet.cell(row=row_idx, column=col_idx_1based)
                                current_border = cell.border.copy()
                                is_top_data_row = (row_idx == outer_border_start_row)
                                is_bottom_data_row = (row_idx == outer_border_end_row)
                                is_left_col = (col_idx_1based == 1)
                                is_right_col = (col_idx_1based == num_cols)
                                if is_top_data_row: current_border.top = medium_border_side
                                if is_bottom_data_row: current_border.bottom = medium_border_side
                                if is_left_col: current_border.left = medium_border_side
                                if is_right_col: current_border.right = medium_border_side
                                cell.border = current_border

            concept_widths = {
                'UNIDADE': 22, 'TIPOLOGIA': 40, 'ÁREA CONSTRUIDA': 15, # Aumentei UNIDADE
                'QUINTAL': 12, 'GARAGEM': 15, 'VALOR': 18
            }
            extra_widths = {}
            default_extra_width = 15

            print("   Ajustando larguras das colunas...")
            for i, header_name in enumerate(output_headers):
                col_letter = get_column_letter(i + 1)
                identifier = final_output_identifiers[i]
                width = None
                if identifier in concept_widths:
                    width = concept_widths[identifier]
                elif identifier in extra_widths:
                     width = extra_widths[identifier]
                elif identifier in header_map and header_map[identifier] in concept_widths:
                     width = concept_widths[header_map[identifier]]
                elif identifier in extra_col_names:
                    width = default_extra_width
                else:
                    width = default_extra_width
                if width:
                    try:
                        worksheet.column_dimensions[col_letter].width = width
                    except Exception as e:
                        print(f"Aviso: Falha ao ajustar largura da coluna {col_letter} ('{header_name}'): {e}")

            print("  Estilos visuais finais aplicados.")

        output.seek(0)
        print(f"(Tabela Preços Formatador - v_Lote_Extras_Refined) Processamento concluído.")
        return output

    except ValueError as ve:
        print(f"(Tabela Preços Formatador) ERRO VALIDAÇÃO: {ve}")
        traceback.print_exc()
        raise ve
    except Exception as e:
        print(f"(Tabela Preços Formatador) ERRO INESPERADO: {e}")
        traceback.print_exc()
        raise RuntimeError(f"Erro inesperado no formatador de tabela de preços: {e}") from e