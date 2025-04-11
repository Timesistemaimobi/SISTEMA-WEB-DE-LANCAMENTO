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

# --- Funções Auxiliares de Normalização e Busca (Mantidas) ---
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

# --- Funções de Formatação Específicas (NOVA FUNÇÃO DE PARSE) ---

def parse_flexible_float(value_str):
    """
    Tenta converter uma string (potencialmente com R$, m², etc. e diferentes
    separadores decimais/milhares) para um float de forma mais robusta.
    """
    if value_str is None: return None
    # Converte para string e remove espaços extras
    text = str(value_str).strip()
    if not text: return None

    # Remove caracteres não numéricos comuns (exceto , . -)
    # Mantém dígitos, vírgula, ponto e sinal de menos
    cleaned_text = re.sub(r'[^\d,\.-]', '', text)
    if not cleaned_text: return None

    # Determina o separador decimal mais provável
    last_dot = cleaned_text.rfind('.')
    last_comma = cleaned_text.rfind(',')

    # Assume BR (vírgula decimal) se vírgula for o último separador
    if last_comma > last_dot:
        # Remove pontos (milhares) e substitui a última vírgula por ponto
        num_str = cleaned_text.replace('.', '').replace(',', '.')
    # Assume US (ponto decimal) se ponto for o último ou único separador
    elif last_dot > last_comma:
        # Remove vírgulas (milhares)
        num_str = cleaned_text.replace(',', '')
    # Se não houver separadores, ou apenas um tipo, trata como número direto
    # (mas pode precisar de ajuste se só tiver vírgula)
    elif last_comma != -1 and last_dot == -1: # Só vírgula, assume BR decimal
        num_str = cleaned_text.replace(',', '.')
    else: # Só ponto (assume US decimal) ou nenhum separador
        num_str = cleaned_text

    try:
        return float(num_str)
    except (ValueError, TypeError):
        # print(f"Debug: parse_flexible_float falhou para '{value_str}' -> '{num_str}'")
        return None

def format_currency_brl(numeric_value):
    # Formata como R$ xxx.xxx,xx (Mantido da v8)
    if numeric_value is None: return ""
    try:
        # Usa separador de milhar '.' e decimal ','
        formatted = f"{float(numeric_value):_.2f}".replace('.', '#').replace(',', '.').replace('#', ',') # Troca temporária
        # Maneira mais segura: formatar com locale ou manualmente com cuidado
        # f-string format:
        parts = f"{float(numeric_value):.2f}".split('.')
        integer_part = parts[0]
        decimal_part = parts[1]
        # Adiciona separador de milhar (ponto)
        integer_part_with_dots = ""
        n = len(integer_part)
        for i, digit in enumerate(reversed(integer_part)):
            integer_part_with_dots = digit + integer_part_with_dots
            if (i + 1) % 3 == 0 and i != n - 1:
                integer_part_with_dots = "." + integer_part_with_dots
        formatted = f"{integer_part_with_dots},{decimal_part}"
        return f"R$ {formatted}"
    except (ValueError, TypeError):
        return ""

def format_garagem_vagas(numeric_value):
    # Mantido da v8
    if numeric_value is None: return "01 VAGA"
    try:
        gn = float(numeric_value)
        if gn > 35: return "04 VAGAS"
        elif gn > 25: return "03 VAGAS"
        elif gn > 15: return "02 VAGAS"
        elif gn >= 0: return "01 VAGA"
        else: return "01 VAGA"
    except (ValueError, TypeError):
        return "01 VAGA"

# --- Função Principal de Processamento (v9 - Usa parse_flexible_float) ---

