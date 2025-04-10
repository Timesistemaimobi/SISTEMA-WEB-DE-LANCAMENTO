# formatadores/tabela_precos_formatador.py

import pandas as pd
import numpy as np
import io
import traceback
import openpyxl
from openpyxl.styles import PatternFill, Font, Border, Side, Alignment, Color
from openpyxl.utils import get_column_letter

# --- Funções Auxiliares Específicas ---

def format_currency_brl(value):
    """Formata um número como moeda BRL (R$ xxx.xxx,xx). Refinada."""
    if pd.isna(value): return ""
    try:
        # Formata com 2 decimais, ponto como separador decimal e _ como milhar
        formatted = f"{float(value):_.2f}"
        # Troca _ por . (milhar) e o . decimal por ,
        formatted = formatted.replace('.', '#TEMP_DECIMAL#').replace('_', '.').replace('#TEMP_DECIMAL#', ',')
        return f"R$ {formatted}"
    except (ValueError, TypeError):
        print(f"Aviso: Falha ao formatar moeda BRL para o valor: {value}")
        return str(value)

def format_area(value, decimal_places=2, suffix="m²", shift_decimal_left=0):
    try:
        if pd.isna(value):
            return "--"
        
        # Aplica o shift decimal (divide por 10^n)
        shifted_value = value / (10 ** shift_decimal_left)
        
        # Formata com casas decimais e adiciona o sufixo
        formatted = f"{round(shifted_value, decimal_places):,.{decimal_places}f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{formatted} {suffix}"
    except Exception as e:
        return f"Erro: {e}"

def map_tipologia(row):
    """Combina TIPOLOGIA e PAVIMENTO da entrada para a saída formatada."""
    tipo_in = str(row.get('TIPOLOGIA', '')).strip()
    pav_in = str(row.get('PAVIMENTO', '')).strip().upper()
    base_tipo = "TIPOLOGIA DESCONHECIDA"
    if '2 quartos' in tipo_in.lower() and 'suíte' in tipo_in.lower():
        base_tipo = "2 QUARTOS SENDO UMA SUÍTE"
    elif '3 quartos' in tipo_in.lower() and 'suíte' in tipo_in.lower():
        base_tipo = "3 QUARTOS SENDO UMA SUÍTE"

    if pav_in == 'TÉRREO':
        return f"{base_tipo} - TÉRREO"
    elif pav_in == 'SUPERIOR':
        return f"{base_tipo} - 1º ANDAR"
    elif pav_in:
        return f"{base_tipo} - {pav_in}"
    else:
        return base_tipo

# --- Função Principal de Processamento ---

