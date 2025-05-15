# Em formatadores/tabela_unidades_bloqueadas.py (ou similar)
import pandas as pd
import io
import traceback
import re
import unicodedata

from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo # IMPORTANTE para Tabelas do Excel

# --- Funções Auxiliares (normalize_text_for_match, find_column_flexible) ---
# (Copie-as aqui ou importe-as como antes)
def normalize_text_for_match(text):
    if not isinstance(text, str): text = str(text)
    try:
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        text = text.lower()
        text = re.sub(r'[^a-z0-9]', '', text)
        return text.strip()
    except Exception:
        return str(text).lower().strip().replace(' ', '')

def find_column_flexible(df_columns, concept_keywords, concept_name, required=True):
    normalized_input_cols = {normalize_text_for_match(col): col for col in df_columns}
    found_col_name = None
    for keyword in concept_keywords:
        norm_keyword = normalize_text_for_match(keyword)
        if norm_keyword in normalized_input_cols:
            found_col_name = normalized_input_cols[norm_keyword]
            return found_col_name
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
        return found_col_name
    if required:
        raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada. Keywords: {concept_keywords}. Colunas originais: {list(df_columns)}")
    else:
        return None
# --- Fim Funções Auxiliares ---


def ler_csv_e_extrair_filtros(input_filepath):
    """
    Lê o CSV, identifica colunas de empreendimento e motivo,
    e retorna o DataFrame e listas únicas para filtro.
    """
    print(f"(Unidades Bloqueadas - Leitura CSV) Lendo: {input_filepath}")
    try:
        # Tentar detectar o separador
        with open(input_filepath, 'r', encoding='utf-8-sig') as f: # utf-8-sig para lidar com BOM
            primeira_linha = f.readline()
            if ';' in primeira_linha and ',' not in primeira_linha:
                sep = ';'
            elif ',' in primeira_linha and ';' not in primeira_linha:
                sep = ','
            else: # Default ou heurística mais complexa se necessário
                sep = ';' if primeira_linha.count(';') >= primeira_linha.count(',') else ','
                print(f"  Separador detectado heuristicamente: '{sep}'")

        df_input = pd.read_csv(input_filepath, dtype=str, keep_default_na=False, sep=sep, encoding='utf-8-sig')
        df_input.columns = [str(col).strip() for col in df_input.columns] # Limpa nomes de colunas
        
        if df_input.empty:
            raise ValueError("O arquivo CSV está vazio ou não pôde ser lido corretamente.")

        # Identificar colunas relevantes para filtro
        col_empreendimento_nome = find_column_flexible(df_input.columns, ['empreendimento', 'projeto', 'nome do empreendimento'], 'Empreendimento', required=True)
        col_motivo_bloqueio_nome = find_column_flexible(df_input.columns, ['motivo do bloqueio', 'motivo bloqueio', 'motivo'], 'Motivo do Bloqueio', required=True)

        empreendimentos_unicos = sorted(list(df_input[col_empreendimento_nome].str.strip().unique()))
        motivos_unicos = sorted(list(df_input[col_motivo_bloqueio_nome].str.strip().unique()))
        
        # Remover vazios se existirem nas listas de únicos
        empreendimentos_unicos = [emp for emp in empreendimentos_unicos if emp]
        motivos_unicos = [mot for mot in motivos_unicos if mot]


        print(f"  Coluna de Empreendimento encontrada: '{col_empreendimento_nome}'")
        print(f"  Coluna de Motivo do Bloqueio encontrada: '{col_motivo_bloqueio_nome}'")
        print(f"  Empreendimentos únicos: {empreendimentos_unicos}")
        print(f"  Motivos únicos: {motivos_unicos}")

        return df_input, empreendimentos_unicos, motivos_unicos, col_empreendimento_nome, col_motivo_bloqueio_nome

    except Exception as e:
        print(f"(Unidades Bloqueadas - Leitura CSV) ERRO: {e}")
        traceback.print_exc()
        raise


