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

# --- Funções Auxiliares (parse_flexible_float, etc. - Mantidas da v11) ---
def normalize_text_for_match(text):
    if not isinstance(text, str): text = str(text)
    try:
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        text = text.lower()
        text = re.sub(r'[^a-z0-9]', '', text) # Remove não alfanuméricos
        return text.strip()
    except Exception:
        return str(text).lower().strip() # Fallback

def find_column_flexible(df_columns, concept_keywords, concept_name, required=True):
    normalized_input_cols = {normalize_text_for_match(col): col for col in df_columns}
    print(f"  Buscando '{concept_name}': Keywords={concept_keywords}. Colunas Norm.: {list(normalized_input_cols.keys())}") # Debug
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
            # Verifica se a keyword normalizada está contida na coluna normalizada
            if norm_keyword in norm_col:
                 priority = 0 if norm_col.startswith(norm_keyword) else 1
                 potential_matches.append((priority, orig_col))
                 print(f"    -> Match parcial candidato: '{keyword}' em '{orig_col}' (Norm: '{norm_keyword}' em '{norm_col}') Prio:{priority}") # Debug

    if potential_matches:
        potential_matches.sort() # Ordena por prioridade
        found_col_name = potential_matches[0][1] # Pega a melhor correspondência
        print(f"    -> Melhor match parcial para '{concept_name}'. Col original: '{found_col_name}'")
        return found_col_name
    # 3. Erro se obrigatório e não encontrado
    if required:
        raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada. Keywords usadas: {concept_keywords}. Colunas originais: {df_columns.tolist()}")
    else:
        print(f"    -> Coluna opcional '{concept_name}' não encontrada.")
        return None


def extract_block_number_safe(block_value_str):
    if not isinstance(block_value_str, str): block_value_str = str(block_value_str)
    match = re.search(r'\d+', block_value_str)
    if match:
        try: return int(match.group(0))
        except ValueError: return None
    return None

def parse_flexible_float(value_str):
    """
    Tenta converter uma string para float de forma mais robusta.
    Retorna float se a string representa APENAS um número (com ou sem
    separadores/símbolos comuns), caso contrário retorna None.
    """
    if value_str is None: return None
    text = str(value_str).strip()
    if not text: return None

    # 1. Limpeza inicial de símbolos comuns e espaços
    cleaned_text = text.upper().replace('R$', '').replace('M²', '').replace('M2','').strip()

    # 2. Verifica se, APÓS a limpeza inicial, a string se parece com um número
    #    (dígitos, talvez UM ponto OU UMA vírgula, talvez UM sinal no início)
    #    Regex: Opcional '-', um ou mais dígitos, opcional (UM ponto OU UMA vírgula seguido de mais dígitos)
    #    Esta regex é SIMPLIFICADA e pode não pegar todos os formatos de milhar,
    #    mas deve evitar converter "02 VAGAS".
    #    Regex mais robusta pode ser necessária para formatos complexos.
    match_simple_num = re.fullmatch(r"^-?(\d+([.,]\d+)?|\d*([.,]\d+))$", cleaned_text.replace('.', '').replace(',', '.')) # Tenta sem separadores de milhar
    match_maybe_num = re.fullmatch(r"^-?[\d.,]+$", cleaned_text) # Verifica se SÓ tem dígitos, ponto, vírgula ou '-'

    if not match_maybe_num:
        # print(f"DEBUG parse: '{cleaned_text}' contém caracteres não numéricos (exceto . , -). Retornando None.")
        return None # Contém letras ou outros símbolos não esperados

    # Se passou na verificação inicial, tenta a conversão mais cuidadosa
    # Removendo apenas caracteres NÃO numéricos, exceto ponto, vírgula e sinal
    parse_ready_text = re.sub(r'[^\d,.-]', '', cleaned_text)

    last_dot = parse_ready_text.rfind('.')
    last_comma = parse_ready_text.rfind(',')

    try:
        if last_comma > last_dot: # Provável decimal BR (,)
            num_str = parse_ready_text.replace('.', '').replace(',', '.')
        elif last_dot > last_comma: # Provável decimal US (.)
            num_str = parse_ready_text.replace(',', '')
        elif last_comma != -1 and last_dot == -1: # Só vírgula
             # Cuidado: "1,234" (milhar) vs "1,2" (decimal)
             # Se houver mais de uma vírgula, provavelmente é milhar
             if parse_ready_text.count(',') > 1:
                 num_str = parse_ready_text.replace(',', '') # Assume milhar US
             else:
                 num_str = parse_ready_text.replace(',', '.') # Assume decimal BR
        elif last_dot != -1 and last_comma == -1: # Só ponto
             # Se houver mais de um ponto, provavelmente é milhar
              if parse_ready_text.count('.') > 1:
                  num_str = parse_ready_text.replace('.', '') # Assume milhar BR
              else:
                  num_str = parse_ready_text # Assume decimal US
        else: # Nenhum separador
            num_str = parse_ready_text

        # Tentativa final de conversão
        result = float(num_str)
        # print(f"DEBUG parse: '{value_str}' -> '{cleaned_text}' -> '{num_str}' -> {result}")
        return result
    except (ValueError, TypeError):
        # print(f"DEBUG parse FALHA FINAL: '{value_str}' -> '{cleaned_text}' -> '{num_str}'")
        # Se todas as tentativas falharam, retorna None
        return None