def processar_tabela_precos_web(input_filepath):
    """
    Processa a planilha de tabela de preços e aplica formatação visual detalhada.
    """
    print(f"(Tabela Preços Formatador) Iniciando processamento para: {input_filepath}")
    try:
        # 1. Ler a planilha de entrada (ajustar skiprows conforme necessário)
        # Voltando para header=3 (linha 4 do excel) conforme o código anterior
        NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL = 3
        linhas_para_pular = NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL - 1
        try:
            df_input = pd.read_excel(input_filepath, engine='openpyxl', skiprows=linhas_para_pular, header=0, dtype=str)
            df_input.columns = df_input.columns.str.strip()
            print(f"  Lido {len(df_input)} linhas. Colunas encontradas: {df_input.columns.tolist()}")
        except Exception as read_err:
             raise ValueError(f"Erro ao ler o arquivo Excel: {read_err}. Verifique o arquivo e o número da linha do cabeçalho ({NUMERO_DA_LINHA_DO_CABECALHO_NO_EXCEL}).")

        # 2. Validação de Colunas Essenciais
        required_cols_in = ['BLOCO', 'PAVIMENTO', 'APT', 'TIPOLOGIA', 'ÁREA CONSTRUÍDA', 'QUINTAL', 'VALOR DO IMÓVEL']
        missing_cols = [col for col in required_cols_in if col not in df_input.columns]
        if missing_cols:
            raise ValueError(f"Colunas obrigatórias não encontradas na entrada: {', '.join(missing_cols)}. Colunas encontradas: {df_input.columns.tolist()}")
        print("  Colunas de entrada essenciais validadas.")

        # 3. Pré-processamento dos Dados
        df_input['BLOCO'] = df_input['BLOCO'].ffill()
        df_input['BLOCO'] = pd.to_numeric(df_input['BLOCO'], errors='coerce').fillna(0).astype(int)

        numeric_cols_in = {'ÁREA CONSTRUÍDA': 'area_construida_num', 'QUINTAL': 'quintal_num', 'VALOR DO IMÓVEL': 'valor_imovel_num'}
        for col_in, col_num in numeric_cols_in.items():
            # --- CORREÇÃO NA LÓGICA DE LIMPEZA NUMÉRICA ---
            original_series = df_input[col_in].astype(str)
            # 1. Remove R$ e espaços (principalmente para VALOR)
            cleaned_series = original_series.str.replace(r'[R$\s]', '', regex=True)
            # 2. Remove pontos '.' (assumidos como separador de milhar)
            cleaned_series = cleaned_series.str.replace('.', '', regex=False)
            # 3. Troca vírgula ',' (assumida como separador decimal) por ponto '.'
            cleaned_series = cleaned_series.str.replace(',', '.', regex=False)
            # 4. Converte para numérico
            converted_values = pd.to_numeric(cleaned_series, errors='coerce')
            df_input[col_num] = converted_values.fillna(0)
            # --- FIM DA CORREÇÃO ---

        print("  Pré-processamento concluído.")

        # 4. Transformar Dados para o Formato de Saída
        df_output = pd.DataFrame()
        df_output['UNIDADE'] = df_input['APT'].astype(str).str.zfill(2)
        df_output['TIPOLOGIA'] = df_input.apply(map_tipologia, axis=1)
        # --- GARANTIR 2 CASAS DECIMAIS E SUFIXO/TRAÇO CORRETOS ---
        df_output['ÁREA CONSTRUÍDA'] = df_input['area_construida_num'].apply(lambda x: format_area(x, decimal_places=2, suffix="m²", shift_decimal_left=2)) # 2 casas decimais
        df_output['QUINTAL'] = df_input['quintal_num'].apply(lambda x: '--' if np.isclose(x, 0) else format_area(x, decimal_places=2, suffix="m", shift_decimal_left=2)) # 2 casas decimais, sem sufixo
        # --- FIM DA GARANTIA ---
        df_output['GARAGEM'] = "01 VAGA"
        df_output['VALOR DO IMÓVEL'] = df_input['valor_imovel_num'].apply(format_currency_brl)
        df_output['BLOCO'] = df_input['BLOCO']
        print("  Transformações de dados concluídas.")

        # 5. Construir a Estrutura da Planilha de Saída (com espaços)
        # (Código de construção da estrutura final_sheet_data permanece o mesmo)
        final_sheet_data = []
        final_sheet_data.extend([([None] * 6)] * 2)
        final_sheet_data.append(["TABELA DE PREÇO 5.0 - DONA OLIVIA CIACCI RESIDENCIAL"] + [None] * 5)
        final_sheet_data.append([None] * 6)
        final_sheet_data.append(["ETAPA 01"] + [None] * 5)
        final_sheet_data.append([None] * 6)
        blocos = sorted(df_output['BLOCO'].unique())
        data_columns_ordered = ['UNIDADE', 'TIPOLOGIA', 'ÁREA CONSTRUÍDA', 'QUINTAL', 'GARAGEM', 'VALOR DO IMÓVEL']
        num_cols = len(data_columns_ordered)
        row_map = {'title': 3, 'etapa': 5, 'blocks': {}}
        current_excel_row = len(final_sheet_data) + 1
        for i, bloco_num in enumerate(blocos):
            bloco_header_excel_row = current_excel_row
            blank_after_bloco_header_row = current_excel_row + 1
            data_header_excel_row = current_excel_row + 2
            final_sheet_data.append([f"BLOCO {bloco_num:02d}"] + [None] * (num_cols - 1))
            final_sheet_data.append([None] * num_cols)
            final_sheet_data.append(data_columns_ordered)
            df_bloco_data = df_output[df_output['BLOCO'] == bloco_num][data_columns_ordered]
            data_rows = [list(row) for _, row in df_bloco_data.iterrows()]
            final_sheet_data.extend(data_rows)
            row_map['blocks'][bloco_num] = {'bloco_header': bloco_header_excel_row, 'blank_after_bloco': blank_after_bloco_header_row, 'data_header': data_header_excel_row, 'data_start': data_header_excel_row + 1, 'data_end': data_header_excel_row + len(data_rows)}
            next_start_row = data_header_excel_row + 1 + len(data_rows)
            if i < len(blocos) - 1:
                 final_sheet_data.append([None] * num_cols)
                 next_start_row += 1
            current_excel_row = next_start_row
        print("  Estrutura final da planilha construída.")


        # 6. Escrever os Dados no Excel e Aplicar Estilos Detalhados
        # (Código de estilização permanece o mesmo da versão anterior)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_final_sheet = pd.DataFrame(final_sheet_data)
            df_final_sheet.to_excel(writer, sheet_name='Tabela Formatada', index=False, header=False)
            workbook = writer.book
            worksheet = writer.sheets['Tabela Formatada']
            print("  Aplicando estilos detalhados...")
            # Definir Estilos
            header_bg_color = "DDEBF7"; header_fill = PatternFill(start_color=header_bg_color, end_color=header_bg_color, fill_type="solid")
            title_font = Font(name='Calibri', size=11, bold=True, color="000000"); header_font = Font(name='Calibri', size=11, bold=True, color="000000"); data_font = Font(name='Calibri', size=11, bold=False, color="000000")
            center_align = Alignment(horizontal='center', vertical='center', wrap_text=True)
            thin_border_side = Side(style='thin', color="000000"); thin_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side); top_bottom_border = Border(top=thin_border_side, bottom=thin_border_side)
            # Aplicar Estilos Fixos
            worksheet.merge_cells(start_row=row_map['title'], start_column=1, end_row=row_map['title'], end_column=num_cols); cell_title = worksheet.cell(row=row_map['title'], column=1); cell_title.font = title_font; cell_title.alignment = center_align
            worksheet.merge_cells(start_row=row_map['etapa'], start_column=1, end_row=row_map['etapa'], end_column=num_cols); cell_etapa = worksheet.cell(row=row_map['etapa'], column=1); cell_etapa.font = title_font; cell_etapa.alignment = center_align
            # Aplicar Estilos por Bloco
            for bloco_num, rows_info in row_map['blocks'].items():
                bloco_header_r = rows_info['bloco_header']; data_header_r = rows_info['data_header']; data_start_r = rows_info['data_start']; data_end_r = rows_info['data_end']
                worksheet.merge_cells(start_row=bloco_header_r, start_column=1, end_row=bloco_header_r, end_column=num_cols); cell_bloco = worksheet.cell(row=bloco_header_r, column=1); cell_bloco.fill = header_fill; cell_bloco.font = header_font; cell_bloco.alignment = center_align; cell_bloco.border = top_bottom_border
                for c_idx in range(1, num_cols + 1): # Data Header
                    cell = worksheet.cell(row=data_header_r, column=c_idx); cell.fill = header_fill; cell.font = header_font; cell.alignment = center_align; cell.border = thin_border
                for r in range(data_start_r, data_end_r + 1): # Data Rows
                    for c_idx in range(1, num_cols + 1):
                        cell = worksheet.cell(row=r, column=c_idx); cell.font = data_font; cell.alignment = center_align; cell.border = thin_border
            # Ajustar Largura
            col_widths = {'A': 10, 'B': 45, 'C': 18, 'D': 12, 'E': 15, 'F': 20}
            for col_letter, width in col_widths.items():
                try: worksheet.column_dimensions[col_letter].width = width
                except Exception as e: print(f"Aviso: não foi possível definir largura para coluna {col_letter}: {e}")
            print("  Estilos detalhados aplicados.")

        output.seek(0)
        print("(Tabela Preços Formatador) Processamento concluído.")
        return output

    except ValueError as ve:
        print(f"(Tabela Preços Formatador) ERRO de VALIDAÇÃO/PROCESSAMENTO: {ve}")
        raise ve # Re-lança para Flask exibir no flash
    except Exception as e:
        print(f"(Tabela Preços Formatador) ERRO INESPERADO: {e}")
        traceback.print_exc()
        raise RuntimeError(f"Ocorreu um erro inesperado: {e}") from e