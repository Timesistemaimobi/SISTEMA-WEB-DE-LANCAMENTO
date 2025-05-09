# formatadores/incorporacao_formatador.py

import pandas as pd
import io
import re
import traceback
import openpyxl
import unicodedata
import numpy as np
from openpyxl.utils import get_column_letter # Para largura

def normalize_text_for_match(text):
    """Normaliza texto para busca: minúsculo, sem acentos, sem não-alfanuméricos."""
    if not isinstance(text, str): text = str(text)
    try: text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII'); text = text.lower(); text = re.sub(r'[^a-z0-9]', '', text); return text.strip()
    except Exception: return str(text).lower().strip().replace(' ', '')

def find_column_flexible(df_columns, concept_keywords, concept_name, required=True):
    """Encontra coluna de forma flexível."""
    normalized_input_cols = {normalize_text_for_match(col): col for col in df_columns}; print(f"  Buscando '{concept_name}': Keywords={concept_keywords}. Colunas Norm.: {list(normalized_input_cols.keys())}"); found_col_name = None
    for keyword in concept_keywords: # Match exato
        norm_keyword = normalize_text_for_match(keyword)
        if norm_keyword in normalized_input_cols: found_col_name = normalized_input_cols[norm_keyword]; print(f"    -> Match exato norm. '{norm_keyword}' para '{concept_name}'. Col original: '{found_col_name}'"); return found_col_name
    potential_matches = []
    for keyword in concept_keywords: # Match parcial
        norm_keyword = normalize_text_for_match(keyword);
        if not norm_keyword: continue
        for norm_col, orig_col in normalized_input_cols.items():
            if not norm_col: continue
            if norm_keyword in norm_col: priority = 0 if norm_col.startswith(norm_keyword) else 1; potential_matches.append((priority, orig_col))
    if potential_matches: potential_matches.sort(); found_col_name = potential_matches[0][1]; print(f"    -> Melhor match parcial para '{concept_name}'. Col original: '{found_col_name}'"); return found_col_name
    if required: raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada. Keywords: {concept_keywords}. Colunas: {list(df_columns)}")
    else: print(f"    -> Coluna opcional '{concept_name}' não encontrada."); return None

def format_decimal_br(value, precision):
    # ... (código da versão anterior com formatação manual) ...
    if pd.isna(value) or str(value).strip() == '': return ""
    s_val = str(value).strip(); s_val = re.sub(r'[^\d,.-]', '', s_val)
    if ',' in s_val and '.' in s_val: s_val = s_val.replace('.', '').replace(',', '.')
    elif ',' in s_val: s_val = s_val.replace(',', '.')
    try:
        num = float(s_val); format_string = f"{{:.{precision}f}}"; formatted = format_string.format(num).replace('.', ',')
        # Adiciona separador de milhar se necessário (apenas para exibição, pois o valor é string)
        parts = formatted.split(',')
        int_part = parts[0]; dec_part = parts[1] if len(parts) > 1 else ''
        int_part_fmt = ""
        n_dig = len(int_part)
        for i, d in enumerate(int_part):
            int_part_fmt += d
            if (n_dig - 1 - i) > 0 and (n_dig - 1 - i) % 3 == 0: int_part_fmt += "."
        return f"{int_part_fmt},{dec_part}"
    except (ValueError, TypeError): return str(value)