def format_garagem_vagas(original_value_str, numeric_value):
    """
    Formata a informação de garagem:
    - Se o valor original for vazio/None/string "None", retorna "01 VAGA".
    - Se o valor original PUDER ser convertido para número, aplica a lógica de faixas.
    - Se o valor original NÃO PUDER ser convertido, retorna a string original.
    """
    original_clean_str = str(original_value_str).strip()

    # Trata casos vazios ou explicitamente "None"
    if not original_clean_str or original_clean_str.lower() == 'none':
        return "01 VAGA"

    # Verifica se a tentativa de conversão numérica (numeric_value) foi bem-sucedida
    if numeric_value is not None:
        # Sim, é um número (provavelmente metragem). Aplica a lógica de faixas.
        try:
            gn = numeric_value # Já é float
            if gn > 35: return "04 VAGAS"
            elif gn > 25: return "03 VAGAS"
            elif gn > 15: return "02 VAGAS"
            elif gn >= 0: return "01 VAGA"
            else: return "01 VAGA" # Fallback para negativos
        except Exception as e:
            # Pouco provável, mas se der erro na comparação, retorna o original
            print(f"AVISO: Erro inesperado ao comparar valor numérico da garagem {numeric_value}: {e}")
            return original_clean_str
    else:
        # Não, não foi possível converter para número. Assume que a string original é a descrição.
        # Ex: "02 VAGAS", "1 VAGA COBERTA", etc.
        return original_clean_str

def extract_stage_number(stage_name_str):
    match = re.search(r'\d+', stage_name_str)
    if match:
        try: return int(match.group(0))
        except ValueError: return float('inf')
    return float('inf')

# --- Função Principal de Processamento (v12 - Keywords CSV adicionadas) ---

