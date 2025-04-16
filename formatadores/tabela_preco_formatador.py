# formatadores/tabela_precos_formatador.py

import pandas as pd
import numpy as np
import io
import traceback
import openpyxl
from openpyxl.styles import PatternFill, Font, Border, Side, Alignment, Color
from openpyxl.utils import get_column_letter
import unicodedata
import re
from collections import defaultdict
from openpyxl.utils.cell import range_boundaries

# --- Funções Auxiliares (incluindo format_area_m2) ---
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
    """Encontra a coluna de forma flexível por keywords."""
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
        print(f"    -> Melhor match parcial para '{concept_name}'. Col original: '{found_col_name}'")
        return found_col_name
    if required:
        raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada. Keywords usadas: {concept_keywords}. Colunas originais: {df_columns.tolist()}")
    else:
        print(f"    -> Coluna opcional '{concept_name}' não encontrada.")
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
    # Limpeza mais agressiva para aceitar formatos variados antes da checagem
    cleaned_text = text.upper().replace('R$', '').replace('M²', '').replace('M2','').strip()
    # Regex simplificada para verificar se parece número após limpeza inicial
    # Remove espaços internos que podem atrapalhar a regex
    check_text = cleaned_text.replace(' ','')
    match_maybe_num = re.fullmatch(r"^-?[\d.,]+$", check_text)
    if not match_maybe_num:
        return None # Contém letras ou outros símbolos não esperados

    # Se parece número, faz a conversão cuidadosa
    parse_ready_text = re.sub(r'[^\d,.-]', '', cleaned_text) # Mantém só dígitos, ',', '.', '-'
    last_dot = parse_ready_text.rfind('.')
    last_comma = parse_ready_text.rfind(',')
    try:
        if last_comma > last_dot: # Provável decimal BR (,) - ex: 1.234,56
            num_str = parse_ready_text.replace('.', '').replace(',', '.')
        elif last_dot > last_comma: # Provável decimal US (.) - ex: 1,234.56
            num_str = parse_ready_text.replace(',', '')
        elif last_comma != -1 and last_dot == -1: # Só vírgula
             if parse_ready_text.count(',') > 1: # Ex: 1,234,567 (milhar US)
                 num_str = parse_ready_text.replace(',', '')
             else: # Ex: 1,5 (decimal BR)
                 num_str = parse_ready_text.replace(',', '.')
        elif last_dot != -1 and last_comma == -1: # Só ponto
              if parse_ready_text.count('.') > 1: # Ex: 1.234.567 (milhar BR)
                  num_str = parse_ready_text.replace('.', '')
              else: # Ex: 1.5 (decimal US)
                  num_str = parse_ready_text
        else: # Nenhum separador decimal claro
            num_str = parse_ready_text

        result = float(num_str)
        return result
    except (ValueError, TypeError):
        return None # Falha na conversão final

def format_garagem_vagas(original_value_str, numeric_value):
    """Formata informação de garagem (faixas por m² ou texto original)."""
    original_clean_str = str(original_value_str).strip()
    if not original_clean_str or original_clean_str.lower() == 'none': return "01 VAGA"
    if numeric_value is not None:
        try:
            gn = numeric_value
            if gn > 35: return "04 VAGAS"
            elif gn > 25: return "03 VAGAS"
            elif gn > 15: return "02 VAGAS"
            elif gn >= 0: return "01 VAGA"
            else: return "01 VAGA" # Fallback
        except Exception as e:
            print(f"AVISO: Erro ao comparar garagem {numeric_value}: {e}")
            return original_clean_str # Retorna original em caso de erro na lógica
    else:
        # Se não for numérico, retorna o texto original
        return original_clean_str

def extract_stage_number(stage_name_str):
    """Extrai o primeiro número de uma string de etapa."""
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
        if np.isclose(val, 0):
            return "--"
        return f"{val:.2f}".replace('.', ',') + " m²"
    except (ValueError, TypeError):
        print(f"AVISO: Erro ao formatar valor de área {numeric_value}. Retornando '--'.")
        return "--"