# --- Função parse_flexible_float (ADICIONE OU GARANTA QUE ESTÁ IMPORTADA) ---
def parse_flexible_float(value):
    """Tenta converter uma string (possivelmente formatada) em um float."""
    if value is None: return None
    s_val = str(value).strip()
    if not s_val: return None
    # Remove R$, espaços não numéricos, etc. Mantém dígitos, ponto, vírgula, sinal
    s_val = re.sub(r'[^\d,.-]+', '', s_val)
    # Tratamento de separadores decimais/milhares
    num_commas = s_val.count(',')
    num_dots = s_val.count('.')

    if num_commas == 1 and num_dots >= 1: # Formato PT: 1.234,56 ou 123.456,78
        # A vírgula é decimal se for o último separador
        if s_val.rfind(',') > s_val.rfind('.'):
            s_val = s_val.replace('.', '').replace(',', '.')
        else: # Formato US: 1,234.56 ou 123,456.78 (ou erro)
             s_val = s_val.replace(',', '')
    elif num_commas >= 2 and num_dots == 1: # Formato US com vírgulas: 1,234,567.89
        s_val = s_val.replace(',', '')
    elif num_dots >= 2 and num_commas == 1: # Formato PT com pontos: 1.234.567,89
        s_val = s_val.replace('.', '').replace(',', '.')
    elif num_commas == 1 and num_dots == 0: # Só vírgula -> decimal
        s_val = s_val.replace(',', '.')
    # Se num_dots == 1 e num_commas == 0 -> decimal já é ponto
    # Se num_dots >= 2 e num_commas == 0 -> erro ou inteiro muito grande (ex: 1.234.567) -> remove pontos
    elif num_dots >= 2 and num_commas == 0:
        s_val = s_val.replace('.', '')
    # Se num_commas >= 2 e num_dots == 0 -> erro ou inteiro com vírgula (ex: 1,234,567) -> remove vírgulas
    elif num_commas >= 2 and num_dots == 0:
        s_val = s_val.replace(',', '')

    # Tentativa final de conversão
    try:
        return float(s_val)
    except (ValueError, TypeError):
        # print(f"Debug parse_flexible_float: Falha ao converter '{value}' -> '{s_val}'") # Debug
        return None

def format_tipo_with_leading_zero(tipo_str):
    """
    Formata a string de TIPO para ter um número com zero à esquerda.
    Ex: "TIPO 1" -> "TIPO 01", "TIPO 10" -> "TIPO 10", "CASA 5" -> "CASA 05".
    Retorna a string original se não encontrar um número no final.
    """
    original_tipo_str = str(tipo_str).strip() # Garante string e remove espaços
    if not original_tipo_str:
        return "" # Retorna vazio se a entrada for vazia

    parts = original_tipo_str.split() # Divide por espaços

    if len(parts) >= 2: # Precisa de pelo menos um prefixo e um número potencial
        prefix = " ".join(parts[:-1]) # Tudo exceto a última parte é o prefixo
        number_part = parts[-1]     # A última parte é o número potencial

        try:
            # Tenta converter a última parte para inteiro
            number_int = int(number_part)
            # Formata o número com duas casas decimais (zero à esquerda)
            formatted_number = f"{number_int:02d}"
            # Remonta a string
            return f"{prefix} {formatted_number}"
        except ValueError:
            # A última parte não era um número inteiro válido
            return original_tipo_str # Retorna o original
    else:
        # Não tem o formato "PREFIXO NUMERO" (ex: "APARTAMENTO", "TIPO", etc.)
        return original_tipo_str # Retorna o original

