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
from collections import defaultdict # Para agrupar blocos por etapa

# --- Funções Auxiliares (parse_flexible_float, normalize_text, find_column, extract_block_number - Mantidas da v9) ---
def normalize_text_for_match(text):
    if not isinstance(text, str): text = str(text)
    try:
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        text = text.lower()
        text = re.sub(r'[^a-z0-9]', '', text)
        return text.strip()
    except Exception:
        return str(text).lower().strip()

def find_column_flexible(df_columns, concept_keywords, concept_name, required=True):
    normalized_input_cols = {normalize_text_for_match(col): col for col in df_columns}
    found_col_name = None
    for keyword in concept_keywords: # Match exato
        norm_keyword = normalize_text_for_match(keyword)
        if norm_keyword in normalized_input_cols:
            return normalized_input_cols[norm_keyword]
    potential_matches = []
    for keyword in concept_keywords: # Match parcial
        norm_keyword = normalize_text_for_match(keyword)
        for norm_col, orig_col in normalized_input_cols.items():
            if norm_keyword in norm_col:
                 priority = 0 if norm_col.startswith(norm_keyword) else 1
                 potential_matches.append((priority, orig_col))
    if potential_matches:
        potential_matches.sort()
        return potential_matches[0][1]
    if required: # Erro
        raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada. Keywords: {concept_keywords}. Cols. normalizadas: {list(normalized_input_cols.keys())}")
    return None

def extract_block_number_safe(block_value_str):
    if not isinstance(block_value_str, str): block_value_str = str(block_value_str)
    match = re.search(r'\d+', block_value_str)
    if match:
        try: return int(match.group(0))
        except ValueError: return None
    return None

def parse_flexible_float(value_str):
    if value_str is None: return None
    text = str(value_str).strip()
    if not text: return None
    cleaned_text = re.sub(r'[^\d,\.-]', '', text)
    if not cleaned_text: return None
    last_dot = cleaned_text.rfind('.')
    last_comma = cleaned_text.rfind(',')
    if last_comma > last_dot:
        num_str = cleaned_text.replace('.', '').replace(',', '.')
    elif last_dot > last_comma:
        num_str = cleaned_text.replace(',', '')
    elif last_comma != -1 and last_dot == -1:
        num_str = cleaned_text.replace(',', '.')
    else:
        num_str = cleaned_text
    try: return float(num_str)
    except (ValueError, TypeError): return None

def format_currency_brl(numeric_value):
    if numeric_value is None: return ""
    try:
        parts = f"{float(numeric_value):.2f}".split('.')
        integer_part = parts[0]; decimal_part = parts[1]
        integer_part_with_dots = ""
        n = len(integer_part)
        for i, digit in enumerate(reversed(integer_part)):
            integer_part_with_dots = digit + integer_part_with_dots
            if (i + 1) % 3 == 0 and i != n - 1: integer_part_with_dots = "." + integer_part_with_dots
        formatted = f"{integer_part_with_dots},{decimal_part}"
        return f"R$ {formatted}"
    except (ValueError, TypeError): return ""

def format_garagem_vagas(numeric_value):
    if numeric_value is None: return "01 VAGA"
    try:
        gn = float(numeric_value)
        if gn > 35: return "04 VAGAS"
        elif gn > 25: return "03 VAGAS"
        elif gn > 15: return "02 VAGAS"
        elif gn >= 0: return "01 VAGA"
        else: return "01 VAGA"
    except (ValueError, TypeError): return "01 VAGA"

def extract_stage_number(stage_name_str):
    """Tenta extrair um número do nome da etapa para ordenação."""
    match = re.search(r'\d+', stage_name_str)
    if match:
        try: return int(match.group(0))
        except ValueError: return float('inf') # Não numérico vai para o fim
    return float('inf') # Sem número vai para o fim

# --- Função Principal de Processamento (v10 - Aceita Mapeamento de Etapas) ---

