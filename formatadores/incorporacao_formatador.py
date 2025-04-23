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

# Função que REMOVE as linhas de cabeçalho Bloco/Quadra
def processar_incorporacao_web(input_filepath_or_stream):
    """
    Processa planilha de incorporação, detectando a linha do cabeçalho,
    extrai dados com base nela, remove linhas de título, formata números,
    e retorna BytesIO do Excel formatado.
    """
    print(f"(Formatador Incorporação - v6 Detecção Header) Iniciando.")
    output = io.BytesIO()
    try:
        # 1. Leitura Bruta Inicial
        print(f"Lendo arquivo/stream...")
        df_raw = pd.read_excel(input_filepath_or_stream, header=None, dtype=str).fillna('') # Preenche NaN com ''
        print(f"Lidas {len(df_raw)} linhas brutas.")
        if df_raw.empty: raise ValueError("Arquivo Excel está vazio.")

        # 2. Detectar a Linha do Cabeçalho Real
        header_row_index = -1
        # Palavras-chave para identificar o cabeçalho dos DADOS
        possible_headers_data = ['tipo', 'casa', 'apt', 'apto', 'areaconstruida', 'area', 'fracaoideal', 'valor']
        print("Tentando detectar a linha do cabeçalho dos dados...")
        # Procura nas primeiras 15 linhas (pode ajustar conforme necessário)
        for idx, row in df_raw.head(15).iterrows():
            row_values_norm = [normalize_text_for_match(str(v)) for v in row.values if pd.notna(v)]
            # Exige pelo menos 3 matches das keywords esperadas no cabeçalho dos dados
            if sum(h in row_values_norm for h in possible_headers_data) >= 3:
                header_row_index = idx
                print(f"Linha do cabeçalho dos dados encontrada no índice: {header_row_index} (Linha Excel: {header_row_index + 1})")
                break
        if header_row_index == -1:
            raise ValueError("Não foi possível encontrar a linha do cabeçalho dos dados (procurando por TIPO, CASA/APT, ÁREA CONSTRUIDA, FRAÇÃO IDEAL, VALOR, etc. nas primeiras 15 linhas).")

        # 3. Identificar os Índices das Colunas Chave usando a linha do Cabeçalho Detectado
        header_data_row_values = df_raw.iloc[header_row_index].fillna('').astype(str).str.strip()
        print(f"Valores do cabeçalho detectado: {header_data_row_values.tolist()}")

        # Mapeia keywords para os índices reais no cabeçalho detectado
        # Cria uma lista de tuplas (keyword, nome_conceito, required)
        concept_mappings = [
            (['tipo'], 'TIPO', True),
            (['casa', 'apt', 'apto', 'apartamento'], 'CASA_APT', True), # Nome conceitual para Unidade
            (['areaconstruida', 'área construída'], 'ÁREA CONSTRUIDA', False),
            (['quintal'], 'QUINTAL', False),
            (['garagem'], 'GARAGEM', False),
            (['areaprivativa', 'área privativa'], 'ÁREA PRIVATIVA', False),
            (['fracaoideal', 'fração ideal'], 'FRAÇÃO IDEAL', False),
            (['quadra', 'bloco', 'qd', 'blk'], 'BLOCO_QUADRA', False), # Buscar bloco/quadra no cabeçalho dos dados
            (['valor', 'preco'], 'VALOR', False), # Buscar valor no cabeçalho dos dados
        ]

        # Mapeia nome conceitual -> índice real no DF (None se não encontrado)
        col_indices = {}
        print("--- Identificando índices das colunas chave no cabeçalho ---")
        for keywords, concept_name, required in concept_mappings:
            found_idx = None
            # Procura pela keyword normalizada nos valores do cabeçalho detectado
            for real_idx, header_val_str in header_data_row_values.items():
                if pd.notna(header_val_str) and normalize_text_for_match(header_val_str) in [normalize_text_for_match(k) for k in keywords]:
                    found_idx = real_idx
                    print(f"  -> Coluna '{concept_name}' encontrada no índice: {found_idx} (Header: '{header_val_str}')")
                    break # Pega o primeiro match
            if found_idx is None and required:
                 raise ValueError(f"Coluna obrigatória '{concept_name}' não encontrada no cabeçalho detectado ({header_row_index+1}). Keywords: {keywords}")
            col_indices[concept_name] = found_idx # Armazena o índice (ou None)
        print("--- Índices das colunas chave: ---", col_indices)
        print("-----------------------------------")

        # 4. Iterar pelas linhas ABAIXO do cabeçalho e Extrair Dados
        processed_data = [] # Lista para guardar dicionários das linhas de dados
        ultimo_bloco_num_str = None # Para o Formato 1 (se houver linhas antes do header)
        header_saida_bloco_quadra = "BLOCO" # Nome da coluna Bloco/Quadra na SAÍDA

        print(f"Iterando pelas linhas de dados a partir do índice {header_row_index + 1}...")
        for idx in range(header_row_index + 1, len(df_raw)):
            row = df_raw.iloc[idx].fillna('') # Pega a linha e preenche NaN com ''

            # 4.1. Verificar se é uma linha de título de seção (QUADRA/BLOCO)
            # Verificar a primeira célula
            cell_val_a = str(row.iloc[0]).strip()
            is_quadra_title_line = cell_val_a.lower().startswith("quadra")
            is_bloco_title_line = cell_val_a.lower().startswith("bloco")

            if is_quadra_title_line or is_bloco_title_line:
                 # É uma linha de título de seção -> Extrair número e definir prefixo de SAÍDA
                if is_quadra_title_line: header_saida_bloco_quadra = "QUADRA"
                else: header_saida_bloco_quadra = "BLOCO"
                match = re.search(r'\d+', cell_val_a)
                if match: # <<< ADICIONADO if match:
                    try:
                        ultimo_bloco_num_str = f"{int(match.group(0)):02d}" # Usa group(0) ou group(1)? Regex r'\d+' só tem grupo 0
                    except (ValueError, TypeError, IndexError): # Captura mais erros potenciais
                        print(f"  Aviso Linha {idx}: Não pôde converter número de '{cell_val_a}'.")
                        ultimo_bloco_num_str = "??" # Ou None, se preferir
                else: # <<< ADICIONADO else:
                    print(f"  Aviso Linha {idx}: Nenhum dígito encontrado em '{cell_val_a}'.")
                    ultimo_bloco_num_str = "??" # Ou None

                    print(f"  Linha {idx}: Título de Seção '{cell_val_a}'. Número = {ultimo_bloco_num_str}. Nome Col Saída = {header_saida_bloco_quadra}")

                    continue
            # 4.2. Tentar extrair dados pelas colunas chave encontradas (se os índices existem)
            # Verifica se tem um valor na coluna CASA/APT (índice detectado)
            casa_apt_idx = col_indices.get('CASA_APT')
            if casa_apt_idx is None or len(row) <= casa_apt_idx or str(row.iloc[casa_apt_idx]).strip() == '':
                 # Se não tem CASA/APT na coluna esperada, PULA esta linha (não é linha de dados)
                 # print(f"  Linha {idx}: Não tem valor na coluna CASA/APT ({casa_apt_idx}). Ignorando.") # Debug
                 continue

            # Esta linha é de dados válidos (tem CASA/APT)
            # Verifica se a coluna BLOCO_QUADRA foi encontrada no cabeçalho
            bloco_quadra_idx = col_indices.get('BLOCO_QUADRA')
            if bloco_quadra_idx is not None and len(row) > bloco_quadra_idx and str(row.iloc[bloco_quadra_idx]).strip():
                 # Se a coluna QUADRA/BLOCO existe nos dados E tem um valor nesta linha
                 # Usa este valor para o bloco (Formato 2)
                 bloco_val_raw = str(row.iloc[bloco_quadra_idx]).strip()
                 match = re.search(r'\d+', bloco_val_raw)
                 bloco_num_str_atual = f"{int(match.group(0)):02d}" if match else "??"
                 ultimo_bloco_num_str = bloco_num_str_atual # Atualiza o último encontrado
                 # Nome da coluna de saída já foi definido pelo último título de seção encontrado

            # Verifica se temos um bloco associado (seja do título de seção ou da coluna de dados)
            if ultimo_bloco_num_str is None:
                 print(f"  Linha {idx}: Linha de dados encontrada sem Bloco/Quadra associado. Ignorando.")
                 continue # Pula linhas de dados sem bloco

            # Extrai os outros valores usando os índices encontrados
            tipo_val = row.iloc[col_indices['TIPO']] if col_indices.get('TIPO') is not None and len(row) > col_indices['TIPO'] else ''
            # CASA/APT já extraído para verificar a linha, pega o valor final formatado
            casa_apt_val_raw = str(row.iloc[casa_apt_idx]).strip()

            area_const_val = row.iloc[col_indices['ÁREA CONSTRUIDA']] if col_indices.get('ÁREA CONSTRUIDA') is not None and len(row) > col_indices['ÁREA CONSTRUIDA'] else ''
            quintal_val = row.iloc[col_indices['QUINTAL']] if col_indices.get('QUINTAL') is not None and len(row) > col_indices['QUINTAL'] else ''
            garagem_val = row.iloc[col_indices['GARAGEM']] if col_indices.get('GARAGEM') is not None and len(row) > col_indices['GARAGEM'] else ''
            area_priv_val = row.iloc[col_indices['ÁREA PRIVATIVA']] if col_indices.get('ÁREA PRIVATIVA') is not None and len(row) > col_indices['ÁREA PRIVATIVA'] else ''
            fracao_val = row.iloc[col_indices['FRAÇÃO IDEAL']] if col_indices.get('FRAÇÃO IDEAL') is not None and len(row) > col_indices['FRAÇÃO IDEAL'] else ''
            valor_val = row.iloc[col_indices['VALOR']] if col_indices.get('VALOR') is not None and len(row) > col_indices['VALOR'] else ''

            # Determina nome da coluna CASA/APT para o cabeçalho final
            # Pega o nome original do cabeçalho detectado
            header_casa_apt_orig_val = header_data_row_values.iloc[casa_apt_idx] if casa_apt_idx is not None else ''
            if 'casa' in normalize_text_for_match(str(header_casa_apt_orig_val)): final_header_casa_apt = "CASA"
            elif 'apt' in normalize_text_for_match(str(header_casa_apt_orig_val)): final_header_casa_apt = "APT"
            else: final_header_casa_apt = "CASA/APT" # Fallback

            # Adiciona dados à lista de saída
            processed_data.append({
                header_saida_bloco_quadra: ultimo_bloco_num_str, # Número formatado XX do último bloco/quadra válido
                'TIPO': str(tipo_val).strip(),
                final_header_casa_apt: casa_apt_val_raw.replace('.0',''), # Valor da unidade (ex: 1, 2, LT 1)
                'ÁREA CONSTRUIDA': area_const_val,
                'QUINTAL': quintal_val,
                'GARAGEM': garagem_val,
                'ÁREA PRIVATIVA': area_priv_val,
                'FRAÇÃO IDEAL': fracao_val,
                'ETAPA': '01', # ETAPA fixa
                'VALOR': valor_val # Mantém valor como está por enquanto
            })

        print(f"Iteração concluída. {len(processed_data)} linhas de dados extraídas.")
        if not processed_data: raise ValueError("Nenhum dado válido extraído.")

        # 5. Criar DataFrame Final a partir dos dados processados
        df_final = pd.DataFrame(processed_data)

        # 6. Aplicar Formatação Numérica
        print("--- Formatando Colunas Numéricas ---")
        cols_to_format_final = {}
        if 'ÁREA CONSTRUIDA' in df_final.columns: cols_to_format_final['ÁREA CONSTRUIDA'] = 2
        if 'QUINTAL' in df_final.columns: cols_to_format_final['QUINTAL'] = 2
        if 'GARAGEM' in df_final.columns: cols_to_format_final['GARAGEM'] = 2
        if 'ÁREA PRIVATIVA' in df_final.columns: cols_to_format_final['ÁREA PRIVATIVA'] = 2
        if 'FRAÇÃO IDEAL' in df_final.columns: cols_to_format_final['FRAÇÃO IDEAL'] = 9
        if 'VALOR' in df_final.columns: cols_to_format_final['VALOR'] = 2 # Formata Valor também

        for col_name, precision in cols_to_format_final.items():
            if col_name in df_final.columns:
                print(f"Formatando coluna '{col_name}' com precisão {precision}...")
                df_final[col_name] = df_final[col_name].apply(lambda x: format_decimal_br(x, precision))
            else: print(f"Aviso: Coluna '{col_name}' para formatar não encontrada.")


        # 7. Definir Ordem Final das Colunas
        ordem_saida = [
            header_saida_bloco_quadra, 'TIPO', final_header_casa_apt,
            'ÁREA CONSTRUIDA', 'QUINTAL', 'GARAGEM', 'ÁREA PRIVATIVA', 'FRAÇÃO IDEAL',
            'ETAPA' # Adiciona valor e etapa no final
        ]
        # Remove duplicatas e mantém a ordem
        colunas_finais_real = []
        for col in ordem_saida:
            if col in df_final.columns and col not in colunas_finais_real:
                colunas_finais_real.append(col)

        df_final = df_final[colunas_finais_real]
        print(f"Ordem final das colunas: {df_final.columns.tolist()}")

        # 8. Gerar o Arquivo Excel de Saída COM CABEÇALHO
        print("Gerando arquivo Excel final...")
        output = io.BytesIO()
        df_final.to_excel(output, index=False, header=True, engine='openpyxl') # header=True
        output.seek(0)
        print("(Formatador Incorporação - v5) Arquivo Excel processado gerado.")
        return output

    except ValueError as ve: print(f"(Formatador Incorporação - v5) ERRO VALIDAÇÃO: {ve}"); traceback.print_exc(); raise ve
    except Exception as e: print(f"(Formatador Incorporação - v5) ERRO INESPERADO: {e}"); traceback.print_exc(); raise RuntimeError(f"Erro inesperado: {e}") from e
