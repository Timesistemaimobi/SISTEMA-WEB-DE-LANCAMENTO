# formatadores/tabela_desformatador.py

import pandas as pd
import io
import traceback
import re
import unicodedata
import csv # Importa o módulo csv (boa prática, embora não usado diretamente aqui)

# --- Funções Auxiliares ---

def normalize_text_simple(text):
    """Normaliza texto removendo acentos, espaços e convertendo para minúsculas."""
    if pd.isna(text): return ""
    try:
        text = str(text).strip().lower()
        text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
        return text
    except:
        return str(text).strip().lower()

def format_brl(value):
    """
    Converte valor numérico ou string para formato moeda BRL (R$ #.###,##),
    arredondando para 2 casas decimais e tratando separadores.
    """
    if pd.isna(value) or str(value).strip() == '' or str(value).strip() == '--':
        return ''

    s_val = str(value).strip()
    
    # Se já tem "R$", assume que pode estar formatado, mas limpa para reformatar com segurança
    s_val = s_val.replace('R$', '').strip()

    # Verifica se contém letras inesperadas após a limpeza inicial
    if re.search(r'[a-zA-Z]', s_val):
        if normalize_text_simple(s_val) == 'valor': return ''
        return str(value).strip() # Retorna o texto original se não for formatável

    # Encontra o último ponto e a última vírgula para decidir qual é o decimal
    last_dot = s_val.rfind('.')
    last_comma = s_val.rfind(',')

    # Assume que o último separador é o decimal e limpa a string para conversão
    if last_comma > last_dot:
        # Formato brasileiro (ex: 1.654,890047)
        # Remove todos os pontos (milhar) e troca a vírgula por ponto para float
        s_val_num = s_val.replace('.', '').replace(',', '.')
    elif last_dot > last_comma:
        # Formato americano (ex: 1,654.890047)
        # Remove todas as vírgulas (milhar)
        s_val_num = s_val.replace(',', '')
    else: # Sem um dos dois separadores
        s_val_num = s_val.replace(',', '.') # Garante que vírgula (se houver) vire ponto

    try:
        num = float(s_val_num)
        
        # --- ARREDONDAMENTO PARA 2 CASAS DECIMAIS ---
        num_rounded = round(num, 2)

        # --- Formatação Manual Explícita com o número arredondado ---
        valor_com_decimal = f"{num_rounded:.2f}".replace('.', ',')
        partes = valor_com_decimal.split(',')
        parte_inteira = partes[0]
        sinal = ""
        if parte_inteira.startswith('-'):
            sinal = "-"
            parte_inteira = parte_inteira[1:]

        parte_decimal = partes[1]
        parte_inteira_com_milhar = ""
        n_digitos = len(parte_inteira)
        for i, digito in enumerate(parte_inteira):
            parte_inteira_com_milhar += digito
            if (n_digitos - 1 - i) > 0 and (n_digitos - 1 - i) % 3 == 0:
                parte_inteira_com_milhar += "."
        return f"R$ {sinal}{parte_inteira_com_milhar},{parte_decimal}"
    except (ValueError, TypeError):
        return str(value).strip() # Retorna original se falhar

def extract_number_from_string(text):
    """Extrai o primeiro número de uma string e retorna como int, ou None se não encontrar."""
    if pd.isna(text): return None
    match = re.search(r'\d+', str(text))
    if match:
        try: return int(match.group(0))
        except ValueError: return None
    return None

# --- Função Principal do Desformatador (MODIFICADA PARA FORMATAR MOEDA) ---
def desformatar_tabela_precos(input_file_object):
    """
    Lê uma planilha Excel formatada e extrai os dados, reformatando
    os valores de moeda (incluindo entrada e desconto) para o padrão BRL.
    """
    print(f"(Desformatador - v2) Iniciando processamento.")
    try:
        df_raw = pd.read_excel(input_file_object, engine='openpyxl', header=None, dtype=str).fillna('')
        if df_raw.empty: raise ValueError("Arquivo Excel está vazio.")
        print(f"(Desformatador) Lidas {len(df_raw)} linhas brutas.")

        processed_data = []
        etapa_atual = None
        bloco_atual = None
        cabecalho_dados = None

        print("Iniciando varredura das linhas...")
        for index, row in df_raw.iterrows():
            primeira_celula = str(row.iloc[0]).strip()
            primeira_celula_norm = normalize_text_simple(primeira_celula)

            # Identificar Tipo de Linha
            if primeira_celula_norm.startswith('etapa'):
                etapa_atual = primeira_celula
                print(f"  Linha {index+1}: ETAPA -> '{etapa_atual}'")
                continue
            elif primeira_celula_norm.startswith(('bloco', 'quadra')):
                bloco_atual = primeira_celula
                cabecalho_dados = None # Reseta o cabeçalho para o novo bloco
                print(f"  Linha {index+1}: BLOCO/QUADRA -> '{bloco_atual}'")
                continue
            elif primeira_celula_norm.startswith('unidade'):
                cabecalho_dados = [str(h).strip() for h in row if str(h).strip()]
                print(f"  Linha {index+1}: CABEÇALHO -> {cabecalho_dados}")
                continue

            # Processar Linha de Dados Reais
            if cabecalho_dados and primeira_celula:
                linha_dict = {'ETAPA': etapa_atual, 'BLOCO': bloco_atual}
                for i, nome_coluna in enumerate(cabecalho_dados):
                    if i < len(row):
                        valor_celula = row.iloc[i]
                        nome_coluna_norm = normalize_text_simple(nome_coluna)
                        
                        # Aplica formatação BRL se for coluna de valor, incluindo desconto
                        if 'valor' in nome_coluna_norm or 'sinal' in nome_coluna_norm or 'mensal' in nome_coluna_norm or 'entrada' in nome_coluna_norm or 'desconto' in nome_coluna_norm:
                            linha_dict[nome_coluna] = format_brl(valor_celula)
                        else:
                            linha_dict[nome_coluna] = valor_celula
                    else:
                        linha_dict[nome_coluna] = ''
                processed_data.append(linha_dict)

        print(f"Varredura concluída. {len(processed_data)} linhas de dados extraídas.")
        if not processed_data:
            raise ValueError("Nenhum dado de unidade foi extraído. Verifique o formato do arquivo.")

        df_final = pd.DataFrame(processed_data)
        # Limpa colunas que podem ter sido criadas mas ficaram totalmente vazias
        df_final.dropna(axis=1, how='all', inplace=True)
        print("DataFrame final criado com sucesso.")
        return df_final

    except ValueError as ve:
        print(f"(Desformatador) ERRO VALIDAÇÃO: {ve}")
        raise ve
    except Exception as e:
        print(f"(Desformatador) ERRO INESPERADO: {e}")
        traceback.print_exc()
        raise RuntimeError(f"Erro inesperado no desformatador: {e}") from e