def processar_tabela_precos_web(input_filepath, block_etapa_mapping):
    print(f"(Tabela Preços Formatador - v11 Valor Numérico + Formato Excel) Iniciando: {input_filepath}")
    try:
        # 1. Ler a planilha (igual v10)
        NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL = 3
        linhas_para_pular = NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL - 1
        try:
            df_input = pd.read_excel(input_filepath, engine='openpyxl', skiprows=linhas_para_pular, header=0, dtype=str).fillna('')
            df_input.columns = df_input.columns.str.strip()
            if df_input.empty: raise ValueError("Nenhum dado encontrado após cabeçalho.")
        except Exception as read_err: raise ValueError(f"Erro ao ler Excel: {read_err}.")

        # 2. Definir Conceitos e Encontrar Colunas (igual v10)
        col_concepts = {
            'BLOCO': (['bloco', 'blk', 'quadra'], True),
            'UNIDADE': (['apt', 'apto', 'apartamento', 'unidade', 'casa', 'unid', 'ap'], True),
            'TIPOLOGIA': (['tipologia', 'tipo', 'descricao', 'descrição'], True),
            'AREA_CONSTRUIDA': (['area construida', 'área construída', 'areaconstruida', 'area util', 'área útil', 'area privativa', 'área privativa'], True),
            'QUINTAL': (['quintal', 'jardim', 'area descoberta', 'área descoberta', 'area externa', 'área externa', 'quintal m2', 'jardim m2'], False),
            'GARAGEM': (['garagem', 'vaga', 'vagas', 'estacionamento'], False),
            'VALOR': (['valor', 'preco', 'preço', 'valor imovel', 'valor do imóvel', 'valor venda'], True)
        }
        found_columns = {}
        for concept, (keywords, is_required) in col_concepts.items():
            found_columns[concept] = find_column_flexible(df_input.columns, keywords, concept, required=is_required)

        # 3. Preparar DataFrame Intermediário (igual v10)
        df_intermediate = pd.DataFrame()
        output_concept_order = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
        col_bloco_orig = found_columns.get('BLOCO')
        if not col_bloco_orig: raise ValueError("Coluna Bloco obrigatória não encontrada.")
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

        # 4. Agrupar e Ordenar por Etapa e Bloco (igual v10)
        etapas_agrupadas = defaultdict(list)
        for _, row in df_intermediate[['BLOCO_ORIGINAL', 'ETAPA_MAPEADA']].drop_duplicates().iterrows():
            etapa, bloco = row['ETAPA_MAPEADA'], row['BLOCO_ORIGINAL']
            if pd.notna(bloco) and str(bloco).lower() != 'nan': etapas_agrupadas[etapa].append(bloco)
        etapas_ordenadas = sorted(etapas_agrupadas.keys(), key=lambda e: (extract_stage_number(e), e))
        blocos_ordenados_por_etapa = {}
        for etapa in etapas_ordenadas:
            blocos_da_etapa = etapas_agrupadas[etapa]
            blocos_ordenados_por_etapa[etapa] = sorted(blocos_da_etapa, key=lambda b: extract_block_number_safe(b) if extract_block_number_safe(b) is not None else float('inf'))

        # 5. Construir a Estrutura da Planilha de Saída (AJUSTE PARA 'VALOR')
        output_headers = ['UNIDADE', 'TIPOLOGIA', 'ÁREA CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
        num_cols = len(output_headers)
        final_sheet_data = []
        # --- Cabeçalhos e estrutura (igual v10) ---
        final_sheet_data.extend([([None] * num_cols)] * 2)
        output_title = "TABELA DE PREÇOS"
        final_sheet_data.append([output_title] + [None] * (num_cols - 1))
        final_sheet_data.append([None] * num_cols)
        row_map = {'title': 3, 'etapas': {}}
        current_excel_row = len(final_sheet_data) + 1

        print(f"  Construindo layout final com etapas e formatando dados...")
        for etapa_idx, etapa_nome in enumerate(etapas_ordenadas):
            etapa_header_excel_row = current_excel_row
            row_map['etapas'][etapa_nome] = {'header_row': etapa_header_excel_row, 'blocks': {}}
            final_sheet_data.append([etapa_nome] + [None] * (num_cols - 1))
            final_sheet_data.append([None] * num_cols)
            current_excel_row += 2

            blocos_desta_etapa = blocos_ordenados_por_etapa[etapa_nome]
            for bloco_idx, bloco_val_orig in enumerate(blocos_desta_etapa):
                bloco_header_excel_row = current_excel_row
                data_header_excel_row = current_excel_row + 2
                block_num = extract_block_number_safe(bloco_val_orig)
                block_display_name = f"BLOCO {block_num:02d}" if block_num is not None else str(bloco_val_orig).upper()
                final_sheet_data.append([block_display_name] + [None] * (num_cols - 1))
                final_sheet_data.append([None] * num_cols)
                final_sheet_data.append(output_headers)

                df_bloco_data = df_intermediate[df_intermediate['BLOCO_ORIGINAL'] == bloco_val_orig][output_concept_order]
                formatted_data_rows = []
                for _, row in df_bloco_data.iterrows():
                    processed_row = [] # Guarda a linha processada (pode ter floats)
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
                            numeric_value = parse_flexible_float(original_value_str)
                            if numeric_value is not None: processed_val = format_garagem_vagas(numeric_value)
                        elif concept == 'VALOR':
                            # <<< MUDANÇA AQUI: Guarda o float ou None >>>
                            numeric_value = parse_flexible_float(original_value_str)
                            # Guarda o valor numérico ou None se não puder converter
                            processed_val = numeric_value if numeric_value is not None else None
                            # Se não conseguiu converter e a string original não estava vazia,
                            # podemos decidir manter a string original ou deixar None.
                            # Vamos preferir None/vazio para não poluir a coluna numérica.
                            if numeric_value is None and original_value_str.strip():
                                print(f"Aviso: Valor '{original_value_str}' não convertido para numérico. Será deixado em branco.")
                                processed_val = None # Garante que não vai string

                        processed_row.append(processed_val)
                    formatted_data_rows.append(processed_row)

                final_sheet_data.extend(formatted_data_rows)

                # --- Guarda info para estilos (igual v10) ---
                row_map['etapas'][etapa_nome]['blocks'][bloco_val_orig] = {
                    'bloco_header': bloco_header_excel_row,
                    'blank_after_bloco': bloco_header_excel_row + 1,
                    'data_header': data_header_excel_row,
                    'data_start': data_header_excel_row + 1,
                    'data_end': data_header_excel_row + len(formatted_data_rows)
                }
                current_excel_row = data_header_excel_row + 1 + len(formatted_data_rows)
                if bloco_idx < len(blocos_desta_etapa) - 1:
                    final_sheet_data.append([None] * num_cols); current_excel_row += 1
            if etapa_idx < len(etapas_ordenadas) - 1:
                 final_sheet_data.extend([([None] * num_cols)] * 2); current_excel_row += 2

        print("  Layout com etapas e dados preparados (valor como numérico).")

        # 6. Escrever no Excel e Aplicar Estilos Visuais (APLICAR FORMATO DE MOEDA)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            # Escreve os dados (coluna VALOR agora contém floats ou None)
            df_final_sheet = pd.DataFrame(final_sheet_data)
            df_final_sheet.to_excel(writer, sheet_name='Tabela Formatada', index=False, header=False)

            workbook = writer.book
            worksheet = writer.sheets['Tabela Formatada']
            print("  Aplicando estilos visuais e formato de moeda...")

            # --- Definição de Estilos e Formato de Moeda ---
            # ... (definições de fill, font, align, border - iguais v10) ...
            header_bg_color = "DDEBF7"; etapa_header_bg_color = "FFF2CC"; bloco_header_bg_color = "E2EFDA"
            title_fill = PatternFill(start_color=header_bg_color, end_color=header_bg_color, fill_type="solid")
            etapa_fill = PatternFill(start_color=etapa_header_bg_color, end_color=etapa_header_bg_color, fill_type="solid")
            bloco_fill = PatternFill(start_color=bloco_header_bg_color, end_color=bloco_header_bg_color, fill_type="solid")
            data_header_fill = PatternFill(start_color=header_bg_color, end_color=header_bg_color, fill_type="solid")
            title_font = Font(name='Calibri', size=11, bold=True, color="000000")
            etapa_font = Font(name='Calibri', size=11, bold=True, color="000000")
            bloco_font = Font(name='Calibri', size=11, bold=True, color="000000")
            data_header_font = Font(name='Calibri', size=11, bold=True, color="000000")
            data_font = Font(name='Calibri', size=11, bold=False, color="000000")
            center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
            thin_border_side = Side(style='thin', color="000000")
            thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
            top_bottom_border = Border(top=thin_border_side, bottom=thin_border_side)

            # <<< NOVO: Formato de Moeda BRL para Excel >>>
            # R$ -> Símbolo Real
            # #,##0.00 -> Separador de milhar (.), duas casas decimais (,)
            # O formato completo pode lidar com negativos e zero, mas este é comum.
            brl_currency_format = 'R$ #,##0.00'
            # Formato de texto explícito (para outras colunas se necessário)
            text_format = '@'

            # --- Aplicação de Estilos ---
            # Título Principal (igual v10)
            worksheet.merge_cells(start_row=row_map['title'], start_column=1, end_row=row_map['title'], end_column=num_cols)
            cell_title = worksheet.cell(row=row_map['title'], column=1)
            cell_title.font = title_font; cell_title.alignment = center_align

            # Encontrar índice da coluna VALOR (1-based)
            try:
                valor_col_index = output_headers.index('VALOR') + 1
            except ValueError:
                print("ERRO CRÍTICO: Coluna 'VALOR' não encontrada nos cabeçalhos de saída.")
                valor_col_index = -1 # Evita erro, mas formato não será aplicado

            # Itera sobre Etapas e Blocos para aplicar estilos e FORMATO DE MOEDA
            for etapa_nome, etapa_info in row_map['etapas'].items():
                etapa_header_r = etapa_info['header_row']
                worksheet.merge_cells(start_row=etapa_header_r, start_column=1, end_row=etapa_header_r, end_column=num_cols)
                cell_etapa = worksheet.cell(row=etapa_header_r, column=1)
                cell_etapa.fill = etapa_fill; cell_etapa.font = etapa_font; cell_etapa.alignment = center_align; cell_etapa.border = top_bottom_border

                for bloco_val_orig, rows_info in etapa_info['blocks'].items():
                    bloco_header_r = rows_info['bloco_header']
                    data_header_r = rows_info['data_header']
                    data_start_r = rows_info['data_start']
                    data_end_r = rows_info['data_end']

                    # Cabeçalho Bloco
                    worksheet.merge_cells(start_row=bloco_header_r, start_column=1, end_row=bloco_header_r, end_column=num_cols)
                    cell_bloco = worksheet.cell(row=bloco_header_r, column=1)
                    cell_bloco.fill = bloco_fill; cell_bloco.font = bloco_font; cell_bloco.alignment = center_align; cell_bloco.border = top_bottom_border

                    # Cabeçalho Dados
                    for c_idx in range(1, num_cols + 1):
                        cell = worksheet.cell(row=data_header_r, column=c_idx)
                        cell.fill = data_header_fill; cell.font = data_header_font; cell.alignment = center_align; cell.border = thin_border

                    # Linhas Dados - Aplicar estilos e FORMATO DE MOEDA
                    for r in range(data_start_r, data_end_r + 1):
                        for c_idx in range(1, num_cols + 1):
                            cell = worksheet.cell(row=r, column=c_idx)
                            cell.font = data_font
                            cell.alignment = center_align
                            cell.border = thin_border

                            # <<< APLICA FORMATO DE NÚMERO >>>
                            if c_idx == valor_col_index and isinstance(cell.value, (int, float)):
                                # Aplica formato de moeda BRL se for a coluna VALOR e o valor for numérico
                                cell.number_format = brl_currency_format
                            elif isinstance(cell.value, str) and cell.value.strip() and cell.value != '--':
                                # Aplica formato Texto para strings não vazias (exceto VALOR)
                                cell.number_format = text_format

            # Ajuste de Largura (igual v10)
            col_widths = {'A': 10, 'B': 45, 'C': 18, 'D': 12, 'E': 15, 'F': 20}
            for i, col_letter in enumerate([get_column_letter(j+1) for j in range(num_cols)]):
                 width = col_widths.get(col_letter)
                 if width:
                     try: worksheet.column_dimensions[col_letter].width = width
                     except Exception as e: print(f"Aviso: Falha ao definir largura {col_letter}: {e}")

            print("  Estilos visuais e formato de moeda aplicados.")

        output.seek(0)
        print("(Tabela Preços Formatador - v11 Valor Numérico + Formato Excel) Processamento concluído.")
        return output

    # --- Blocos except (iguais v10) ---
    except ValueError as ve:
        print(f"(Tabela Preços Formatador) ERRO VALIDAÇÃO: {ve}")
        raise ve
    except Exception as e:
        print(f"(Tabela Preços Formatador) ERRO INESPERADO: {e}")
        traceback.print_exc()
        raise RuntimeError(f"Erro inesperado ao formatar Tabela de Preços: {e}") from e