def processar_tabela_precos_web(input_filepath, block_etapa_mapping):
    print(f"(Tabela Preços Formatador - v12 Keywords CSV) Iniciando: {input_filepath}")
    # A função não precisa mais saber se veio de CSV ou Excel aqui.
    # Ela recebe um DataFrame lido pelo app.py

    try:
        # 1. Ler o DataFrame (JÁ LIDO PELO app.py)
        # Simulamos a leitura aqui apenas para ter o df_input no escopo,
        # mas na prática o app.py já teria feito isso.
        # A linha abaixo deve ser REMOVIDA se você chamar esta função do app.py
        # passando o DataFrame lido. Por enquanto, deixamos para teste isolado.
        # df_input = pd.read_excel(input_filepath, ...) # REMOVER ESTA LINHA NO USO REAL
        # Na prática, o df_input seria o DataFrame lido no app.py
        # Para esta função funcionar como está no exemplo, precisamos da leitura:
        # (Mantendo a lógica de leitura aqui apenas para que a função seja 'completa' no exemplo)
        # (NO SEU app.py, VOCÊ JÁ LÊ O ARQUIVO ANTES DE CHAMAR ESTA FUNÇÃO)
        # >>> INICIO Bloco de Leitura (COMENTAR/REMOVER no app.py) <<<
        NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL = 1 # Assume CSV tem header na linha 1
        linhas_para_pular = NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL - 1
        try:
            # Tenta ler como CSV primeiro (exemplo)
            df_input = pd.read_csv(input_filepath, sep=';', decimal=',', encoding='utf-8', header=0, dtype=str, skipinitialspace=True).fillna('')
        except: # Se falhar CSV, tenta Excel (exemplo)
             try:
                  df_input = pd.read_excel(input_filepath, engine='openpyxl', skiprows=2, header=0, dtype=str).fillna('') # Assume Excel header linha 3
             except Exception as read_err:
                  raise ValueError(f"Falha ao ler arquivo como CSV ou Excel: {read_err}")
        # >>> FIM Bloco de Leitura (COMENTAR/REMOVER no app.py) <<<


        # 2. Definir Conceitos e Encontrar Colunas (KEYWORDS ATUALIZADAS)
        col_concepts = {
            'BLOCO': (['bloco', 'blk', 'quadra'], True),
            'UNIDADE': (['apt', 'apto', 'apartamento', 'unidade', 'casa', 'unid', 'ap'], True),
            'TIPOLOGIA': (['tipologia', 'tipo', 'descricao', 'descrição'], True),
            # Adiciona 'area privativa'
            'AREA_CONSTRUIDA': (['area construida', 'área construída', 'areaconstruida', 'area util', 'área útil', 'area privativa', 'área privativa'], True),
            # Adiciona 'jardim'
            'QUINTAL': (['quintal', 'jardim', 'area descoberta', 'área descoberta', 'area externa', 'área externa', 'quintal m2', 'jardim m2'], False),
            'GARAGEM': (['garagem', 'vaga', 'vagas', 'estacionamento'], False),
             # Adiciona 'valor do imovel 1x' e 'valor do imovel'
            'VALOR': (['valor', 'preco', 'preço', 'valor imovel', 'valor do imóvel', 'valor venda', 'valor do imovel (1x)', 'valor do imovel 1x'], True)
        }
        found_columns = {}
        print("--- Buscando Colunas ---")
        df_input.columns = df_input.columns.str.strip() # Garante limpeza
        for concept, (keywords, is_required) in col_concepts.items():
            found_columns[concept] = find_column_flexible(df_input.columns, keywords, concept, required=is_required)
        print("--- Mapeamento de Colunas Encontradas ---")
        print(found_columns)
        print("-" * 30)


        # 3. Preparar DataFrame Intermediário (igual v11)
        df_intermediate = pd.DataFrame()
        output_concept_order = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
        col_bloco_orig = found_columns.get('BLOCO')
        if not col_bloco_orig: raise ValueError("Coluna Bloco/Quadra obrigatória não encontrada usando as keywords.")
        df_input[col_bloco_orig] = df_input[col_bloco_orig].replace('', np.nan).ffill()
        df_intermediate['BLOCO_ORIGINAL'] = df_input[col_bloco_orig].astype(str)

        def map_etapa(bloco_original):
            if pd.isna(bloco_original) or str(bloco_original).lower() == 'nan': return "ETAPA_NAO_MAPEADA"
            return block_etapa_mapping.get(str(bloco_original).strip(), "ETAPA_NAO_MAPEADA")
        df_intermediate['ETAPA_MAPEADA'] = df_intermediate['BLOCO_ORIGINAL'].apply(map_etapa)

        if "ETAPA_NAO_MAPEADA" in df_intermediate['ETAPA_MAPEADA'].unique():
            blocos_nao_mapeados = df_intermediate[df_intermediate['ETAPA_MAPEADA'] == "ETAPA_NAO_MAPEADA"]['BLOCO_ORIGINAL'].unique()
            print(f"Aviso: Blocos não mapeados encontrados: {blocos_nao_mapeados}.")

        for concept in output_concept_order:
            original_col_name = found_columns.get(concept)
            df_intermediate[concept] = df_input[original_col_name].astype(str).copy() if original_col_name else ''


        # 4. Agrupar e Ordenar por Etapa e Bloco (igual v11)
        etapas_agrupadas = defaultdict(list)
        for _, row in df_intermediate[['BLOCO_ORIGINAL', 'ETAPA_MAPEADA']].drop_duplicates().iterrows():
            etapa, bloco = row['ETAPA_MAPEADA'], row['BLOCO_ORIGINAL']
            if pd.notna(bloco) and str(bloco).lower() != 'nan': etapas_agrupadas[etapa].append(bloco)
        etapas_ordenadas = sorted(etapas_agrupadas.keys(), key=lambda e: (extract_stage_number(e), e))
        blocos_ordenados_por_etapa = {}
        for etapa in etapas_ordenadas:
            blocos_da_etapa = etapas_agrupadas[etapa]
            blocos_ordenados_por_etapa[etapa] = sorted(blocos_da_etapa, key=lambda b: extract_block_number_safe(b) if extract_block_number_safe(b) is not None else float('inf'))

        # 5. Construir a Estrutura da Planilha de Saída (igual v11)
        output_headers = ['UNIDADE', 'TIPOLOGIA', 'ÁREA CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
        num_cols = len(output_headers)
        final_sheet_data = []
        # ... (cabeçalhos, estrutura de loop por etapa/bloco - igual v11) ...
        final_sheet_data.extend([([None] * num_cols)] * 2)
        output_title = "TABELA DE PREÇOS"; final_sheet_data.append([output_title] + [None] * (num_cols - 1)); final_sheet_data.append([None] * num_cols)
        row_map = {'title': 3, 'etapas': {}}; current_excel_row = len(final_sheet_data) + 1
        for etapa_idx, etapa_nome in enumerate(etapas_ordenadas):
            etapa_header_excel_row = current_excel_row; row_map['etapas'][etapa_nome] = {'header_row': etapa_header_excel_row, 'blocks': {}}
            final_sheet_data.append([etapa_nome] + [None] * (num_cols - 1)); final_sheet_data.append([None] * num_cols); current_excel_row += 2
            blocos_desta_etapa = blocos_ordenados_por_etapa[etapa_nome]
            for bloco_idx, bloco_val_orig in enumerate(blocos_desta_etapa):
                bloco_header_excel_row = current_excel_row; data_header_excel_row = current_excel_row + 2
                block_num = extract_block_number_safe(bloco_val_orig)
                block_display_name = f"BLOCO {block_num:02d}" if block_num is not None else str(bloco_val_orig).upper()
                final_sheet_data.append([block_display_name] + [None] * (num_cols - 1)); final_sheet_data.append([None] * num_cols); final_sheet_data.append(output_headers)
                df_bloco_data = df_intermediate[df_intermediate['BLOCO_ORIGINAL'] == bloco_val_orig][output_concept_order]
                formatted_data_rows = []
                for _, row in df_bloco_data.iterrows():
                    processed_row = []
                    for concept in output_concept_order:
                        original_value_str = str(row.get(concept, ''))
                        processed_val = original_value_str # Default
                        if concept in ['AREA_CONSTRUIDA', 'QUINTAL']:
                            numeric_value = parse_flexible_float(original_value_str)
                            placeholder = "--"
                            if numeric_value is not None:
                                if np.isclose(numeric_value, 0): processed_val = placeholder
                                else: processed_val = f"{numeric_value:.2f}".replace('.', ',') + " m²"
                            else:
                                if not original_value_str.strip(): processed_val = placeholder
                        elif concept == 'GARAGEM':
                            # 1. Tenta converter o valor original para número
                            numeric_value = parse_flexible_float(original_value_str)
                            # 2. Chama a função passando a string ORIGINAL e o resultado da conversão
                            processed_val = format_garagem_vagas(original_value_str, numeric_value)

                        elif concept == 'VALOR':
                            numeric_value = parse_flexible_float(original_value_str)
                            processed_val = numeric_value if numeric_value is not None else None
                            if numeric_value is None and original_value_str.strip():
                                print(f"Aviso: Valor '{original_value_str}' não convertido para numérico. Será deixado em branco.")
                                processed_val = None
                        processed_row.append(processed_val)
                    formatted_data_rows.append(processed_row)
                final_sheet_data.extend(formatted_data_rows)
                row_map['etapas'][etapa_nome]['blocks'][bloco_val_orig] = {'bloco_header': bloco_header_excel_row,'blank_after_bloco': bloco_header_excel_row + 1,'data_header': data_header_excel_row,'data_start': data_header_excel_row + 1,'data_end': data_header_excel_row + len(formatted_data_rows)}
                current_excel_row = data_header_excel_row + 1 + len(formatted_data_rows)
                if bloco_idx < len(blocos_desta_etapa) - 1: final_sheet_data.append([None] * num_cols); current_excel_row += 1
            if etapa_idx < len(etapas_ordenadas) - 1: final_sheet_data.extend([([None] * num_cols)] * 2); current_excel_row += 2


        # 6. Escrever no Excel e Aplicar Estilos Visuais (igual v11)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_final_sheet = pd.DataFrame(final_sheet_data)
            # Não mescla aqui, o DataFrame é só para dados. A mesclagem é feita depois.
            df_final_sheet.to_excel(writer, sheet_name='Tabela Formatada', index=False, header=False)

            workbook = writer.book
            worksheet = writer.sheets['Tabela Formatada']
            print("  Aplicando estilos visuais (Zebra, Borda Externa, Bordas Cabeçalho CORRIGIDO v2)...")

            # --- Definição de Estilos e Formatos (iguais v15) ---
            etapa_header_bg_color = "FFFFFF"; bloco_header_bg_color = "FFFFFF"
            data_header_bg_color = "FFFFFF"; zebra_gray_color = "ffa3a3a3"
            etapa_fill = PatternFill(start_color=etapa_header_bg_color, fill_type="solid")
            bloco_fill = PatternFill(start_color=bloco_header_bg_color, fill_type="solid")
            data_header_fill = PatternFill(start_color=data_header_bg_color, fill_type="solid")
            zebra_gray_fill = PatternFill(start_color=zebra_gray_color, fill_type="solid")
            no_fill = PatternFill(fill_type=None)
            title_font = Font(name='Calibri', size=11, bold=True, color="000000")
            etapa_font = Font(name='Calibri', size=11, bold=True, color="000000")
            bloco_font = Font(name='Calibri', size=11, bold=True, color="000000")
            data_header_font = Font(name='Calibri', size=11, bold=True, color="000000")
            data_font = Font(name='Calibri', size=11, bold=False, color="000000")
            center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
            thin_border_side = Side(style='thin', color="000000")
            medium_border_side = Side(style='medium', color="000000")
            # NÃO precisamos mais do medium_external_border completo
            data_header_left_border = Border(top=medium_border_side, bottom=thin_border_side, left=medium_border_side)
            data_header_right_border = Border(top=medium_border_side, bottom=thin_border_side, right=medium_border_side)
            data_header_middle_border = Border(top=medium_border_side, bottom=thin_border_side)
            brl_currency_format = 'R$ #,##0.00'; text_format = '@'

            # --- Aplicação de Estilos ---

            # Função auxiliar REFINADA para aplicar bordas a um range MESCLADO
            def style_merged_range(ws, cell_range_str, border_side, fill=None, font=None, alignment=None):
                """
                Aplica estilos a um range que SERÁ ou FOI mesclado.
                Aplica fill/font/alignment à célula top-left.
                Aplica a borda externa especificada ao redor do range.
                """
                # Aplica estilos não-borda à célula top-left (funciona para mescladas)
                min_col, min_row, max_col, max_row = range_boundaries(cell_range_str)
                top_left_cell = ws.cell(row=min_row, column=min_col)
                if fill: top_left_cell.fill = fill
                if font: top_left_cell.font = font
                if alignment: top_left_cell.alignment = alignment

                # Aplica bordas apenas no perímetro do range
                for row_idx in range(min_row, max_row + 1):
                    for col_idx in range(min_col, max_col + 1):
                        cell = ws.cell(row=row_idx, column=col_idx)
                        current_border = cell.border.copy() # Pega borda existente ou cria nova

                        # Aplica bordas externas
                        if row_idx == min_row: current_border.top = border_side
                        if row_idx == max_row: current_border.bottom = border_side
                        if col_idx == min_col: current_border.left = border_side
                        if col_idx == max_col: current_border.right = border_side

                        cell.border = current_border


            # --- Aplica Mesclagem e Estilos ---
            # Título Principal
            title_row = row_map['title']
            title_range_str = f"A{title_row}:{get_column_letter(num_cols)}{title_row}"
            worksheet.merge_cells(title_range_str) # <<< Mescla PRIMEIRO
            style_merged_range(worksheet, title_range_str, border_side=medium_border_side, font=title_font, alignment=center_align)

            # Encontrar índice da coluna VALOR
            try: valor_col_index = output_headers.index('VALOR') + 1
            except ValueError: valor_col_index = -1

            # Itera sobre Etapas e Blocos para aplicar estilos
            for etapa_nome, etapa_info in row_map['etapas'].items():
                etapa_header_r = etapa_info['header_row']
                # Cabeçalho Etapa
                etapa_range_str = f"A{etapa_header_r}:{get_column_letter(num_cols)}{etapa_header_r}"
                worksheet.merge_cells(etapa_range_str) # <<< Mescla PRIMEIRO
                style_merged_range(worksheet, etapa_range_str, border_side=medium_border_side, fill=etapa_fill, font=etapa_font, alignment=center_align)

                for bloco_val_orig, rows_info in etapa_info['blocks'].items():
                    bloco_header_r = rows_info['bloco_header']
                    data_header_r = rows_info['data_header']
                    data_start_r = rows_info['data_start']
                    data_end_r = rows_info['data_end']

                    # Cabeçalho Bloco
                    bloco_range_str = f"A{bloco_header_r}:{get_column_letter(num_cols)}{bloco_header_r}"
                    worksheet.merge_cells(bloco_range_str) # <<< Mescla PRIMEIRO
                    style_merged_range(worksheet, bloco_range_str, border_side=medium_border_side, fill=bloco_fill, font=bloco_font, alignment=center_align)

                    # Cabeçalho Dados (Data Header) - Sem mesclagem, lógica anterior está OK
                    for c_idx in range(1, num_cols + 1):
                        cell = worksheet.cell(row=data_header_r, column=c_idx)
                        cell.fill = data_header_fill; cell.font = data_header_font; cell.alignment = center_align
                        if c_idx == 1: cell.border = data_header_left_border
                        elif c_idx == num_cols: cell.border = data_header_right_border
                        else: cell.border = data_header_middle_border

                    # Linhas Dados - Zebra e Borda Externa (igual v14)
                    for r in range(data_start_r, data_end_r + 1):
                        relative_row_index = r - data_start_r
                        row_fill = zebra_gray_fill if relative_row_index % 2 == 1 else no_fill
                        for c_idx in range(1, num_cols + 1):
                            cell = worksheet.cell(row=r, column=c_idx); cell.font = data_font; cell.alignment = center_align; cell.fill = row_fill
                            current_border = Border()
                            is_last_data_row = (r == data_end_r); is_first_col = (c_idx == 1); is_last_col = (c_idx == num_cols)
                            if is_last_data_row: current_border.bottom = medium_border_side
                            if is_first_col: current_border.left = medium_border_side
                            if is_last_col: current_border.right = medium_border_side
                            cell.border = current_border
                            if c_idx == valor_col_index and isinstance(cell.value, (int, float)): cell.number_format = brl_currency_format
                            elif isinstance(cell.value, str) and cell.value.strip() and cell.value != '--': cell.number_format = text_format

            # Ajuste de Largura (igual v14)
            col_widths = {'A': 10, 'B': 45, 'C': 18, 'D': 12, 'E': 15, 'F': 20}
            for i, col_letter in enumerate([get_column_letter(j+1) for j in range(num_cols)]):
                 width = col_widths.get(col_letter);
                 if width:
                     try: worksheet.column_dimensions[col_letter].width = width
                     except Exception as e: print(f"Aviso: Largura {col_letter}: {e}")

            print("  Estilos visuais finais aplicados (borda mesclada v2 corrigida).")

        output.seek(0)
        print("(Tabela Preços Formatador - v16 Borda Mesclada Ok) Processamento concluído.")
        return output

    # --- Blocos except (iguais v14) ---
    except ValueError as ve: print(f"(Tabela Preços Formatador) ERRO VALIDAÇÃO: {ve}"); raise ve
    except Exception as e: print(f"(Tabela Preços Formatador) ERRO INESPERADO: {e}"); traceback.print_exc(); raise RuntimeError(f"Erro inesperado: {e}") from e