def processar_unidades_bloqueadas_csv(df_input, col_empreendimento_input,
                                   empreendimentos_a_ignorar=None, 
                                   motivos_a_ignorar=None):
    print(f"(Unidades Bloqueadas - Processamento CSV com Tabelas Excel)")
    # ... (prints e inicialização de listas a ignorar) ...

    try:
        # ... (Identificação de colunas e filtragem de df_input como antes) ...
        col_etapa_input = find_column_flexible(df_input.columns, ['etapa'], 'Etapa', required=False)
        col_bloco_input = find_column_flexible(df_input.columns, ['bloco', 'quadra'], 'Bloco/Quadra', required=True)
        col_unidade_input = find_column_flexible(df_input.columns, ['unidade', 'lote', 'identificacao da unidade', 'identificação da unidade'], 'Unidade/Lote', required=True)
        col_motivo_input = find_column_flexible(df_input.columns, ['motivo do bloqueio', 'motivo bloqueio', 'motivo'], 'Motivo do Bloqueio', required=True)
        col_descricao_input = find_column_flexible(df_input.columns, ['descrição', 'descricao', 'detalhes'], 'Descrição', required=False)
        col_data_bloqueio_input = find_column_flexible(df_input.columns, ['data do bloqueio', 'data bloqueio', 'data'], 'Data do Bloqueio', required=False)

        df_filtrado = df_input.copy()
        if empreendimentos_a_ignorar:
            df_filtrado = df_filtrado[~df_filtrado[col_empreendimento_input].astype(str).str.strip().isin([str(emp).strip() for emp in empreendimentos_a_ignorar])]
        if motivos_a_ignorar:
            df_filtrado = df_filtrado[~df_filtrado[col_motivo_input].astype(str).str.strip().isin([str(mot).strip() for mot in motivos_a_ignorar])]
        
        if df_filtrado.empty:
            # ... (código para retornar Excel com mensagem "Nenhum dado" como antes) ...
            from openpyxl import Workbook
            output_excel_stream = io.BytesIO()
            wb = Workbook(); ws = wb.active; ws.title = "Resultado"
            ws['A1'] = "Nenhum dado encontrado com os filtros aplicados."
            ws['A1'].font = Font(name='Calibri', size=12, bold=True)
            ws.column_dimensions['A'].width = 50
            wb.save(output_excel_stream); output_excel_stream.seek(0)
            return output_excel_stream

        empreendimentos_no_df_filtrado = sorted(list(df_filtrado[col_empreendimento_input].astype(str).str.strip().unique()))
        
        colunas_saida_map = {
            col_etapa_input: "Etapa", col_bloco_input: "Bloco", col_unidade_input: "Unidade",
            col_motivo_input: "Motivo do Bloqueio", col_descricao_input: "Descrição",
            col_data_bloqueio_input: "Data do Bloqueio"
        }
        colunas_de_entrada_existentes = [col for col in [col_etapa_input, col_bloco_input, col_unidade_input, col_motivo_input, col_descricao_input, col_data_bloqueio_input] if col is not None]
        nomes_colunas_saida_ordenadas = [colunas_saida_map[col] for col in colunas_de_entrada_existentes]

        output_excel_stream = io.BytesIO()
        with pd.ExcelWriter(output_excel_stream, engine='openpyxl') as writer:
            current_row_excel_pandas = 0 
            sheet_name_output = 'Unidades Bloqueadas'
            empreendimento_style_info = [] 

            for i, nome_emp in enumerate(empreendimentos_no_df_filtrado):
                df_emp_data_original = df_filtrado[df_filtrado[col_empreendimento_input] == nome_emp].copy()
                if df_emp_data_original.empty: continue

                df_output_emp = pd.DataFrame()
                # ... (lógica para montar df_output_emp como antes) ...
                for col_in, col_out_name in colunas_saida_map.items():
                    if col_in and col_in in df_emp_data_original.columns:
                        df_output_emp[col_out_name] = df_emp_data_original[col_in]
                    elif col_out_name in nomes_colunas_saida_ordenadas:
                        df_output_emp[col_out_name] = pd.Series([""] * len(df_emp_data_original), index=df_emp_data_original.index)
                if not df_output_emp.empty:
                    df_output_emp = df_output_emp[nomes_colunas_saida_ordenadas]
                else: 
                    df_output_emp = pd.DataFrame(columns=nomes_colunas_saida_ordenadas)

                if i > 0: current_row_excel_pandas += 1 
                
                empreendimento_title_row_pyxl = current_row_excel_pandas + 1
                current_row_excel_pandas += 1 
                start_row_data_table_pandas = current_row_excel_pandas 
                
                # Escreve os dados SEM o cabeçalho do Pandas, pois a Tabela Excel terá seu próprio.
                df_output_emp.to_excel(writer, sheet_name=sheet_name_output, 
                                       startrow=start_row_data_table_pandas + 1, # Dados começam 1 linha abaixo do cabeçalho da tabela
                                       index=False, header=False) # HEADER = FALSE
                
                # Escrever os nomes das colunas manualmente para a Tabela Excel
                # Esta será a linha do cabeçalho da Tabela Excel
                temp_header_df = pd.DataFrame([nomes_colunas_saida_ordenadas])
                temp_header_df.to_excel(writer, sheet_name=sheet_name_output,
                                        startrow=start_row_data_table_pandas,
                                        index=False, header=False)

                empreendimento_style_info.append({
                    'nome': nome_emp,
                    'title_row_pyxl': empreendimento_title_row_pyxl,
                    'table_header_row_pyxl': start_row_data_table_pandas + 1, # Cabeçalho da Tabela
                    'table_data_start_row_pyxl': start_row_data_table_pandas + 2, # Dados da Tabela
                    'num_data_rows': len(df_output_emp),
                    'table_name': f"Tabela_{re.sub(r'[^A-Za-z0-9_]', '', nome_emp.replace(' ', '_'))}_{i}" # Nome único para a tabela
                })
                
                current_row_excel_pandas += (1 + len(df_output_emp)) # 1 para o header da tabela + dados
                current_row_excel_pandas += 1 # Linha em branco ABAIXO da tabela

            # --- APLICAÇÃO DE ESTILOS E CRIAÇÃO DE TABELAS ---
            workbook = writer.book
            worksheet = workbook[sheet_name_output]

            # ... (Definição dos seus estilos: font_white_bold, etc. - SEM MUDANÇAS) ...
            font_white_bold = Font(name='Calibri', size=11, bold=True, color="FFFFFF")
            # font_black_bold = Font(name='Calibri', size=11, bold=True, color="000000") # Não mais necessário se a tabela estilizar
            # font_black_normal = Font(name='Calibri', size=11, bold=False, color="000000") # Não mais necessário
            fill_blue_dark = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
            # fill_grey_light = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid") # Não mais necessário
            center_alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            left_alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
            # thin_border_side = Side(border_style="thin", color="000000") # Não mais necessário se a tabela estilizar
            # table_border = Border(left=thin_border_side, right=thin_border_side, 
            #                       top=thin_border_side, bottom=thin_border_side) # Não mais necessário
            
            num_cols_tabela = len(nomes_colunas_saida_ordenadas)

            for info in empreendimento_style_info:
                if num_cols_tabela == 0: # Pula se não há colunas para a tabela
                    # Apenas estiliza o título se existir
                    worksheet.merge_cells(start_row=info['title_row_pyxl'], start_column=1, 
                                          end_row=info['title_row_pyxl'], end_column=max(1, num_cols_tabela if num_cols_tabela > 0 else 1))
                    title_cell = worksheet.cell(row=info['title_row_pyxl'], column=1)
                    title_cell.value = info['nome'].upper()
                    title_cell.font = font_white_bold
                    title_cell.fill = fill_blue_dark
                    title_cell.alignment = center_alignment
                    worksheet.row_dimensions[info['title_row_pyxl']].height = 20
                    continue

                # Estilizar Título do Empreendimento (como antes)
                worksheet.merge_cells(start_row=info['title_row_pyxl'], start_column=1, 
                                      end_row=info['title_row_pyxl'], end_column=num_cols_tabela)
                title_cell = worksheet.cell(row=info['title_row_pyxl'], column=1)
                title_cell.value = info['nome'].upper()
                title_cell.font = font_white_bold
                title_cell.fill = fill_blue_dark
                title_cell.alignment = center_alignment
                worksheet.row_dimensions[info['title_row_pyxl']].height = 20

                # --- CRIAÇÃO DA TABELA EXCEL ---
                # O range da tabela inclui o cabeçalho e todas as linhas de dados
                table_range_start_col_letter = get_column_letter(1)
                table_range_end_col_letter = get_column_letter(num_cols_tabela)
                table_range_end_row = info['table_header_row_pyxl'] + info['num_data_rows'] # Cabeçalho + dados

                # Certifique-se de que a linha final não seja menor que a linha do cabeçalho
                # (caso não haja dados, a tabela ainda precisa do cabeçalho)
                if table_range_end_row < info['table_header_row_pyxl']:
                    table_range_end_row = info['table_header_row_pyxl']


                table_ref = f"{table_range_start_col_letter}{info['table_header_row_pyxl']}:{table_range_end_col_letter}{table_range_end_row}"
                
                # Não criar tabela se não houver colunas
                if num_cols_tabela > 0:
                    excel_table = Table(displayName=info['table_name'], ref=table_ref)

                    # Adicionar um estilo de tabela (pode escolher entre os predefinidos)
                    # "TableStyleMedium9" é um azul comum, "TableStyleMedium2" é cinza/preto
                    # "TableStyleLight1" ou "TableStyleMedium1" são bons para o visual da sua imagem
                    style = TableStyleInfo(name="TableStyleMedium2", # Tente este para o visual cinza
                                           showFirstColumn=False,
                                           showLastColumn=False,
                                           showRowStripes=True, # Linhas zebradas
                                           showColumnStripes=False)
                    excel_table.tableStyleInfo = style
                    worksheet.add_table(excel_table)
                
                # Opcional: Ajustar alinhamento das células de dados se o estilo da tabela não o fizer
                # A estilização de fonte, preenchimento e bordas agora virá principalmente do estilo da Tabela Excel.
                # Se precisar de ajustes finos no alinhamento ou formato numérico, pode aplicar aqui.
                for r_offset in range(info['num_data_rows']):
                    data_row_num_pyxl = info['table_data_start_row_pyxl'] + r_offset
                    for col_num_pyxl in range(1, num_cols_tabela + 1):
                        cell = worksheet.cell(row=data_row_num_pyxl, column=col_num_pyxl)
                        cell.alignment = left_alignment # Garante alinhamento à esquerda para dados
                    worksheet.row_dimensions[data_row_num_pyxl].height = 15

                # O cabeçalho da tabela é estilizado pelo TableStyleInfo.
                # Se quiser forçar um estilo específico no cabeçalho da Tabela (além do estilo da Tabela):
                # for col_num_pyxl in range(1, num_cols_tabela + 1):
                #     cell = worksheet.cell(row=info['table_header_row_pyxl'], column=col_num_pyxl)
                #     cell.font = font_black_bold # Exemplo
                #     cell.alignment = center_alignment


            # Ajuste de largura das colunas (como antes)
            for col_idx_1based, col_name_output in enumerate(nomes_colunas_saida_ordenadas, 1):
                # ... (lógica de ajuste de largura como antes) ...
                column_letter = get_column_letter(col_idx_1based)
                max_length = 0
                if len(str(col_name_output)) > max_length: max_length = len(str(col_name_output))
                for row_idx_1based in range(1, worksheet.max_row + 1):
                    cell_value = worksheet.cell(row=row_idx_1based, column=col_idx_1based).value
                    if cell_value:
                        cell_len = len(str(cell_value))
                        if cell_len > max_length: max_length = cell_len
                adjusted_width = (max_length + 2) * 1.2 
                if adjusted_width > 70 : adjusted_width = 70 
                if adjusted_width < 10 : adjusted_width = 10 
                worksheet.column_dimensions[column_letter].width = adjusted_width


        output_excel_stream.seek(0)
        print("(Unidades Bloqueadas - Processamento CSV com Tabelas Excel) Concluído.")
        return output_excel_stream

    # ... (try-except como antes) ...
    except ValueError as ve: 
        print(f"(Unidades Bloqueadas - Processamento CSV com Estilização) ERRO VALIDAÇÃO: {ve}")
        traceback.print_exc(); raise ve 
    except Exception as e:
        print(f"(Unidades Bloqueadas - Processamento CSV com Estilização) ERRO INESPERADO: {e}")
        traceback.print_exc(); raise RuntimeError(f"Erro inesperado na estilização Excel: {e}") from e