def processar_tabela_precos_web(input_filepath):
    print(f"(Tabela Preços Formatador - v9 Usa parse_flexible_float) Iniciando: {input_filepath}")
    try:
        # 1. Ler a planilha (igual v8)
        NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL = 3
        linhas_para_pular = NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL - 1
        try:
            df_input = pd.read_excel(input_filepath, engine='openpyxl', skiprows=linhas_para_pular, header=0, dtype=str).fillna('')
            df_input.columns = df_input.columns.str.strip()
            if df_input.empty: raise ValueError("Nenhum dado encontrado após cabeçalho.")
            print(f"  Lido {len(df_input)} linhas. Cabeçalho: {df_input.columns.tolist()}")
        except ValueError as ve: raise ve
        except Exception as read_err: raise ValueError(f"Erro ao ler Excel: {read_err}.")

        # 2. Definir Conceitos e Encontrar Colunas (igual v8)
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
        print("  Buscando colunas...")
        for concept, (keywords, is_required) in col_concepts.items():
            found_columns[concept] = find_column_flexible(df_input.columns, keywords, concept, required=is_required)
        print(f"  Mapeamento: {found_columns}")

        # 3. Preparar DataFrame Intermediário (igual v8 - copia como string)
        df_intermediate = pd.DataFrame()
        output_concept_order = ['UNIDADE', 'TIPOLOGIA', 'AREA_CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
        col_bloco_orig = found_columns.get('BLOCO')
        if not col_bloco_orig: raise ValueError("Coluna Bloco obrigatória não encontrada.")
        df_input[col_bloco_orig] = df_input[col_bloco_orig].replace('', np.nan).ffill().fillna('BLOCO_N/A')
        df_intermediate['BLOCO'] = df_input[col_bloco_orig]
        print("  Copiando dados originais...")
        for concept in output_concept_order:
            original_col_name = found_columns.get(concept)
            df_intermediate[concept] = df_input[original_col_name].astype(str).copy() if original_col_name else ''

        # 4. Ordenar Blocos Numericamente (igual v8)
        unique_block_vals = df_intermediate['BLOCO'].unique()
        sortable_blocks = []
        non_numeric_blocks = []
        for block_str in unique_block_vals:
            numeric_key = extract_block_number_safe(block_str)
            if numeric_key is not None: sortable_blocks.append((numeric_key, block_str))
            else: non_numeric_blocks.append(block_str)
        sortable_blocks.sort(key=lambda item: item[0])
        blocos_ordenados = [item[1] for item in sortable_blocks] + sorted(non_numeric_blocks)
        print(f"  Blocos ordenados para processamento: {blocos_ordenados}")

        # 5. Construir a Estrutura da Planilha de Saída (LÓGICA DE FORMATAÇÃO v9)
        output_headers = ['UNIDADE', 'TIPOLOGIA', 'ÁREA CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'VALOR']
        num_cols = len(output_headers)
        final_sheet_data = []
        # --- Adiciona linhas de título/etapa (igual v8) ---
        final_sheet_data.extend([([None] * num_cols)] * 2)
        output_title = "TABELA DE PREÇOS"; output_etapa = "ETAPA ÚNICA"
        final_sheet_data.append([output_title] + [None] * (num_cols - 1))
        final_sheet_data.append([None] * num_cols)
        final_sheet_data.append([output_etapa] + [None] * (num_cols - 1))
        final_sheet_data.append([None] * num_cols)

        row_map = {'title': 3, 'etapa': 5, 'blocks': {}}
        current_excel_row = len(final_sheet_data) + 1

        print(f"  Construindo layout final e aplicando formatação (Iterando sobre {len(blocos_ordenados)} blocos ordenados)...")
        for i, bloco_val_orig in enumerate(blocos_ordenados):
            bloco_header_excel_row = current_excel_row
            data_header_excel_row = current_excel_row + 2
            block_num = extract_block_number_safe(bloco_val_orig)
            block_display_name = f"BLOCO {block_num:02d}" if block_num is not None else str(bloco_val_orig).upper()
            # --- Adiciona cabeçalhos (igual v8) ---
            final_sheet_data.append([block_display_name] + [None] * (num_cols - 1))
            final_sheet_data.append([None] * num_cols)
            final_sheet_data.append(output_headers)

            # --- Filtra e FORMATA os dados (LÓGICA v9) ---
            df_bloco_data = df_intermediate[df_intermediate['BLOCO'] == bloco_val_orig][output_concept_order]
            formatted_data_rows = []
            for _, row in df_bloco_data.iterrows():
                formatted_row = []
                for concept in output_concept_order:
                    original_value_str = str(row.get(concept, ''))
                    formatted_val = original_value_str # Fallback: começa com o valor original

                    # --- LÓGICA DE FORMATAÇÃO ESPECÍFICA POR CONCEITO (v9) ---
                    if concept in ['AREA_CONSTRUIDA', 'QUINTAL']:
                        # <<< MODIFICAÇÃO v9: Usa parse_flexible_float e formata como XX,XX m² >>>
                        # Tenta parsear usando a função mais robusta
                        numeric_value = parse_flexible_float(original_value_str)
                        placeholder = "--"

                        if numeric_value is not None:
                            # Verifica se é zero após conversão
                            if np.isclose(numeric_value, 0):
                                formatted_val = placeholder
                            else:
                                # Formata para 2 decimais (com ponto) e substitui por vírgula
                                formatted_num_comma = f"{numeric_value:.2f}".replace('.', ',')
                                formatted_val = f"{formatted_num_comma}m²"
                        else:
                            # Parse falhou
                            if not original_value_str.strip(): # String original vazia
                                formatted_val = placeholder
                            # else: mantém original (já está em formatted_val)

                    elif concept == 'GARAGEM':
                        # Usa parse_flexible_float também para robustez
                        numeric_value = parse_flexible_float(original_value_str)
                        if numeric_value is not None:
                            formatted_val = format_garagem_vagas(numeric_value)
                        # else: mantém o texto original

                    elif concept == 'VALOR':
                        # Usa parse_flexible_float e formata como R$ xxx.xxx,xx
                        numeric_value = parse_flexible_float(original_value_str)
                        if numeric_value is not None:
                             formatted_val = format_currency_brl(numeric_value)
                        # else: mantém o texto original

                    # Para UNIDADE, TIPOLOGIA, mantém o texto original

                    formatted_row.append(formatted_val)
                formatted_data_rows.append(formatted_row)

            final_sheet_data.extend(formatted_data_rows)
            # --- Guarda info para estilos e calcula próxima linha (igual v8) ---
            row_map_key = bloco_val_orig
            row_map['blocks'][row_map_key] = {
                'bloco_header': bloco_header_excel_row, 'blank_after_bloco': bloco_header_excel_row + 1,
                'data_header': data_header_excel_row, 'data_start': data_header_excel_row + 1,
                'data_end': data_header_excel_row + len(formatted_data_rows)
            }
            current_excel_row = data_header_excel_row + 1 + len(formatted_data_rows)
            if i < len(blocos_ordenados) - 1: final_sheet_data.append([None] * num_cols); current_excel_row += 1

        print("  Layout e formatação concluídos.")

        # 6. Escrever no Excel e Aplicar Estilos Visuais (Igual v8)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_final_sheet = pd.DataFrame(final_sheet_data)
            df_final_sheet.to_excel(writer, sheet_name='Tabela Formatada', index=False, header=False)

            workbook = writer.book
            worksheet = writer.sheets['Tabela Formatada']
            print("  Aplicando estilos visuais...")

            # --- Definição e Aplicação de Estilos (igual v8) ---
            header_bg_color = "DDEBF7"
            header_fill = PatternFill(start_color=header_bg_color, end_color=header_bg_color, fill_type="solid")
            title_font = Font(name='Calibri', size=11, bold=True, color="000000")
            header_font = Font(name='Calibri', size=11, bold=True, color="000000")
            data_font = Font(name='Calibri', size=11, bold=False, color="000000")
            center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
            thin_border_side = Side(style='thin', color="000000")
            thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
            top_bottom_border = Border(top=thin_border_side, bottom=thin_border_side)

            worksheet.merge_cells(start_row=row_map['title'], start_column=1, end_row=row_map['title'], end_column=num_cols)
            worksheet.cell(row=row_map['title'], column=1).font = title_font
            worksheet.cell(row=row_map['title'], column=1).alignment = center_align
            worksheet.merge_cells(start_row=row_map['etapa'], start_column=1, end_row=row_map['etapa'], end_column=num_cols)
            worksheet.cell(row=row_map['etapa'], column=1).font = title_font
            worksheet.cell(row=row_map['etapa'], column=1).alignment = center_align

            for row_map_key, rows_info in row_map['blocks'].items():
                bloco_header_r, data_header_r = rows_info['bloco_header'], rows_info['data_header']
                data_start_r, data_end_r = rows_info['data_start'], rows_info['data_end']

                worksheet.merge_cells(start_row=bloco_header_r, start_column=1, end_row=bloco_header_r, end_column=num_cols)
                cell_bloco = worksheet.cell(row=bloco_header_r, column=1)
                cell_bloco.fill, cell_bloco.font, cell_bloco.alignment, cell_bloco.border = header_fill, header_font, center_align, top_bottom_border

                for c_idx in range(1, num_cols + 1):
                    cell = worksheet.cell(row=data_header_r, column=c_idx)
                    cell.fill, cell.font, cell.alignment, cell.border = header_fill, header_font, center_align, thin_border

                for r in range(data_start_r, data_end_r + 1):
                    for c_idx in range(1, num_cols + 1):
                        cell = worksheet.cell(row=r, column=c_idx)
                        cell.font, cell.alignment, cell.border = data_font, center_align, thin_border
                        # Aplica formato Texto se o valor for string e não for placeholder ou vazio
                        if cell.value is not None and isinstance(cell.value, str) and cell.value.strip() and cell.value != '--':
                             cell.number_format = '@' # Força a ser texto no Excel

            # Ajuste de Largura (igual v8)
            col_widths = {'A': 10, 'B': 45, 'C': 18, 'D': 12, 'E': 15, 'F': 20}
            for i, col_letter in enumerate([get_column_letter(j+1) for j in range(num_cols)]):
                 width = col_widths.get(col_letter)
                 if width:
                     try: worksheet.column_dimensions[col_letter].width = width
                     except Exception as e: print(f"Aviso: Falha ao definir largura {col_letter}: {e}")
                 else: print(f"Aviso: Largura não definida para {col_letter}.")

            print("  Estilos visuais aplicados.")

        output.seek(0)
        print("(Tabela Preços Formatador - v9 Usa parse_flexible_float) Processamento concluído.")
        return output

    except ValueError as ve:
        print(f"(Tabela Preços Formatador) ERRO VALIDAÇÃO: {ve}")
        raise ve
    except Exception as e:
        print(f"(Tabela Preços Formatador) ERRO INESPERADO: {e}")
        traceback.print_exc()
        raise RuntimeError(f"Erro inesperado ao formatar Tabela de Preços: {e}") from e