# --- Função Principal de Processamento (MODIFICADA p/ Lotes E Colunas Extras) ---

def processar_tabela_precos_web(input_filepath, block_etapa_mapping):
    """
    Processa a tabela de preços, adaptando a saída para loteamentos e incluindo colunas extras.

    Args:
        input_filepath (str): Caminho para o arquivo Excel ou CSV de entrada.
        block_etapa_mapping (dict): Dicionário mapeando nome original do bloco/quadra para nome da etapa.

    Returns:
        io.BytesIO: Stream de bytes contendo o arquivo Excel (.xlsx) formatado.

    Raises:
        ValueError: Se colunas obrigatórias não forem encontradas ou se o arquivo for ilegível.
        RuntimeError: Para erros inesperados durante o processamento.
    """
    print(f"(Tabela Preços Formatador - v_Lote_Extras) Iniciando: {input_filepath}")

    try:
        # 1. Leitura Robusta do Arquivo (Excel/CSV)
        df_input = None
        try:
            # Tenta Excel com header na linha 3 (skiprows=2)
            df_input = pd.read_excel(input_filepath, engine='openpyxl', skiprows=2, header=0, dtype=str)
            print("  Lido como Excel (header linha 3).")
        except Exception as e_excel_h3:
            print(f"  Falha ao ler como Excel (header linha 3): {e_excel_h3}. Tentando header linha 1.")
            try:
                # Tenta Excel com header na linha 1 (header=0)
                df_input = pd.read_excel(input_filepath, engine='openpyxl', header=0, dtype=str)
                print("  Lido como Excel (header linha 1).")
            except Exception as e_excel_h1:
                 print(f"  Falha ao ler como Excel (header linha 1): {e_excel_h1}. Tentando CSV.")
                 try:
                    # Tenta CSV com parâmetros padrão (idealmente viriam do app.py)
                    df_input = pd.read_csv(input_filepath, sep=';', decimal=',', encoding='utf-8', header=0, dtype=str, skipinitialspace=True)
                    print("  Lido como CSV (padrão ';', ',', 'utf-8').")
                 except Exception as e_csv:
                     # Se tudo falhar, lança erro claro
                     raise ValueError(f"Não foi possível ler o arquivo '{input_filepath}' como Excel (linhas 1 ou 3) ou CSV padrão. Verifique o formato. Erro final: {e_csv}")

        df_input = df_input.fillna('') # Garante que não há NaNs literais
        df_input.columns = df_input.columns.str.strip() # Limpa nomes das colunas

        # 2. Definir Conceitos Padrão e Encontrar Colunas Correspondentes
        col_concepts = {
            'BLOCO': (['bloco', 'blk', 'quadra'], True),
            'UNIDADE': (['apt', 'apto', 'apartamento', 'unidade', 'casa', 'unid', 'ap', 'lote'], True),
            'TIPOLOGIA': (['tipologia', 'tipo', 'descricao', 'descrição'], False),
            'AREA_CONSTRUIDA': (['area construida', 'área construída', 'areaconstruida', 'area util', 'área útil', 'area privativa', 'área privativa', 'área'], True),
            'QUINTAL': (['quintal', 'jardim', 'area descoberta', 'área descoberta', 'area externa', 'área externa', 'quintal m2', 'jardim m2'], False), # Opcional
            'GARAGEM': (['garagem', 'vaga', 'vagas', 'estacionamento'], False), # Opcional
            'VALOR': (['valor', 'preco', 'preço', 'valor imovel', 'valor do imóvel', 'valor venda', 'valor do imovel (1x)', 'valor do imovel 1x', 'valor a vista', 'valorávista'], False)
        }
        found_columns_map = {} # Mapeia CONCEITO -> NOME_ORIGINAL_ENCONTRADO
        print("--- Buscando Colunas Padrão ---")
        for concept, (keywords, is_required) in col_concepts.items():
             # **** CORRIGIR AQUI ****
             # Passar df_input.columns diretamente
             found_name = find_column_flexible(df_input.columns, keywords, concept, required=is_required)
             # **** FIM DA CORREÇÃO ****
             if found_name:
                found_columns_map[concept] = found_name
        print("--- Mapeamento de Colunas Padrão Encontradas ---")
        print(found_columns_map)
        print("-" * 30)

        # --- Identificar Colunas Extras (não mapeadas como padrão) ---
        mapped_original_names = set(found_columns_map.values())
        extra_col_names = [
            col for col in df_input.columns if col not in mapped_original_names
        ]
        if extra_col_names:
            print(f"--- Colunas Extras Identificadas ---")
            print(extra_col_names)
            print("-" * 30)
        # --- Fim Identificar Extras ---

        # --- Detecção de Lote (Baseado na coluna UNIDADE encontrada) ---
        col_unidade_nome = found_columns_map.get('UNIDADE')
        is_lote_file = False
        if col_unidade_nome and col_unidade_nome in df_input.columns:
            # Verifica se *alguma* célula na coluna UNIDADE contém 'lote'
            if df_input[col_unidade_nome].astype(str).str.contains('lote', case=False, na=False).any():
                is_lote_file = True
                print(">>> DETECTADO: Arquivo contém 'LOTE'. Saída adaptada (sem Quintal/Garagem, Tipologia='LOTEAMENTO').")
        else:
            # Se a coluna UNIDADE não foi encontrada (apesar de ser obrigatória), assume que não é lote
            print("AVISO: Coluna 'UNIDADE' não encontrada, não é possível detectar modo Lote.")
        # --- Fim Detecção Lote ---

        # 3. Preparar DataFrame Intermediário (Incluindo Dados Extras)
        df_intermediate = pd.DataFrame()
        # Copia dados das colunas padrão encontradas, usando o CONCEITO como chave
        for concept, original_col_name in found_columns_map.items():
             df_intermediate[concept] = df_input[original_col_name].astype(str).copy()
        # Copia dados das colunas extras, usando o NOME ORIGINAL como chave
        for extra_col_name in extra_col_names:
            df_intermediate[extra_col_name] = df_input[extra_col_name].astype(str).copy()

        # Adiciona colunas auxiliares (Bloco Original, Etapa Mapeada)
        col_bloco_orig_found = found_columns_map.get('BLOCO')
        if not col_bloco_orig_found: raise ValueError("Coluna Bloco/Quadra obrigatória não foi encontrada.")
        df_intermediate['BLOCO_ORIGINAL'] = df_input[col_bloco_orig_found].astype(str)
        # Propaga valores de bloco para baixo (ffill) para tratar células mescladas ou vazias
        df_intermediate['BLOCO_ORIGINAL'] = df_intermediate['BLOCO_ORIGINAL'].replace('', np.nan).ffill()
        # Remove linhas que possam ter ficado sem bloco após o ffill (ex: linhas antes do primeiro bloco)
        df_intermediate.dropna(subset=['BLOCO_ORIGINAL'], inplace=True)

        # Mapeia a etapa usando o dicionário fornecido
        def map_etapa(bloco_original):
            if pd.isna(bloco_original) or str(bloco_original).lower() == 'nan': return "ETAPA_NAO_MAPEADA"
            # Usa .strip() para remover espaços extras no nome do bloco antes de mapear
            return block_etapa_mapping.get(str(bloco_original).strip(), "ETAPA_NAO_MAPEADA")
        df_intermediate['ETAPA_MAPEADA'] = df_intermediate['BLOCO_ORIGINAL'].apply(map_etapa)

        # Alerta sobre blocos não mapeados
        if "ETAPA_NAO_MAPEADA" in df_intermediate['ETAPA_MAPEADA'].unique():
            blocos_nao_mapeados = df_intermediate[df_intermediate['ETAPA_MAPEADA'] == "ETAPA_NAO_MAPEADA"]['BLOCO_ORIGINAL'].unique()
            print(f"Aviso: Blocos não mapeados encontrados: {blocos_nao_mapeados}.")

        # 4. Agrupar e Ordenar Blocos por Etapa (para estrutura da planilha)
        etapas_agrupadas = defaultdict(list)
        # Usa drop_duplicates para pegar combinações únicas de Bloco/Etapa
        for _, row in df_intermediate[['BLOCO_ORIGINAL', 'ETAPA_MAPEADA']].drop_duplicates().iterrows():
            etapa, bloco = row['ETAPA_MAPEADA'], row['BLOCO_ORIGINAL']
            # Garante que blocos inválidos (NaN, 'nan') não entrem no agrupamento
            if pd.notna(bloco) and str(bloco).lower() != 'nan':
                 etapas_agrupadas[etapa].append(bloco)
            else:
                 print(f"Aviso: Bloco inválido ('{bloco}') encontrado para etapa '{etapa}', ignorando agrupamento.")
        # Ordena as etapas (numericamente se possível, senão alfabeticamente)
        etapas_ordenadas = sorted(etapas_agrupadas.keys(), key=lambda e: (extract_stage_number(e), e))
        # Ordena os blocos dentro de cada etapa (numericamente se possível)
        blocos_ordenados_por_etapa = {}
        for etapa in etapas_ordenadas:
            blocos_da_etapa = etapas_agrupadas[etapa]
            blocos_ordenados_por_etapa[etapa] = sorted(
                blocos_da_etapa,
                key=lambda b: extract_block_number_safe(b) if extract_block_number_safe(b) is not None else float('inf')
            )

        # 5. Construir Estrutura de Dados para Saída Excel (Dinâmica)
        print(f"--- Montando Saída (Modo Lote: {is_lote_file}, Extras: {bool(extra_col_names)}) ---")
        # Define a lista base de conceitos para a saída (com ou sem Quintal/Garagem)
        if is_lote_file:
            # Ordem para Lotes (sem Quintal/Garagem)
            output_concepts_base = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA', 'VALOR']
        else:
            # Ordem Padrão (inclui opcionais se foram encontrados no passo 2)
            standard_concepts_order = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
            # Filtra para incluir apenas os conceitos que TEM uma coluna mapeada em found_columns_map
            output_concepts_base = [c for c in standard_concepts_order if c in found_columns_map]

        # Lista final de identificadores (conceitos OU nomes extras) na ordem correta para a saída
        final_output_concepts_or_names = output_concepts_base + extra_col_names

        # Mapeia identificadores para os nomes dos cabeçalhos na planilha Excel
        header_map = { # Nomes "bonitos" para conceitos padrão
            'UNIDADE': 'UNIDADE', 'TIPOLOGIA': 'TIPOLOGIA', 'AREA_CONSTRUIDA': 'ÁREA CONSTRUIDA',
            'QUINTAL': 'QUINTAL', 'GARAGEM': 'GARAGEM', 'VALOR': 'VALOR'
        }
        # Para extras, o header é o próprio nome original; Para padrão, usa o mapa ou o conceito se não mapeado
        output_headers = [header_map.get(c, c) for c in final_output_concepts_or_names]

        print(f"   Colunas Finais de Saída: {output_headers}")
        num_cols = len(output_headers) # Número total de colunas na saída

        # Inicializa a lista de dados e o mapa de linhas para estilos
        final_sheet_data = []
        final_sheet_data.extend([([None] * num_cols)] * 2) # Espaço no topo
        output_title = "TABELA DE PREÇOS"
        final_sheet_data.append([output_title] + [None] * (num_cols - 1))
        final_sheet_data.append([None] * num_cols) # Linha em branco após título
        row_map = {'title': 3, 'etapas': {}} # Mapeia linha Excel (base 1)
        current_excel_row = len(final_sheet_data) + 1 # Próxima linha a ser escrita

        # Loop principal para montar dados por Etapa e Bloco
        for etapa_idx, etapa_nome in enumerate(etapas_ordenadas):
            etapa_header_excel_row = current_excel_row
            row_map['etapas'][etapa_nome] = {'header_row': etapa_header_excel_row, 'blocks': {}}
            final_sheet_data.append([etapa_nome] + [None] * (num_cols - 1)) # Header Etapa
            final_sheet_data.append([None] * num_cols); current_excel_row += 2 # Linha branca

            blocos_desta_etapa = blocos_ordenados_por_etapa.get(etapa_nome, []) # Blocos ordenados desta etapa
            for bloco_idx, bloco_val_orig in enumerate(blocos_desta_etapa):
                bloco_header_excel_row = current_excel_row
                data_header_excel_row = current_excel_row + 2 # Cabeçalho dos dados 2 linhas abaixo
                # Formata nome do bloco para exibição
                block_num = extract_block_number_safe(bloco_val_orig)
                block_display_name = f"BLOCO {block_num:02d}" if block_num is not None else str(bloco_val_orig).upper()

                final_sheet_data.append([block_display_name] + [None] * (num_cols - 1)) # Header Bloco
                final_sheet_data.append([None] * num_cols); # Linha branca
                final_sheet_data.append(output_headers) # Cabeçalhos dos dados

                # Filtra dados do df_intermediate APENAS para este bloco específico
                df_bloco_data = df_intermediate[df_intermediate['BLOCO_ORIGINAL'] == bloco_val_orig]

                formatted_data_rows = []
                # Itera sobre as linhas de dados filtradas para este bloco
                for _, row in df_bloco_data.iterrows():
                    processed_row = [] # Linha de saída para esta linha de entrada
                    # Pega o valor da unidade desta linha para checar se é LOTE
                    unidade_original_desta_linha = str(row.get('UNIDADE', '')) # Pega o valor da coluna 'UNIDADE' (conceito)
                    is_lote_row = 'lote' in unidade_original_desta_linha.lower()

                    # Itera sobre os identificadores (conceitos ou nomes extras) que vão para a saída
                    for concept_or_extra_name in final_output_concepts_or_names:
                        # Pega o valor do df_intermediate usando o identificador correto
                        original_value_str = str(row.get(concept_or_extra_name, ''))
                        processed_val = original_value_str # Valor padrão é o original

                        # --- Lógica de formatação e override condicional ---
                        if concept_or_extra_name == 'TIPOLOGIA' and is_lote_row:
                            processed_val = "LOTEAMENTO" # Override para linhas de lote
                        elif concept_or_extra_name in ['AREA_CONSTRUIDA', 'QUINTAL']:
                            # Formata áreas (mesmo que não vá para a saída lote)
                            numeric_value = parse_flexible_float(original_value_str)
                            processed_val = format_area_m2(numeric_value)
                        elif concept_or_extra_name == 'GARAGEM':
                            # Formata garagem (mesmo que não vá para a saída lote)
                            numeric_value = parse_flexible_float(original_value_str)
                            processed_val = format_garagem_vagas(original_value_str, numeric_value)
                        elif concept_or_extra_name == 'VALOR' or concept_or_extra_name in extra_col_names:
                            # Tenta converter VALOR e todas as COLUNAS EXTRAS para número
                            numeric_value = parse_flexible_float(original_value_str)
                            processed_val = numeric_value # Mantém como número para formatação Excel
                            if numeric_value is None and original_value_str.strip():
                                # Se não converteu mas tinha texto, avisa e deixa em branco
                                print(f"Aviso: Valor/Extra '{original_value_str}' em '{concept_or_extra_name}' não convertido. Será deixado em branco.")
                                processed_val = None

                        processed_row.append(processed_val) # Adiciona valor processado à linha
                    formatted_data_rows.append(processed_row) # Adiciona linha processada à lista

                final_sheet_data.extend(formatted_data_rows) # Adiciona todas as linhas formatadas deste bloco

                # Mapeia as linhas no Excel para permitir aplicação de estilos posterior
                row_map['etapas'][etapa_nome]['blocks'][bloco_val_orig] = {
                    'bloco_header': bloco_header_excel_row,
                    'blank_after_bloco': bloco_header_excel_row + 1,
                    'data_header': data_header_excel_row,
                    'data_start': data_header_excel_row + 1, # Primeira linha de dados 
                    'data_end': data_header_excel_row + len(formatted_data_rows) # Última linha de dados
                }
                current_excel_row = data_header_excel_row + 1 + len(formatted_data_rows) # Atualiza ponteiro da linha

                # Adiciona espaço entre blocos, se não for o último bloco desta etapa
                if bloco_idx < len(blocos_desta_etapa) - 1:
                    final_sheet_data.append([None] * num_cols)
                    current_excel_row += 1

            # Adiciona espaço entre etapas, se não for a última etapa
            if etapa_idx < len(etapas_ordenadas) - 1:
                final_sheet_data.extend([([None] * num_cols)] * 2) # Duas linhas em branco
                current_excel_row += 2

        # 6. Escrever no Excel e Aplicar Estilos Visuais
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Cria DataFrame a partir da lista de listas e escreve no Excel sem header/index
            df_final_sheet = pd.DataFrame(final_sheet_data)
            df_final_sheet.to_excel(writer, sheet_name='Tabela Formatada', index=False, header=False)

            # Pega referências ao workbook e worksheet para aplicar estilos
            workbook = writer.book
            worksheet = writer.sheets['Tabela Formatada']
            print("  Aplicando estilos visuais...")

            # --- Definição de Estilos (cores, fontes, bordas, alinhamentos, formatos) ---
            etapa_header_bg_color = "FFFFFF"; bloco_header_bg_color = "FFFFFF"
            data_header_bg_color = "FFFFFF"; zebra_gray_color = "ffa3a3a3" # Cinza claro para zebra
            etapa_fill = PatternFill(start_color=etapa_header_bg_color, fill_type="solid")
            bloco_fill = PatternFill(start_color=bloco_header_bg_color, fill_type="solid")
            data_header_fill = PatternFill(start_color=data_header_bg_color, fill_type="solid")
            zebra_gray_fill = PatternFill(start_color=zebra_gray_color, fill_type="solid")
            no_fill = PatternFill(fill_type=None) # Para linhas não-zebra
            title_font = Font(name='Calibri', size=11, bold=True, color="000000")
            etapa_font = Font(name='Calibri', size=11, bold=True, color="000000")
            bloco_font = Font(name='Calibri', size=11, bold=True, color="000000")
            data_header_font = Font(name='Calibri', size=11, bold=True, color="000000")
            data_font = Font(name='Calibri', size=11, bold=False, color="000000")
            center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
            thin_border_side = Side(style='thin', color="000000") # Borda fina preta
            medium_border_side = Side(style='medium', color="000000") # Borda média preta
            # Bordas específicas para o cabeçalho de dados (topo médio, resto fino)
            data_header_left_border = Border(top=medium_border_side, bottom=thin_border_side, left=medium_border_side)
            data_header_right_border = Border(top=medium_border_side, bottom=thin_border_side, right=medium_border_side)
            data_header_middle_border = Border(top=medium_border_side, bottom=thin_border_side)
            # Formatos numéricos
            brl_currency_format = 'R$ #,##0.00' # Formato Moeda BRL
            text_format = '@' # Formato Texto

            # --- Função Auxiliar para Estilizar Células Mescladas ---
            def style_merged_range(ws, cell_range_str, border_side, fill=None, font=None, alignment=None):
                """Aplica estilos a um range mesclado (borda externa, fill/font/align na top-left)."""
                min_col, min_row, max_col, max_row = range_boundaries(cell_range_str)
                top_left_cell = ws.cell(row=min_row, column=min_col)
                if fill: top_left_cell.fill = fill
                if font: top_left_cell.font = font
                if alignment: top_left_cell.alignment = alignment
                # Aplica borda no perímetro do range mesclado
                for row_idx in range(min_row, max_row + 1):
                    for col_idx in range(min_col, max_col + 1):
                        cell = ws.cell(row=row_idx, column=col_idx); current_border = cell.border.copy()
                        if row_idx == min_row: current_border.top = border_side
                        if row_idx == max_row: current_border.bottom = border_side
                        if col_idx == min_col: current_border.left = border_side
                        if col_idx == max_col: current_border.right = border_side
                        cell.border = current_border

            # --- Aplicação Principal de Estilos ---
            # Título Principal (Mesclado)
            title_row = row_map['title']
            title_range_str = f"A{title_row}:{get_column_letter(num_cols)}{title_row}"
            worksheet.merge_cells(title_range_str)
            style_merged_range(worksheet, title_range_str, border_side=medium_border_side, font=title_font, alignment=center_align)

            # Identifica dinamicamente quais colunas de saída devem receber formato de moeda
            currency_col_indices_1based = []
            for i, header_name in enumerate(output_headers):
                concept_or_name = final_output_concepts_or_names[i] # Pega o identificador original
                # Formata como moeda se for o conceito 'VALOR' ou se for uma coluna extra
                if concept_or_name == 'VALOR' or concept_or_name in extra_col_names:
                    currency_col_indices_1based.append(i + 1) # Armazena índice base 1
            print(f"   Índices (1-based) para formato Moeda: {currency_col_indices_1based}")

            # Itera sobre Etapas e Blocos no mapa de linhas para aplicar estilos
            for etapa_nome, etapa_info in row_map['etapas'].items():
                # Cabeçalho da Etapa (Mesclado)
                etapa_header_r = etapa_info['header_row']
                etapa_range_str = f"A{etapa_header_r}:{get_column_letter(num_cols)}{etapa_header_r}"
                worksheet.merge_cells(etapa_range_str)
                style_merged_range(worksheet, etapa_range_str, border_side=medium_border_side, fill=etapa_fill, font=etapa_font, alignment=center_align)

                # Itera sobre os blocos desta etapa
                for bloco_val_orig, rows_info in etapa_info['blocks'].items():
                    bloco_header_r = rows_info['bloco_header']
                    data_header_r = rows_info['data_header']
                    data_start_r = rows_info['data_start']
                    data_end_r = rows_info['data_end']

                    # Cabeçalho do Bloco (Mesclado)
                    bloco_range_str = f"A{bloco_header_r}:{get_column_letter(num_cols)}{bloco_header_r}"
                    worksheet.merge_cells(bloco_range_str)
                    style_merged_range(worksheet, bloco_range_str, border_side=medium_border_side, fill=bloco_fill, font=bloco_font, alignment=center_align)

                    # Cabeçalho dos Dados (Não mesclado, estilo por célula)
                    for c_idx_1based in range(1, num_cols + 1):
                        cell = worksheet.cell(row=data_header_r, column=c_idx_1based)
                        cell.fill = data_header_fill; cell.font = data_header_font; cell.alignment = center_align
                        # Aplica bordas específicas para o cabeçalho
                        if c_idx_1based == 1: cell.border = data_header_left_border         # Primeira coluna
                        elif c_idx_1based == num_cols: cell.border = data_header_right_border # Última coluna
                        else: cell.border = data_header_middle_border      # Colunas do meio

                    # Linhas de Dados (Aplica Zebra, Bordas Externas e Formatos)
                    for r in range(data_start_r, data_end_r + 1):
                        relative_row_index = r - data_start_r # Índice relativo dentro do bloco (0, 1, 2...)
                        # Define preenchimento Zebra (cinza claro em linhas ímpares relativas)
                        row_fill = zebra_gray_fill if relative_row_index % 2 == 1 else no_fill
                        # Itera sobre as colunas desta linha
                        for c_idx_1based in range(1, num_cols + 1):
                            cell = worksheet.cell(row=r, column=c_idx_1based)
                            cell.font = data_font; cell.alignment = center_align; cell.fill = row_fill

                            # Aplica Bordas Externas da seção de dados
                            current_border = Border() # Começa sem borda interna
                            is_last_data_row = (r == data_end_r); is_first_col = (c_idx_1based == 1); is_last_col = (c_idx_1based == num_cols)
                            if is_last_data_row: current_border.bottom = medium_border_side # Borda inferior na última linha
                            if is_first_col: current_border.left = medium_border_side       # Borda esquerda na primeira coluna
                            if is_last_col: current_border.right = medium_border_side      # Borda direita na última coluna
                            cell.border = current_border

                            # Aplica formato moeda ou texto
                            if c_idx_1based in currency_col_indices_1based and isinstance(cell.value, (int, float)):
                                # Aplica formato moeda se for número e coluna designada
                                cell.number_format = brl_currency_format
                            elif isinstance(cell.value, str) and cell.value.strip() and cell.value != '--':
                                 # Aplica formato texto se for string não vazia e não placeholder
                                 # Evita formatar números como texto por engano
                                 if parse_flexible_float(cell.value) is None:
                                      cell.number_format = text_format

            # --- Ajuste de Largura das Colunas (Com Default para Extras) ---
            concept_widths = { # Larguras preferenciais para colunas padrão conhecidas
                'UNIDADE': 15, 'TIPOLOGIA': 45, 'ÁREA CONSTRUIDA': 18,
                'QUINTAL': 12, 'GARAGEM': 15, 'VALOR': 20
            }
            # Define larguras para colunas extras comuns (se não definidas, usará default)
            extra_widths = {
                'SINAL 1': 15,
                # Adicione larguras específicas para outras colunas extras aqui pelo nome exato
                # Ex: 'MENSAL ANO 01': 15, 'MENSAL ANO 02': 15, ...
            }
            default_extra_width = 15 # Largura padrão para colunas extras não mapeadas

            print("   Ajustando larguras...")
            for i, header_name in enumerate(output_headers): # Itera sobre os headers REAIS da saída
                col_letter = get_column_letter(i + 1)
                # Tenta pegar largura do mapa padrão, depois do mapa extra, senão usa default
                width = concept_widths.get(header_name, extra_widths.get(header_name, default_extra_width))
                try:
                    worksheet.column_dimensions[col_letter].width = width
                except Exception as e:
                    print(f"Aviso: Falha ao ajustar largura da coluna {col_letter} ('{header_name}'): {e}")

            print("  Estilos visuais finais aplicados.")

        # Retorna o stream de bytes do Excel gerado
        output.seek(0)
        print("(Tabela Preços Formatador - v_Lote_Extras) Processamento concluído.")
        return output

    # --- Blocos de Tratamento de Erro ---
    except ValueError as ve:
        # Erros esperados (ex: coluna não encontrada, arquivo inválido)
        print(f"(Tabela Preços Formatador) ERRO VALIDAÇÃO: {ve}")
        traceback.print_exc() # Mostra detalhes do erro no log
        raise ve # Re-lança para ser tratado pelo Flask (mostrar flash message)
    except Exception as e:
        # Erros inesperados durante o processamento
        print(f"(Tabela Preços Formatador) ERRO INESPERADO: {e}")
        traceback.print_exc()
        # Lança um erro genérico para o Flask
        raise RuntimeError(f"Erro inesperado no formatador de tabela de preços: {e}") from e