# Função que REMOVE as linhas de cabeçalho Bloco/Quadra
def processar_incorporacao_web(input_filepath_or_stream):
    """
    Processa planilha de incorporação... Adiciona (PCD) à unidade se aplicável
    verificando TIPO ou CASA/APT.
    """
    print(f"(Formatador Incorporação - v11 PCD Unidade - TIPO ou UNID) Iniciando.")
    output = io.BytesIO()
    try:
        # 1. Leitura Bruta Inicial (MANTENHA)
        # ...
        print(f"Lendo arquivo/stream...")
        df_raw = pd.read_excel(input_filepath_or_stream, header=None, dtype=str).fillna('')
        print(f"Lidas {len(df_raw)} linhas brutas.")
        if df_raw.empty: raise ValueError("Arquivo Excel está vazio.")

        # 2. Detectar a Linha do Cabeçalho Real (MANTENHA)
        # ...
        header_row_index = -1
        possible_headers_data = ['tipo', 'casa', 'apt', 'apto', 'areaconstruida', 'area', 'fracaoideal', 'valor']
        print("Tentando detectar a linha do cabeçalho dos dados...")
        for idx, row in df_raw.head(15).iterrows():
            row_values_norm = [normalize_text_for_match(str(v)) for v in row.values if pd.notna(v)]
            if sum(h in row_values_norm for h in possible_headers_data) >= 3:
                header_row_index = idx
                print(f"Linha do cabeçalho dos dados encontrada no índice: {header_row_index} (Linha Excel: {header_row_index + 1})")
                break
        if header_row_index == -1:
            raise ValueError("Não foi possível encontrar a linha do cabeçalho dos dados.")


        # 3. Identificar os Índices das Colunas Chave (MANTENHA)
        # ...
        header_data_row_values = df_raw.iloc[header_row_index].fillna('').astype(str).str.strip()
        print(f"Valores do cabeçalho detectado: {header_data_row_values.tolist()}")
        concept_mappings = [
            (['tipo'], 'TIPO', True),
            (['casa', 'apt', 'apto', 'apartamento'], 'CASA_APT', True),
            (['areaconstruida', 'área construída'], 'ÁREA CONSTRUIDA', False),
            (['quintal'], 'QUINTAL', False),
            (['garagem', 'garagem e frontal'], 'GARAGEM', False),
            (['areaprivativa', 'área privativa'], 'ÁREA PRIVATIVA', False),
            (['fracaoideal', 'fração ideal'], 'FRAÇÃO IDEAL', False),
            (['quadra', 'bloco', 'qd', 'blk'], 'BLOCO_QUADRA', False)
        ]
        col_indices = {}
        print("--- Identificando índices das colunas chave no cabeçalho ---")
        for keywords, concept_name, required in concept_mappings:
            found_idx = None
            for real_idx, header_val_str in header_data_row_values.items():
                if pd.notna(header_val_str) and normalize_text_for_match(header_val_str) in [normalize_text_for_match(k) for k in keywords]:
                    found_idx = real_idx
                    print(f"  -> Coluna '{concept_name}' encontrada no índice: {found_idx} (Header: '{header_val_str}')")
                    break
            if found_idx is None and required:
                 raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada no cabeçalho detectado ({header_row_index+1}). Keywords: {keywords}")
            col_indices[concept_name] = found_idx
        print("--- Índices das colunas chave: ---", col_indices)
        print("-----------------------------------")


        # 4. Iterar pelas linhas ABAIXO do cabeçalho e Extrair Dados (MODIFICAÇÕES AQUI)
        processed_data = []
        ultimo_bloco_num_str = None
        header_saida_bloco_quadra = "BLOCO"
        final_header_casa_apt = "UNIDADE" # Alterado fallback para UNIDADE

        print(f"Iterando pelas linhas de dados a partir do índice {header_row_index + 1}...")
        for idx in range(header_row_index + 1, len(df_raw)):
            row = df_raw.iloc[idx].fillna('')

            # 4.1. Tratar linhas de título (MANTENHA)
            # ...
            cell_val_a = str(row.iloc[0]).strip()
            is_quadra_title_line = cell_val_a.lower().startswith("quadra")
            is_bloco_title_line = cell_val_a.lower().startswith("bloco")

            if is_quadra_title_line or is_bloco_title_line:
                if is_quadra_title_line: header_saida_bloco_quadra = "QUADRA"
                else: header_saida_bloco_quadra = "BLOCO"
                match = re.search(r'\d+', cell_val_a)
                if match:
                    try: ultimo_bloco_num_str = f"{int(match.group(0)):02d}"
                    except (ValueError, TypeError, IndexError): ultimo_bloco_num_str = "??"
                else: ultimo_bloco_num_str = "??"
                print(f"  Linha {idx}: Título de Seção '{cell_val_a}'. Número = {ultimo_bloco_num_str}. Nome Col Saída = {header_saida_bloco_quadra}")
                continue

            # 4.2. Verificar se é linha de dados válida (MANTENHA)
            # ...
            casa_apt_idx = col_indices.get('CASA_APT')
            if casa_apt_idx is None or len(row) <= casa_apt_idx or str(row.iloc[casa_apt_idx]).strip() == '':
                 continue

            # 4.3. Tratar bloco/quadra da linha de dados (MANTENHA)
            # ...
            bloco_quadra_idx = col_indices.get('BLOCO_QUADRA')
            if bloco_quadra_idx is not None and len(row) > bloco_quadra_idx and str(row.iloc[bloco_quadra_idx]).strip():
                 bloco_val_raw = str(row.iloc[bloco_quadra_idx]).strip()
                 match = re.search(r'\d+', bloco_val_raw)
                 bloco_num_str_atual = f"{int(match.group(0)):02d}" if match else "??"
                 ultimo_bloco_num_str = bloco_num_str_atual

            if ultimo_bloco_num_str is None:
                 continue

            # --- Extração dos valores ---
            # Pega o valor ORIGINAL da coluna TIPO para verificação PCD
            tipo_val_original = str(row.iloc[col_indices['TIPO']]) if col_indices.get('TIPO') is not None and len(row) > col_indices['TIPO'] else ''
            # Pega o valor ORIGINAL da coluna CASA/APT para verificação PCD e para formatação do número
            casa_apt_val_original = str(row.iloc[casa_apt_idx]).strip()

            # Formata o TIPO para a coluna de saída TIPO (ex: TIPO 01)
            formatted_tipo_output_val = format_tipo_with_leading_zero(tipo_val_original)

            # --- MODIFICAÇÃO: Determinar se é PCD verificando TIPO OU CASA/APT ---
            is_special_unit = False
            normalized_tipo = normalize_text_for_match(tipo_val_original)
            normalized_unidade = normalize_text_for_match(casa_apt_val_original)

            if 'pcd' in normalized_tipo or 'pne' in normalized_tipo:
                is_special_unit = True
            elif 'pcd' in normalized_unidade or 'pne' in normalized_unidade:
                is_special_unit = True
            # --- FIM DA MODIFICAÇÃO PCD ---

            # Formata o número da unidade (CASA/APT)
            # Extrai apenas os dígitos do valor original da unidade para formatação do número
            unit_number_digits = ''.join(filter(str.isdigit, casa_apt_val_original))
            if unit_number_digits:
                try:
                    formatted_unit_number_part = f"{int(unit_number_digits):02d}"
                except ValueError:
                    formatted_unit_number_part = casa_apt_val_original # Fallback
            else:
                formatted_unit_number_part = casa_apt_val_original # Se não houver dígitos, usa o valor original

            # Adiciona (PCD) ao número formatado da unidade se aplicável
            if is_special_unit:
                formatted_unit_number_with_pcd = f"{formatted_unit_number_part} (PCD)"
            else:
                formatted_unit_number_with_pcd = formatted_unit_number_part

            # Outras colunas
            area_const_val = row.iloc[col_indices['ÁREA CONSTRUIDA']] if col_indices.get('ÁREA CONSTRUIDA') is not None and len(row) > col_indices['ÁREA CONSTRUIDA'] else ''
            quintal_val = row.iloc[col_indices['QUINTAL']] if col_indices.get('QUINTAL') is not None and len(row) > col_indices['QUINTAL'] else ''
            garagem_val = row.iloc[col_indices['GARAGEM']] if col_indices.get('GARAGEM') is not None and len(row) > col_indices['GARAGEM'] else ''
            area_priv_val = row.iloc[col_indices['ÁREA PRIVATIVA']] if col_indices.get('ÁREA PRIVATIVA') is not None and len(row) > col_indices['ÁREA PRIVATIVA'] else ''
            fracao_val = row.iloc[col_indices['FRAÇÃO IDEAL']] if col_indices.get('FRAÇÃO IDEAL') is not None and len(row) > col_indices['FRAÇÃO IDEAL'] else ''


            # Determina nome do cabeçalho CASA/APT para a coluna de saída
            header_casa_apt_orig_val_from_header = header_data_row_values.iloc[casa_apt_idx] if casa_apt_idx is not None else ''
            if 'casa' in normalize_text_for_match(str(header_casa_apt_orig_val_from_header)):
                final_header_casa_apt = "CASA"
            elif 'apt' in normalize_text_for_match(str(header_casa_apt_orig_val_from_header)) or \
                 'apartamento' in normalize_text_for_match(str(header_casa_apt_orig_val_from_header)):
                final_header_casa_apt = "APT"
            else:
                final_header_casa_apt = "UNIDADE" # Fallback se não for explicitamente casa ou apt

            # --- Adiciona dados à lista ---
            processed_data.append({
                header_saida_bloco_quadra: ultimo_bloco_num_str,
                'TIPO': formatted_tipo_output_val, # TIPO formatado (ex: TIPO 01) para a coluna TIPO
                final_header_casa_apt: formatted_unit_number_with_pcd, # Valor da unidade com (PCD) se aplicável
                'ÁREA CONSTRUIDA': area_const_val,
                'QUINTAL': quintal_val,
                'GARAGEM': garagem_val,
                'ÁREA PRIVATIVA': area_priv_val,
                'FRAÇÃO IDEAL': fracao_val,
                'ETAPA': '01',
            })

        print(f"Iteração concluída. {len(processed_data)} linhas de dados extraídas.")
        if not processed_data: raise ValueError("Nenhum dado válido extraído.")

        # 5. Criar DataFrame Final (MANTENHA)
        df_final = pd.DataFrame(processed_data)

        # 6. Aplicar Formatação Numérica para exibição string (MANTENHA)
        #    (Se precisar de números reais no Excel, o pós-processamento openpyxl é crucial)
        print("--- Formatando Colunas Numéricas (para exibição no CSV/string) ---")
        cols_to_format_final = {}
        if 'ÁREA CONSTRUIDA' in df_final.columns: cols_to_format_final['ÁREA CONSTRUIDA'] = 2
        if 'QUINTAL' in df_final.columns: cols_to_format_final['QUINTAL'] = 2
        if 'GARAGEM' in df_final.columns: cols_to_format_final['GARAGEM'] = 2
        if 'ÁREA PRIVATIVA' in df_final.columns: cols_to_format_final['ÁREA PRIVATIVA'] = 2
        if 'FRAÇÃO IDEAL' in df_final.columns: cols_to_format_final['FRAÇÃO IDEAL'] = 9
        if 'VALOR' in df_final.columns: cols_to_format_final['VALOR'] = 2

        for col_name, precision in cols_to_format_final.items():
            if col_name in df_final.columns:
                print(f"Formatando coluna '{col_name}' com precisão {precision}...")
                # Garante que está aplicando a formatação correta
                df_final[col_name] = df_final[col_name].apply(lambda x: format_decimal_br(x, precision))
            else: print(f"Aviso: Coluna '{col_name}' para formatar não encontrada.")


        # 7. Definir Ordem Final das Colunas (MANTENHA)
        # ...
        ordem_saida = [
            header_saida_bloco_quadra, 'TIPO', final_header_casa_apt,
            'ÁREA CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'ÁREA PRIVATIVA', 'FRAÇÃO IDEAL',
            'ETAPA'
        ]
        colunas_finais_real = []
        for col in ordem_saida:
            if col in df_final.columns and col not in colunas_finais_real:
                colunas_finais_real.append(col)
        # Adiciona colunas não previstas na ordem ao final (segurança)
        for col in df_final.columns:
            if col not in colunas_finais_real:
                print(f"Aviso: Coluna '{col}' não prevista na ordem de saída, adicionando ao final.")
                colunas_finais_real.append(col)
        df_final = df_final[colunas_finais_real]
        print(f"Ordem final das colunas: {df_final.columns.tolist()}")


        # 8. Gerar o Arquivo Excel e APLICAR PÓS-PROCESSAMENTO com openpyxl (MANTENHA)
        #    (Este bloco é crucial para ter números reais no Excel e aplicar formatos visuais)
        print("Gerando arquivo Excel e aplicando conversão/formatação numérica...")
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_final.to_excel(writer, index=False, header=True, sheet_name='Incorporacao Formatada')
            workbook = writer.book
            worksheet = writer.sheets['Incorporacao Formatada']
            print("Iniciando pós-processamento das células...")
            tipo_col_name_final = None
            casa_apt_col_name_final = final_header_casa_apt # Pega o nome da coluna da unidade da lógica anterior

            for col in df_final.columns:
                if normalize_text_for_match(col) == 'tipo':
                    tipo_col_name_final = col
                    print(f"Coluna 'TIPO' final identificada como: '{tipo_col_name_final}'")
                    break # Só precisa encontrar uma vez

            col_excel_formats = {
                'ÁREA CONSTRUIDA': '0.00', 'QUINTAL': '0.00', 'GARAGEM': '0.00',
                'ÁREA PRIVATIVA': '0.00', 'FRAÇÃO IDEAL': '0.000000000',
                'VALOR': '#,##0.00' # Formato para VALOR
            }

            for row_idx in range(2, worksheet.max_row + 1):
                for col_idx_1based in range(1, worksheet.max_column + 1):
                    cell = worksheet.cell(row=row_idx, column=col_idx_1based)
                    current_col_name = df_final.columns[col_idx_1based - 1]

                    # Pula colunas que devem ser texto por padrão (TIPO, e a coluna da UNIDADE)
                    if (tipo_col_name_final and current_col_name == tipo_col_name_final) or \
                       (casa_apt_col_name_final and current_col_name == casa_apt_col_name_final):
                        if isinstance(cell.value, str) and cell.value.startswith(('=', '+', '-', '@')):
                             cell.value = "'" + cell.value
                             cell.number_format = '@'
                        continue

                    original_value = cell.value
                    numeric_value = None
                    if original_value is not None and str(original_value).strip() != '':
                        numeric_value = parse_flexible_float(original_value)

                    if numeric_value is not None:
                        cell.value = numeric_value
                        if current_col_name in col_excel_formats:
                            cell.number_format = col_excel_formats[current_col_name]
                    else:
                        if isinstance(original_value, str):
                            original_value_str = original_value.strip()
                            if original_value_str.startswith(('=', '+', '-', '@')):
                                cell.value = "'" + original_value_str
                                cell.number_format = '@'
                        elif original_value is None or str(original_value).strip() == '':
                             cell.value = None

            print("Ajustando largura das colunas...")
            # ... (código de ajuste de largura - MANTENHA) ...
            for i, column_name in enumerate(df_final.columns):
                column_letter = get_column_letter(i + 1)
                try:
                    max_len_data = 0
                    if column_name in df_final and not df_final[column_name].empty:
                         max_len_data = df_final[column_name].astype(str).map(len).max()
                    max_len_header = len(str(column_name))
                    width = max(max_len_data, max_len_header) + 3
                    worksheet.column_dimensions[column_letter].width = min(width, 60)
                except Exception as e_width:
                     print(f"  Aviso: Falha ao ajustar largura da coluna {column_letter} ('{column_name}'): {e_width}")
                     worksheet.column_dimensions[column_letter].width = 15


        output.seek(0)
        print("(Formatador Incorporação - v11 PCD) Arquivo Excel processado gerado.")
        return output

    except ValueError as ve: print(f"(Formatador Incorporação - v11 PCD) ERRO VALIDAÇÃO: {ve}"); traceback.print_exc(); raise ve
    except Exception as e: print(f"(Formatador Incorporação - v11 PCD) ERRO INESPERADO: {e}"); traceback.print_exc(); raise RuntimeError(f"Erro inesperado: {e}") from e
