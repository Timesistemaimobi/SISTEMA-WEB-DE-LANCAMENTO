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
        df_input = df_input.fillna('') # Garante que não há NaNs literais, substituindo por string vazia
        df_input.columns = df_input.columns.str.strip() # Limpa nomes das colunas

        # Remove linhas completamente vazias que podem ter sido lidas
        df_input.dropna(how='all', inplace=True)
        if df_input.empty:
            raise ValueError("O arquivo parece estar vazio ou não contém dados após a leitura.")

        print(f"  Dimensões do DataFrame lido: {df_input.shape}")

        # 2. Definir Conceitos Padrão e Encontrar Colunas Correspondentes
        col_concepts = {
            'BLOCO': (['bloco', 'blk', 'quadra'], True),
            'UNIDADE': (['apt', 'apto', 'apartamento', 'unidade', 'casa', 'unid', 'ap', 'lote'], True),
            'TIPOLOGIA': (['tipologia', 'tipo', 'descricao', 'descrição'], False),
            'AREA_CONSTRUIDA': (['area construida', 'área construída', 'areaconstruida', 'area util', 'área útil', 'area privativa', 'área privativa', 'área'], True), # Área principal é obrigatória
            'QUINTAL': (['quintal', 'jardim', 'area descoberta', 'área descoberta', 'area externa', 'área externa', 'quintal m2', 'jardim m2'], False),
            'GARAGEM': (['garagem', 'vaga', 'vagas', 'estacionamento'], False),
            'VALOR': (['valor', 'preco', 'preço', 'valor imovel', 'valor do imóvel', 'valor venda', 'valor do imovel (1x)', 'valor do imovel 1x', 'valor a vista', 'valorávista'], False) # Valor passa a ser opcional para flexibilidade
        }
        found_columns_map = {} # Mapeia CONCEITO -> NOME_ORIGINAL_ENCONTRADO
        print("--- Buscando Colunas Padrão ---")
        for concept, (keywords, is_required) in col_concepts.items():
             # *** CORRIGIDO: Passa df_input.columns ***
             found_name = find_column_flexible(df_input.columns, keywords, concept, required=is_required)
             if found_name:
                found_columns_map[concept] = found_name
        print("--- Mapeamento de Colunas Padrão Encontradas ---")
        print(found_columns_map)
        print("-" * 30)

        # --- Identificar Colunas Extras (não mapeadas como padrão) ---
        mapped_original_names = set(found_columns_map.values())
        extra_col_names = [
            col for col in df_input.columns if col not in mapped_original_names and col # Garante que não adiciona colunas com nome vazio
        ]
        if extra_col_names:
            print(f"--- Colunas Extras Identificadas ---")
            print(extra_col_names)
            print("-" * 30)

        # --- Detecção de Lote (Baseado na coluna UNIDADE encontrada) ---
        col_unidade_nome = found_columns_map.get('UNIDADE')
        is_lote_file = False
        if col_unidade_nome and col_unidade_nome in df_input.columns:
            # Verifica se *alguma* célula na coluna UNIDADE contém 'lote', ignorando case e NaN/vazios
            if df_input[col_unidade_nome].astype(str).str.contains('lote', case=False, na=False).any():
                is_lote_file = True
                print(">>> DETECTADO: Arquivo parece ser de LOTEAMENTO (encontrado 'lote' na coluna Unidade). Saída será adaptada.")
        else:
            print("AVISO: Coluna 'UNIDADE' não encontrada ou não mapeada corretamente. Não é possível detectar modo Lote automaticamente.")

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

        # Garante que a coluna de bloco original existe antes de usá-la
        if col_bloco_orig_found not in df_input.columns:
             raise ValueError(f"Erro interno: Coluna de bloco '{col_bloco_orig_found}' mapeada mas não encontrada no DataFrame de entrada.")

        df_intermediate['BLOCO_ORIGINAL'] = df_input[col_bloco_orig_found].astype(str)
        # Propaga valores de bloco para baixo (ffill) para tratar células mescladas ou vazias
        # Antes de ffill, substitui strings vazias por NaN para que ffill funcione corretamente
        df_intermediate['BLOCO_ORIGINAL'] = df_intermediate['BLOCO_ORIGINAL'].replace('', np.nan).ffill()
        # Remove linhas que possam ter ficado sem bloco após o ffill (ex: linhas antes do primeiro bloco válido)
        df_intermediate.dropna(subset=['BLOCO_ORIGINAL'], inplace=True)

        # Garante que a coluna UNIDADE exista no df_intermediate para a próxima etapa
        if 'UNIDADE' not in df_intermediate.columns:
             raise ValueError("Coluna 'UNIDADE' é obrigatória e não foi encontrada ou mapeada.")
        # Remove linhas onde a unidade é vazia, pois são provavelmente inválidas ou separadores
        df_intermediate = df_intermediate[df_intermediate['UNIDADE'].astype(str).str.strip() != '']
        if df_intermediate.empty:
            raise ValueError("Não foram encontrados dados válidos (com Bloco e Unidade preenchidos) no arquivo.")

        # Mapeia a etapa usando o dicionário fornecido
        def map_etapa(bloco_original):
            bloco_str = str(bloco_original).strip() # Limpa espaços antes de buscar
            if not bloco_str or bloco_str.lower() == 'nan': return "ETAPA_NAO_MAPEADA"
            return block_etapa_mapping.get(bloco_str, "ETAPA_NAO_MAPEADA")

        df_intermediate['ETAPA_MAPEADA'] = df_intermediate['BLOCO_ORIGINAL'].apply(map_etapa)

        # Alerta sobre blocos não mapeados
        unmapped_blocks = df_intermediate[df_intermediate['ETAPA_MAPEADA'] == "ETAPA_NAO_MAPEADA"]['BLOCO_ORIGINAL'].unique()
        if len(unmapped_blocks) > 0:
            print(f"AVISO: Os seguintes Blocos/Quadras não foram encontrados no mapeamento de etapas e serão agrupados em 'ETAPA_NAO_MAPEADA': {list(unmapped_blocks)}")

        # 4. Agrupar e Ordenar Blocos por Etapa (para estrutura da planilha)
        etapas_agrupadas = defaultdict(list)
        # Usa drop_duplicates para pegar combinações únicas de Bloco/Etapa válidas
        valid_blocks = df_intermediate[['BLOCO_ORIGINAL', 'ETAPA_MAPEADA']].dropna().drop_duplicates()
        for _, row in valid_blocks.iterrows():
            etapa, bloco = row['ETAPA_MAPEADA'], row['BLOCO_ORIGINAL']
            # Adiciona apenas se o bloco não for vazio ou 'nan' (já filtrado antes, mas reforça)
            if pd.notna(bloco) and str(bloco).strip().lower() != 'nan' and str(bloco).strip() != '':
                 etapas_agrupadas[etapa].append(str(bloco).strip()) # Garante que é string e sem espaços extras
            else:
                 print(f"Aviso: Bloco inválido ('{bloco}') encontrado para etapa '{etapa}', ignorando agrupamento.")

        # Ordena as etapas (numericamente se possível, senão alfabeticamente)
        etapas_ordenadas = sorted(etapas_agrupadas.keys(), key=lambda e: (extract_stage_number(e), e))
        # Ordena os blocos dentro de cada etapa (numericamente se possível)
        blocos_ordenados_por_etapa = {}
        for etapa in etapas_ordenadas:
            blocos_da_etapa = list(set(etapas_agrupadas[etapa])) # Remove duplicatas se houver
            blocos_ordenados_por_etapa[etapa] = sorted(
                blocos_da_etapa,
                key=lambda b: (extract_block_number_safe(b) if extract_block_number_safe(b) is not None else float('inf'), b) # Desempate alfabético
            )

        # 5. Construir Estrutura de Dados para Saída Excel (Dinâmica)
        print(f"--- Montando Saída (Modo Lote: {is_lote_file}, Extras: {bool(extra_col_names)}) ---")
        # Define a lista base de conceitos para a saída
        if is_lote_file:
            # Ordem e colunas para Lotes (sem Quintal/Garagem, mesmo que existam no input)
            output_concepts_base = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA']
            # Adiciona VALOR se foi encontrado
            if 'VALOR' in found_columns_map:
                 output_concepts_base.append('VALOR')
        else:
            # Ordem Padrão (inclui opcionais se foram encontrados no passo 2)
            standard_concepts_order = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
            # Filtra para incluir apenas os conceitos que TEM uma coluna mapeada em found_columns_map
            output_concepts_base = [c for c in standard_concepts_order if c in found_columns_map]

        # Lista final de identificadores (conceitos OU nomes extras) na ordem correta para a saída
        final_output_identifiers = output_concepts_base + extra_col_names

        # Mapeia identificadores para os nomes dos cabeçalhos na planilha Excel
        header_map = { # Nomes "bonitos" para conceitos padrão
            'UNIDADE': 'UNIDADE', 'TIPOLOGIA': 'TIPOLOGIA', 'AREA_CONSTRUIDA': 'ÁREA CONSTRUIDA',
            'QUINTAL': 'QUINTAL', 'GARAGEM': 'GARAGEM', 'VALOR': 'VALOR DO IMÓVEL'
        }
        # Para extras, o header é o próprio nome original; Para padrão, usa o mapa ou o identificador
        output_headers = [header_map.get(identifier, identifier) for identifier in final_output_identifiers]

        print(f"   Colunas Finais de Saída: {output_headers}")
        num_cols = len(output_headers) # Número total de colunas na saída
        if num_cols == 0:
             raise ValueError("Nenhuma coluna foi selecionada para a saída. Verifique o mapeamento.")

        # Inicializa a lista de dados e o mapa de linhas para estilos
        final_sheet_data = []
        final_sheet_data.extend([([None] * num_cols)] * 2) # 2 Linhas em branco no topo
        output_title = "TABELA DE PREÇOS" # Pode ser customizado se necessário
        final_sheet_data.append([output_title] + [None] * (num_cols - 1))
        final_sheet_data.append([None] * num_cols) # Linha em branco após título
        row_map = {'title': 3, 'etapas': {}} # Mapeia linha Excel (base 1)
        current_excel_row = len(final_sheet_data) + 1 # Próxima linha a ser escrita (base 1)

        # Loop principal para montar dados por Etapa e Bloco
        for etapa_idx, etapa_nome in enumerate(etapas_ordenadas):
            etapa_header_excel_row = current_excel_row
            row_map['etapas'][etapa_nome] = {'header_row': etapa_header_excel_row, 'blocks': {}}
            final_sheet_data.append([etapa_nome] + [None] * (num_cols - 1)) # Header Etapa
            final_sheet_data.append([None] * num_cols); current_excel_row += 2 # Linha branca abaixo, atualiza ponteiro

            blocos_desta_etapa = blocos_ordenados_por_etapa.get(etapa_nome, [])
            for bloco_idx, bloco_val_orig in enumerate(blocos_desta_etapa):
                bloco_header_excel_row = current_excel_row
                data_header_excel_row = current_excel_row + 2 # Cabeçalho dos dados 2 linhas abaixo
                # Formata nome do bloco para exibição
                block_num = extract_block_number_safe(bloco_val_orig)
                block_display_name = f"BLOCO {block_num:02d}" if block_num is not None else str(bloco_val_orig).upper()

                final_sheet_data.append([block_display_name] + [None] * (num_cols - 1)) # Header Bloco
                final_sheet_data.append([None] * num_cols); # Linha branca
                final_sheet_data.append(output_headers) # Cabeçalhos dos dados (ex: UNIDADE, TIPOLOGIA...)
                current_excel_row += 3 # Atualiza ponteiro (Header Bloco + Branca + Header Dados)

                # Filtra dados do df_intermediate APENAS para este bloco específico
                # Compara usando o valor original do bloco (string limpa)
                df_bloco_data = df_intermediate[df_intermediate['BLOCO_ORIGINAL'] == bloco_val_orig].copy()
                # Ordena os dados dentro do bloco pela coluna UNIDADE (alfanumericamente)
                # Tenta extrair número da unidade para ordenação numérica primária
                def extract_unit_sort_key(unit_str):
                    unit_str = str(unit_str)
                    numbers = re.findall(r'\d+', unit_str)
                    try:
                        # Retorna o primeiro número encontrado como int, ou float('inf') se nenhum número
                        num_part = int(numbers[0]) if numbers else float('inf')
                    except ValueError:
                        num_part = float('inf') # Caso de número muito grande
                    # Retorna tupla (número, string original) para ordenação estável
                    return (num_part, unit_str)

                if 'UNIDADE' in df_bloco_data.columns:
                    df_bloco_data = df_bloco_data.sort_values(by='UNIDADE', key=lambda col: col.apply(extract_unit_sort_key))


                formatted_data_rows = []
                # Itera sobre as linhas de dados filtradas e ordenadas para este bloco
                for _, row in df_bloco_data.iterrows():
                    processed_row = [] # Linha de saída para esta linha de entrada
                    unidade_original_desta_linha = str(row.get('UNIDADE', ''))
                    # A detecção global is_lote_file é usada aqui, não por linha
                    is_lote_row_specific = 'lote' in unidade_original_desta_linha.lower() # Pode ser útil para lógicas futuras por linha

                    # Itera sobre os identificadores (conceitos ou nomes extras) que vão para a saída
                    for identifier in final_output_identifiers:
                        original_value_str = str(row.get(identifier, '')) # Pega valor do df_intermediate
                        processed_val = original_value_str # Valor padrão é o original

                        # --- Lógica de formatação e override condicional ---
                        if identifier == 'TIPOLOGIA' and is_lote_file: # Usa detecção global
                            processed_val = "LOTEAMENTO" # Override para arquivos de lote
                        elif identifier in ['AREA_CONSTRUIDA', 'QUINTAL']:
                            numeric_value = parse_flexible_float(original_value_str)
                            processed_val = format_area_m2(numeric_value)
                        elif identifier == 'GARAGEM':
                            numeric_value = parse_flexible_float(original_value_str)
                            # Passa o valor original para usar como fallback ou texto
                            processed_val = format_garagem_vagas(original_value_str, numeric_value)
                        elif identifier == 'VALOR' or identifier in extra_col_names:
                            # Tenta converter VALOR e COLUNAS EXTRAS para número
                            numeric_value = parse_flexible_float(original_value_str)
                            if numeric_value is not None:
                                processed_val = numeric_value # Mantém como número para formatação Excel
                            elif original_value_str.strip():
                                # Se não converteu mas tinha texto, mantém o texto original
                                # print(f"Aviso: Valor/Extra '{original_value_str}' em '{identifier}' mantido como texto.") # Debug
                                processed_val = original_value_str.strip() # Mantém como string limpa
                            else:
                                processed_val = None # Deixa em branco (ou None) se era vazio/inválido

                        # Adiciona valor processado à linha de saída
                        processed_row.append(processed_val)

                    formatted_data_rows.append(processed_row) # Adiciona linha processada à lista

                final_sheet_data.extend(formatted_data_rows) # Adiciona todas as linhas formatadas deste bloco

                # Mapeia as linhas no Excel para permitir aplicação de estilos posterior
                data_start_excel_row = data_header_excel_row + 1
                data_end_excel_row = data_start_excel_row + len(formatted_data_rows) -1
                row_map['etapas'][etapa_nome]['blocks'][bloco_val_orig] = {
                    'bloco_header': bloco_header_excel_row,
                    'data_header': data_header_excel_row,
                    'data_start': data_start_excel_row,
                    'data_end': data_end_excel_row
                }
                current_excel_row = data_end_excel_row + 1 # Atualiza ponteiro para a linha após os dados

                # Adiciona espaço entre blocos, se não for o último bloco desta etapa
                if bloco_idx < len(blocos_desta_etapa) - 1:
                    final_sheet_data.append([None] * num_cols)
                    current_excel_row += 1 # Incrementa pelo espaço adicionado

            # Adiciona espaço entre etapas, se não for a última etapa
            if etapa_idx < len(etapas_ordenadas) - 1:
                final_sheet_data.extend([([None] * num_cols)] * 2) # Duas linhas em branco
                current_excel_row += 2 # Incrementa pelos espaços adicionados

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

            # --- Definição de Estilos ---
            # Cores (Exemplo: Azul escuro para Headers, Cinza claro alternado)
            # Cores podem ser ajustadas conforme preferência visual
            header_bg_color = "FFFFFF" # Azul claro suave
            header_font_color = "000000" # Preto
            title_bg_color = "FFFFFF" # Azul mais escuro
            title_font_color = "000000" # Branco

            # Estilos Base
            title_fill = PatternFill(start_color=title_bg_color, fill_type="solid")
            header_fill = PatternFill(start_color=header_bg_color, fill_type="solid")

            title_font = Font(name='Calibri', size=11, bold=True, color=title_font_color)
            etapa_bloco_header_font = Font(name='Calibri', size=11, bold=True, color=header_font_color)
            data_header_font = Font(name='Calibri', size=11, bold=True, color=header_font_color)
            data_font = Font(name='Calibri', size=11, bold=False, color="000000")

            center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
            left_align = Alignment(horizontal='left', vertical='center', wrap_text=True) # Para Unidade/Tipologia?
            right_align = Alignment(horizontal='right', vertical='center', wrap_text=False) # Para Valores

            thin_border_side = Side(style='thin', color="B2B2B2") # Cinza para bordas internas
            medium_border_side = Side(style='medium', color="000000") # Preto para bordas externas

            # Bordas específicas (Exemplo: Contorno médio, internas finas)
            outer_border = Border(left=medium_border_side, right=medium_border_side, top=medium_border_side, bottom=medium_border_side)
            data_header_border = Border(left=thin_border_side, right=thin_border_side, top=medium_border_side, bottom=medium_border_side) # Topo e Fundo Médios
            data_cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side) # Todas finas

            # Formatos numéricos
            brl_currency_format = 'R$ #,##0.00'
            text_format = '@'

            # --- Função Auxiliar para Estilizar Células Mescladas ---
            def style_merged_range(ws, cell_range_str, fill=None, font=None, alignment=None, border=None):
                """Aplica estilos a um range mesclado (borda externa, fill/font/align na top-left)."""
                min_col, min_row, max_col, max_row = range_boundaries(cell_range_str)
                top_left_cell = ws.cell(row=min_row, column=min_col)
                if fill: top_left_cell.fill = fill
                if font: top_left_cell.font = font
                if alignment: top_left_cell.alignment = alignment

                # Aplica borda no perímetro do range mesclado
                if border:
                    for row_idx in range(min_row, max_row + 1):
                        for col_idx in range(min_col, max_col + 1):
                            cell = ws.cell(row=row_idx, column=col_idx)
                            current_border = cell.border.copy() # Preserva bordas existentes de outras células
                            if row_idx == min_row and border.top: current_border.top = border.top
                            if row_idx == max_row and border.bottom: current_border.bottom = border.bottom
                            if col_idx == min_col and border.left: current_border.left = border.left
                            if col_idx == max_col and border.right: current_border.right = border.right
                            cell.border = current_border

            # --- Aplicação Principal de Estilos ---
            # Título Principal (Mesclado)
            title_row = row_map['title']
            title_range_str = f"A{title_row}:{get_column_letter(num_cols)}{title_row}"
            if num_cols > 0: # Só mescla se houver colunas
                worksheet.merge_cells(title_range_str)
                style_merged_range(worksheet, title_range_str, fill=title_fill, font=title_font, alignment=center_align, border=outer_border)

            # Identifica dinamicamente quais colunas de saída devem receber formato de moeda ou texto
            currency_col_indices_1based = []
            text_col_indices_1based = [] # Colunas que devem ser explicitamente texto
            numeric_col_indices_1based = [] # Colunas numéricas (não moeda) como área
            alignment_map = {} # Mapeia índice (1-based) para alinhamento

            for i, header_name in enumerate(output_headers):
                identifier = final_output_identifiers[i]
                col_idx_1based = i + 1

                # Define formato
                if identifier == 'VALOR' or identifier in extra_col_names:
                    # Tenta tratar Valor e Extras como moeda por padrão se forem numéricos
                    currency_col_indices_1based.append(col_idx_1based)
                    alignment_map[col_idx_1based] = right_align # Alinha moeda à direita
                elif identifier in ['AREA_CONSTRUIDA', 'QUINTAL']:
                     # Áreas podem ser tratadas como texto ('-- m²') ou número se precisasse de cálculo
                     # Como formatamos como string com 'm²', trataremos como texto para alinhamento
                     text_col_indices_1based.append(col_idx_1based)
                     alignment_map[col_idx_1based] = center_align # Centraliza áreas
                elif identifier in ['UNIDADE', 'TIPOLOGIA', 'GARAGEM']:
                     text_col_indices_1based.append(col_idx_1based)
                     alignment_map[col_idx_1based] = left_align if identifier in ['TIPOLOGIA'] else center_align # Alinha Tipologia à esquerda

                # Define alinhamento padrão (se não definido acima)
                if col_idx_1based not in alignment_map:
                    alignment_map[col_idx_1based] = center_align


            print(f"   Índices (1-based) Formato Moeda: {currency_col_indices_1based}")
            print(f"   Índices (1-based) Formato Texto: {text_col_indices_1based}")

            # Itera sobre Etapas e Blocos no mapa de linhas para aplicar estilos
            table_counter = 1 # Contador para nomes de tabela únicos
            for etapa_nome, etapa_info in row_map['etapas'].items():
                # Cabeçalho da Etapa (Mesclado)
                etapa_header_r = etapa_info['header_row']
                etapa_range_str = f"A{etapa_header_r}:{get_column_letter(num_cols)}{etapa_header_r}"
                if num_cols > 0:
                    worksheet.merge_cells(etapa_range_str)
                    style_merged_range(worksheet, etapa_range_str, fill=header_fill, font=etapa_bloco_header_font, alignment=center_align, border=outer_border)

                # Itera sobre os blocos desta etapa
                for bloco_val_orig, rows_info in etapa_info['blocks'].items():
                    bloco_header_r = rows_info['bloco_header']
                    data_header_r = rows_info['data_header']
                    data_start_r = rows_info['data_start']
                    data_end_r = rows_info['data_end']

                    # Cabeçalho do Bloco (Mesclado)
                    bloco_range_str = f"A{bloco_header_r}:{get_column_letter(num_cols)}{bloco_header_r}"
                    if num_cols > 0:
                        worksheet.merge_cells(bloco_range_str)
                        style_merged_range(worksheet, bloco_range_str, fill=header_fill, font=etapa_bloco_header_font, alignment=center_align, border=outer_border)

                    # --- Aplica Estilo de Tabela (para zebra e filtros) ---
                    if data_start_r <= data_end_r: # Só cria tabela se houver dados
                        start_col_letter = get_column_letter(1)
                        end_col_letter = get_column_letter(num_cols)
                        table_range = f"{start_col_letter}{data_header_r}:{end_col_letter}{data_end_r}"
                        # Nome da tabela mais simples e único
                        table_name = f"Tabela_{table_counter}"
                        table_counter += 1

                        tab = Table(displayName=table_name, ref=table_range)
                        # Estilo de tabela: 'TableStyleMedium9' é um exemplo com azul e linhas alternadas
                        # Consulte a documentação do Openpyxl ou teste estilos no Excel para ver opções
                        style = TableStyleInfo(name="TableStyleLight1", # Exemplo: Azul Médio
                                            showFirstColumn=False,
                                            showLastColumn=False,
                                            showRowStripes=True, # Habilita linhas zebradas
                                            showColumnStripes=False)
                        tab.tableStyleInfo = style
                        worksheet.add_table(tab)
                        print(f"   Aplicado Estilo Tabela '{style.name}' range {table_range} (Nome: {table_name})")

                    # --- Formatação Manual Adicional (Cabeçalho Dados e Células Dados) ---
                    # (Necessário para fontes, alinhamentos, formatos específicos que o TableStyle não cobre totalmente)

                    # Cabeçalho dos Dados (Estilo célula a célula sobrepõe parcialmente o TableStyle se necessário)
                    for c_idx_1based in range(1, num_cols + 1):
                        cell = worksheet.cell(row=data_header_r, column=c_idx_1based)
                        cell.font = data_header_font
                        cell.alignment = alignment_map.get(c_idx_1based, center_align) # Usa mapa de alinhamento
                        # A cor de fundo e bordas do cabeçalho são geralmente definidas pelo TableStyle,
                        # mas podemos forçar se necessário:
                        # cell.fill = data_header_fill
                        # cell.border = data_header_border

                    # Linhas de Dados (Formatação célula a célula)
                    for r in range(data_start_r, data_end_r + 1):
                        for c_idx_1based in range(1, num_cols + 1):
                            cell = worksheet.cell(row=r, column=c_idx_1based)
                            cell.font = data_font
                            cell.alignment = alignment_map.get(c_idx_1based, center_align)
                            # Aplica formato moeda ou texto
                            if c_idx_1based in currency_col_indices_1based and isinstance(cell.value, (int, float, np.number)):
                                cell.number_format = brl_currency_format
                            elif c_idx_1based in text_col_indices_1based:
                                 cell.number_format = text_format

                    if data_start_r <= data_end_r and num_cols > 0:
                        outer_border_start_row = data_header_r # Começa no cabeçalho da tabela
                        outer_border_end_row = data_end_r       # Termina na última linha de dados

                        for row_idx in range(outer_border_start_row, outer_border_end_row + 1):
                            for col_idx_1based in range(1, num_cols + 1):
                                cell = worksheet.cell(row=row_idx, column=col_idx_1based)
                                # Copia a borda existente para preservar linhas internas do TableStyle
                                current_border = cell.border.copy()

                                # Aplica LADO MÉDIO SOMENTE NA PERIMETRIA DA ÁREA DE DADOS
                                is_top_data_row = (row_idx == outer_border_start_row)
                                is_bottom_data_row = (row_idx == outer_border_end_row)
                                is_left_col = (col_idx_1based == 1)
                                is_right_col = (col_idx_1based == num_cols)

                                if is_top_data_row:
                                    current_border.top = medium_border_side
                                if is_bottom_data_row:
                                    current_border.bottom = medium_border_side
                                if is_left_col:
                                    current_border.left = medium_border_side
                                if is_right_col:
                                    current_border.right = medium_border_side

                                cell.border = current_border

                                # Bordas podem ser controladas pelo Table Style, mas podemos adicionar aqui se necessário
                                # Ex: cell.border = data_cell_border

            # --- Ajuste de Largura das Colunas ---
            concept_widths = { # Larguras preferenciais (ajuste conforme necessário)
                'UNIDADE': 12, 'TIPOLOGIA': 40, 'ÁREA CONSTRUIDA': 15,
                'QUINTAL': 12, 'GARAGEM': 15, 'VALOR': 18
            }
            extra_widths = { # Larguras específicas para colunas extras conhecidas
                # Adicione aqui pelo NOME ORIGINAL da coluna extra
                # Ex: 'NOME_COLUNA_EXTRA_1': 15,
            }
            default_extra_width = 15 # Largura padrão para extras não mapeadas

            print("   Ajustando larguras das colunas...")
            for i, header_name in enumerate(output_headers): # Itera sobre os headers REAIS da saída
                col_letter = get_column_letter(i + 1)
                identifier = final_output_identifiers[i] # Pega o identificador original (conceito ou nome extra)

                # Lógica para determinar a largura:
                width = None
                # 1. Tenta largura específica para o CONCEITO padrão
                if identifier in concept_widths:
                    width = concept_widths[identifier]
                # 2. Se não, tenta largura específica para o NOME EXTRA original
                elif identifier in extra_widths:
                     width = extra_widths[identifier]
                # 3. Se não, usa largura padrão para CONCEITO padrão (se aplicável)
                elif identifier in header_map and header_map[identifier] in concept_widths:
                     width = concept_widths[header_map[identifier]] # Usa o nome bonito mapeado
                # 4. Se for coluna extra não mapeada, usa default
                elif identifier in extra_col_names:
                    width = default_extra_width
                # 5. Fallback final (caso algum conceito padrão não esteja em concept_widths)
                else:
                    width = default_extra_width

                if width:
                    try:
                        worksheet.column_dimensions[col_letter].width = width
                    except Exception as e:
                        print(f"Aviso: Falha ao ajustar largura da coluna {col_letter} ('{header_name}'): {e}")

            print("  Estilos visuais finais aplicados.")

        # Retorna o stream de bytes do Excel gerado
        output.seek(0)
        print(f"(Tabela Preços Formatador - v_Lote_Extras_Refined) Processamento concluído.")
        return output

    # --- Blocos de Tratamento de Erro ---
    except ValueError as ve:
        # Erros esperados (ex: coluna não encontrada, arquivo inválido, sem dados)
        print(f"(Tabela Preços Formatador) ERRO VALIDAÇÃO: {ve}")
        traceback.print_exc() # Mostra detalhes do erro no log
        raise ve # Re-lança para ser tratado pela aplicação (mostrar flash message)
    except Exception as e:
        # Erros inesperados durante o processamento
        print(f"(Tabela Preços Formatador) ERRO INESPERADO: {e}")
        traceback.print_exc()
        # Lança um erro genérico
        raise RuntimeError(f"Erro inesperado no formatador de tabela de preços: {e}") from e
