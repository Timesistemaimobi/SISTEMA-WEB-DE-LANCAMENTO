import pandas as pd
import os
import io # Para trabalhar com CSV/Excel em memória
import unicodedata
import xlwt # Para escrever arquivos .xls
import csv
import openpyxl # Necessário para engine='openpyxl' do pandas
import re # Para limpeza numérica e busca de colunas
import traceback # Para erros detalhados
from flask import (
    Flask, render_template, request, redirect, url_for,
    send_file, flash, session, abort
)
from werkzeug.utils import secure_filename

# --- Constantes ---
TIPOLOGIAS_PADRAO = {
    "51 - 2 quartos sem suíte": "51", "36 - 2 quartos sendo 1 suíte térreo": "36",
    "34 - 3 quartos sendo 1 suíte térreo": "34"
}
TIPOLOGIAS_SUPERIOR = {
    "52 - 2 quartos sem suíte": "52", "35 - 2 quartos sendo 1 suíte superior": "35",
    "33 - 3 quartos sendo 1 suíte superior": "33"
}
TIPOLOGIAS_PCD = {"50 PCD - 2 QUARTOS SENDO UMA SUÍTE - TÉRREO (PCD)": "50"}
ENDERECO_FIXO = {
    "Endereço": "Av. Olívia Flores", "Bairro": "Candeias", "Número": "1265", "Estado": "BA",
    "Cidade": "Vitória da Conquista", "CEP": "45028610", "Região": "Nordeste",
    "Data da Entrega (Empreendimento)": "01/01/2028"
}

# --- Configuração do Flask ---
app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('FLASK_SECRET_KEY', 'chave-padrao-muito-insegura-trocar-!!!!')
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024 # 16MB
ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
if not os.path.exists(app.config['UPLOAD_FOLDER']): os.makedirs(app.config['UPLOAD_FOLDER'])

# --- Funções Auxiliares Globais ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Funções Auxiliares CV ---
def normalize_text(text):
    if not isinstance(text, str): text = str(text)
    text = unicodedata.normalize('NFKD', text).encode('ASCII', 'ignore').decode('ASCII')
    return text.upper().strip()
def normalize_column_name(column_name):
    if not isinstance(column_name, str): column_name = str(column_name)
    normalized = unicodedata.normalize('NFKD', column_name).encode('ASCII', 'ignore').decode('ASCII')
    return normalized.lower().replace(" ", "").strip()
def encontrar_coluna_garagem(df_columns):
    normalized_columns = {normalize_column_name(col): col for col in df_columns}
    for norm_name, orig_name in normalized_columns.items():
        if "garagem" in norm_name: return orig_name
    return None
def formatar_nome_unidade(row):
    pcd = " (PCD)" if any('PCD' in normalize_text(str(row.get(c,''))) for c in ['APT','CASA','TIPO']) else ""
    qd, ca, bl, ap = row.get('QUADRA'), row.get('CASA'), row.get('BLOCO'), row.get('APT')
    if pd.notna(qd) and pd.notna(ca):
        try: return f"QD{int(qd):02d} - CASA {int(''.join(filter(str.isdigit, str(ca)))):02d}{pcd}"
        except: return f"QD{int(qd):02d} - CASA {str(ca).strip()}{pcd}"
    elif pd.notna(bl) and pd.notna(ap):
        try: return f"BL{int(bl):02d} - APT {int(''.join(filter(str.isdigit, str(ap)))):02d}{pcd}"
        except: return f"BL{int(bl):02d} - APT {str(ap).strip()}{pcd}"
    return ""
def verificar_vaga(g, num_mode):
    if pd.isna(g): return "01 VAGA"
    if num_mode:
        s = str(g).strip(); n=0
        if s:
            for sep in [" e ",","]:
                if sep in s: n=len([v for v in s.split(sep) if v.strip()]); break
            else: n=1
        if n>=4: return "04 VAGAS";
        elif n==3: return "03 VAGAS"
        elif n==2: return "02 VAGAS";
        else: return "01 VAGA"
    else:
        try:
            gn=float(str(g).replace(',','.').strip())
            if abs(gn-int(gn))>0.001: # Metragem
                if gn>35: return"04 VAGAS";
                elif gn>25: return"03 VAGAS"
                elif gn>15: return"02 VAGAS";
                else: return"01 VAGA"
            else: # Int
                gi=int(gn)
                if gi>=4: return"04 VAGAS";
                elif gi==3: return"03 VAGAS"
                elif gi==2: return"02 VAGAS";
                else: return"01 VAGA"
        except: return verificar_vaga(g, True)
def formatar_jardim(v):
    if pd.isna(v): return ""
    try: vf=float(str(v).replace(',','.')); return f"{vf:.2f}".replace('.',',')+" m²" if vf!=0 else ""
    except: return ""
def mapear_tipologia_web(row, tip_map, is_casa):
    t_orig=str(row.get('TIPO','')).strip(); map_i=tip_map.get(t_orig,{}); unit=str(row.get('APT','')or row.get('CASA','')).strip().upper()
    if not t_orig or not map_i: return None
    is_pcd='PCD' in unit or 'PCD' in normalize_text(t_orig)
    if is_pcd: return map_i.get('pcd')
    if is_casa: return map_i.get('padrao')
    try: apt_n=int(''.join(filter(str.isdigit, unit))); return map_i.get('padrao') if apt_n<=6 else map_i.get('superior')
    except: return map_i.get('padrao')

# --- Funções Auxiliares CV Lote ---
def normalize_text_lote(t):
    if pd.isna(t): return ""
    t = str(t); t = unicodedata.normalize('NFKD', t).encode('ASCII','ignore').decode('ASCII')
    return t.upper().strip()
def normalize_column_name_lote(c):
    if pd.isna(c): return ""
    norm = unicodedata.normalize('NFKD', str(c)).encode('ASCII','ignore').decode('ASCII')
    return norm.lower().replace(" ","").strip()
def encontrar_coluna_similar_lote(cols, target):
    t=target.lower().strip(); norm_c={normalize_column_name_lote(col):col for col in cols}
    for n, o in norm_c.items():
        if t in n: print(f"(Lote) Found '{t}': '{o}'"); return o
    print(f"(Lote) Warn: Col '{t}' not found."); return None
def limpar_converter_numerico_lote(v):
    if pd.isna(v): return 0.0
    try:
        s=str(v); s=re.sub(r'M2|M²','',s,flags=re.IGNORECASE).strip(); sep='.'
        if s.rfind(',')>s.rfind('.'): sep=','
        elif s.rfind('.')==-1 and s.rfind(',')!=-1: sep=','
        s = s.replace('.','') if sep==',' else s.replace(',','')
        s=s.replace(sep,'.'); s=''.join(s.split())
        return float(s) if re.fullmatch(r'-?\d+(\.\d+)?',s) else 0.0
    except: return 0.0
def formatar_nome_bloco_lote(row, col_q):
    try:
        if col_q in row.index and pd.notna(row[col_q]):
            try: n=int(row[col_q])
            except ValueError: n=int(float(row[col_q]))
            return f"QUADRA {n:02d}"
        else: return "QUADRA_NA"
    except: return "QUADRA_ERR"
def formatar_nome_unidade_lote(row, col_q, col_l):
    qd_s, lt_s = "QD??", "LOTE ??"
    try:
        if col_q in row.index and pd.notna(row[col_q]):
            try: qd_s=f"QD{int(float(row[col_q])):02d}"
            except: qd_s="QD_INV"
        else: qd_s="QD_NA"
        if col_l in row.index and pd.notna(row[col_l]):
            lv=str(row[col_l]).strip(); ln=''.join(filter(str.isdigit, lv))
            if ln:
                try: lt_s=f"LOTE {int(ln):02d}"
                except: lt_s="LOTE_INV"
            else: lt_s=f"LOTE_{lv}" if lv else "LOTE_S/N"
        else: lt_s="LOTE_NA"
        return f"{qd_s} - {lt_s}"
    except: return "ERRO_NOME_UNIDADE"
def formatar_fracao_ideal_lote(v_num):
    try: return "" if pd.isna(v_num) else str(float(v_num)).replace('.',',')
    except: return "ERRO_FRAC"
def formatar_area_privativa_lote(v_num):
    try: return "" if pd.isna(v_num) else f"{float(v_num):.2f}".replace('.',',')+" m²"
    except: return "ERRO m²"

# --- Funções Auxiliares SIENGE ---
def normalize_column_name_sienge(c):
    if pd.isna(c): return ""
    return str(c).upper().strip()
def determinar_tipo_imovel_sienge(row, apt_col):
    if apt_col=="APT": return "APARTAMENTO";
    elif apt_col=="CASA": return "CASA";
    else: return "INDEFINIDO"
def formatar_unidade_sienge(row, bloco_coluna_nome, apt_coluna_nome):
    bloco_str = "00"; apt_str = "00"; bloco_prefix = "??"; apt_prefix = "??"
    try:
        if bloco_coluna_nome and pd.notna(row.get(bloco_coluna_nome)):
            bloco_val = row[bloco_coluna_nome]; bpt = str(bloco_coluna_nome)[:2] if len(str(bloco_coluna_nome)) >= 2 else "??"; bloco_prefix = ''.join(filter(str.isalpha, bpt)).upper() or "??"
            try: bloco_int = int(float(bloco_val)); bloco_str = f"{bloco_int:02d}"
            except: bloco_str = str(bloco_val).strip()
        if apt_coluna_nome and pd.notna(row.get(apt_coluna_nome)):
            apt_val = row[apt_coluna_nome]; apt_prefix = str(apt_coluna_nome).upper()
            apt_num_str = ''.join(filter(str.isdigit, str(apt_val)))
            if apt_num_str:
                try: apt_int = int(apt_num_str); apt_str = f"{apt_int:02d}"
                except ValueError: apt_str = apt_num_str
            else: apt_str = "S/N"; print(f"Aviso SIENGE L{row.name if hasattr(row,'name') else 'Unk'}: Não extraiu número de '{apt_val}' em {apt_coluna_nome}")
        if bloco_coluna_nome and apt_coluna_nome: return f"{bloco_prefix}{bloco_str} - {apt_prefix} {apt_str}"
        elif bloco_coluna_nome: return f"{bloco_prefix}{bloco_str}";
        elif apt_coluna_nome: return f"{apt_prefix} {apt_str}";
        else: return "N/D"
    except Exception as e: print(f"(SIENGE) Erro formatar unidade: {e}"); return "ERRO_FORMAT"

# --- Funções Auxiliares SIENGE Lote ---
def normalize_column_name_sienge_lote(c):
    if pd.isna(c): return ""
    n=str(c).upper().strip(); n=n.replace('(M²)','(M2)').replace(' (M2)','(M2)'); n=n.replace('AREA(M2)','ÁREA(M2)')
    return n
def extrair_numero_sienge_lote(t, pref=None):
    if pd.isna(t): return None
    s=str(t).strip();
    if pref: s=re.sub(f'^{re.escape(pref)}\s*','',s,flags=re.IGNORECASE)
    m=re.search(r'\d+',s)
    try: return int(m.group(0)) if m else None
    except: return None
def formatar_unidade_sienge_lote(row, col_q, col_l):
    try:
        qv=row.get(col_q); qn=extrair_numero_sienge_lote(qv); pb=f"QD{qn:02d}" if qn is not None else ""
        lv=row.get(col_l); ln=extrair_numero_sienge_lote(lv,"LT") or extrair_numero_sienge_lote(lv,"LOTE"); pa=f"LOTE {ln:02d}" if ln is not None else ""
        if pb and pa: return f"{pb} - {pa}";
        elif pb: return pb;
        elif pa: return pa;
        else: return "LOCALIZACAO_INVALIDA"
    except: return "ERRO_FORMATACAO"
def limpar_converter_numerico_sienge_lote(v): return limpar_converter_numerico_lote(v) # Reutiliza

# --- Funções Auxiliares Formatador Incorporação ---
def processar_incorporacao_web(input_filepath):
    print(f"(Incorp) Processando: {input_filepath}")
    try:
        df = pd.read_excel(input_filepath, header=None, dtype=str); df['Bloco'] = None
        ultimo_bloco = None; rows_to_del = []
        print(f"(Incorp) Varrendo {len(df)} linhas...")
        for idx, row in df.iterrows():
            cell_val = str(row.iloc[0]).strip() if pd.notna(row.iloc[0]) else ""
            is_q = cell_val.lower().startswith("quadra"); is_b = re.search(r'^\s*bloco', cell_val, re.IGNORECASE)
            if is_q or is_b:
                print(f"  Linha {idx+1}: {'QUADRA' if is_q else 'BLOCO'} ('{cell_val}')") # idx+1 para num linha Excel
                rows_to_del.append(idx); bloco_num = None
                match = re.search(r'(?:quadra|bloco)\s*(?:n[o°.\s]?|número)?\s*(\d+)', cell_val, re.IGNORECASE)
                if match:
                    try: bloco_num = match.group(1).zfill(2); print(f"    Bloco: {bloco_num}")
                    except: print(f"    Erro extrair num: '{cell_val}'")
                if bloco_num: ultimo_bloco = bloco_num
                continue
            elif ultimo_bloco is not None: df.loc[idx, 'Bloco'] = ultimo_bloco
        print(f"(Incorp) Índices p/ del: {rows_to_del}")
        df_proc = df.drop(index=rows_to_del).copy()
        cols_orig = [c for c in df_proc.columns if c != 'Bloco']
        # Garante que Bloco seja a última coluna, mesmo se não houver outras
        df_proc = df_proc[cols_orig + (['Bloco'] if 'Bloco' in df_proc.columns else [])]
        print(f"(Incorp) Processado. {len(df_proc)} linhas.")
        output = io.BytesIO(); df_proc.to_excel(output, header=False, index=False, engine='openpyxl')
        output.seek(0); print("(Incorp) Excel em memória.")
        return output
    except Exception as e: print(f"(Incorp) ERRO: {e}"); traceback.print_exc(); raise e

# --- Funções Auxiliares Formatador Lote ---
def add_lt_prefix_if_needed_fmt_lote(v_str):
    if not isinstance(v_str,str): v_str=str(v_str)
    cleaned_value = v_str.strip() # Corrigido para usar cleaned_value
    if not cleaned_value: return ""
    if cleaned_value.isdigit(): return f"LT {cleaned_value}"
    elif cleaned_value.lower().startswith("lt"):
        if len(cleaned_value)>2 and cleaned_value[2].isspace(): return cleaned_value
        elif len(cleaned_value)>2 and cleaned_value[2].isdigit(): return f"{cleaned_value[:2]} {cleaned_value[2:].strip()}"
        else: return cleaned_value
    else: return cleaned_value
def format_measurement_fmt_lote(value_str, unit="m"):
    if not isinstance(value_str, str): value_str = str(value_str)
    cleaned_orig = value_str.strip() # Corrigido para usar cleaned_orig
    cleaned_float_attempt = cleaned_orig.lower().replace("m²", "").replace("m2", "").replace("m", "").strip()
    if not cleaned_float_attempt: return "N/A"
    try:
        numeric = float(cleaned_float_attempt.replace(',', '.'))
        formatted = f"{numeric:.2f}".replace('.', ',')
        return f"{formatted}{unit}"
    except (ValueError, TypeError):
        print(f"Aviso Fmt Lote: Valor '{cleaned_orig}' não convertido. Retornando original.") # Corrigido para cleaned_orig
        if cleaned_orig.lower().endswith(unit.lower()): return cleaned_orig
        else: return f"{cleaned_orig}{unit}" # Adiciona unidade se não tinha
def get_numeric_area_fmt_lote(a_str):
    if not isinstance(a_str,str): a_str=str(a_str)
    clean=a_str.strip().lower().replace("m²","").replace("m2","").replace("m","").strip()
    if not clean: return 0.0
    try: return float(clean.replace(',','.'))
    except: print(f"Warn Area (Fmt Lote): '{a_str}' -> 0.0"); return 0.0
def processar_formatador_lote_web(input_filepath):
    print(f"(Fmt Lote) Processando: {input_filepath}")
    try:
        df_raw=pd.read_excel(input_filepath, header=None, engine='openpyxl', dtype=str); df_raw.fillna("", inplace=True)
        dados_proc=[]; q_atual=None; q_val_num=None; cabecalho=None; map_hdr_rev={}; offset=0
        cols_esp={'lote':'LOTE', 'tipo':'TIPO', 'área(m²)':'AREA_M2','testada(m)':'TESTADA_M', 'fundo(m)':'FUNDO_M','lat. direita(n':'LAT_DIREITA_M', 'lat. direita(m)':'LAT_DIREITA_M','lat. esquerda(m)':'LAT_ESQUERDA_M','frente':'FRENTE_DESC', 'fundo':'FUNDO_DESC_CONFRONTANTE','direita':'DIREITA_DESC', 'esquerda':'ESQUERDA_DESC'}
        cols_medida={'AREA_M2':'m²', 'TESTADA_M':'m', 'FUNDO_M':'m','LAT_DIREITA_M':'m', 'LAT_ESQUERDA_M':'m'}
        cols_lt=['LOTE', 'FUNDO_DESC_CONFRONTANTE', 'DIREITA_DESC', 'ESQUERDA_DESC']
        print("(Fmt Lote) Varrendo...")
        for idx, row_s in df_raw.iterrows():
            linha=[str(v) for v in row_s.values]; linha_orig=idx+1; cel1=linha[0].strip()
            if cel1.lower().startswith(("quadra","bloco")):
                q_atual=cel1; m=re.search(r'\d+',q_atual)
                try: q_val_num=int(m.group(0)) if m else q_atual
                except: q_val_num=q_atual
                print(f" L{linha_orig}: QUADRA/BLOCO '{q_atual}' (Val:{q_val_num})"); cabecalho=None; map_hdr_rev={}; offset=linha_orig; continue
            if q_atual and not cabecalho:
                if cel1.lower()=='lote':
                    cabecalho=[h.strip() for h in linha]; print(f" L{linha_orig}: HEADER {cabecalho}")
                    map_hdr_rev={}; fundo_map={}
                    for i,hdr in enumerate(cabecalho):
                        hl=hdr.lower()
                        for el,ek in cols_esp.items():
                            if hl==el or (el=='lat. direita(n' and hl=='lat. direita(m)') or (el=='lat. direita(m)' and hl=='lat. direita(n)'):
                                if hl=='fundo':
                                    if ek=='FUNDO_M': fundo_map['FUNDO_M']=hdr
                                    elif ek=='FUNDO_DESC_CONFRONTANTE': fundo_map['FUNDO_DESC_CONFRONTANTE']=hdr
                                else: map_hdr_rev[ek]=hdr; break
                    if fundo_map.get('FUNDO_M')==fundo_map.get('FUNDO_DESC_CONFRONTANTE'):
                        if 'FUNDO_DESC_CONFRONTANTE' in fundo_map: map_hdr_rev['FUNDO_DESC_CONFRONTANTE']=fundo_map['FUNDO_DESC_CONFRONTANTE']
                    else:
                        if 'FUNDO_M' in fundo_map: map_hdr_rev['FUNDO_M']=fundo_map['FUNDO_M']
                        if 'FUNDO_DESC_CONFRONTANTE' in fundo_map: map_hdr_rev['FUNDO_DESC_CONFRONTANTE']=fundo_map['FUNDO_DESC_CONFRONTANTE']
                    print(f" Mapa Hdr Rev: {map_hdr_rev}"); offset=linha_orig; continue
                elif not any(c.strip() for c in linha): continue
                else: print(f" Warn L{linha_orig}: Ignorando linha antes do header '{cel1}'"); continue
            if q_atual and cabecalho:
                if any(c.strip() for c in linha) and cel1.lower()!='lote':
                    if len(linha)<len(cabecalho): linha.extend([""]*(len(cabecalho)-len(linha)))
                    if len(linha)>len(cabecalho): linha=linha[:len(cabecalho)]
                    d_lin=dict(zip(cabecalho,linha)); d_lin['QUADRA']=q_val_num
                    a_col=map_hdr_rev.get('AREA_M2'); a_str=d_lin.get(a_col,"") if a_col else ""; d_lin['_area_numerica']=get_numeric_area_fmt_lote(a_str)
                    for ek,u in cols_medida.items():
                        cr=map_hdr_rev.get(ek);
                        if cr and cr in d_lin: d_lin[cr]=format_measurement_fmt_lote(d_lin[cr],u)
                    for ek in cols_lt:
                        cr=map_hdr_rev.get(ek);
                        if cr and cr in d_lin: d_lin[cr]=add_lt_prefix_if_needed_fmt_lote(d_lin[cr])
                    try:
                        tm,fd = map_hdr_rev.get('TESTADA_M'),map_hdr_rev.get('FRENTE_DESC'); fum,fudc=map_hdr_rev.get('FUNDO_M'),map_hdr_rev.get('FUNDO_DESC_CONFRONTANTE'); ldm,dd=map_hdr_rev.get('LAT_DIREITA_M'),map_hdr_rev.get('DIREITA_DESC'); lem,ed=map_hdr_rev.get('LAT_ESQUERDA_M'),map_hdr_rev.get('ESQUERDA_DESC')
                        vt=d_lin.get(tm,"N/A") if tm else"N/A"; dfrente=d_lin.get(fd,"").strip() if fd else""; vf=d_lin.get(fum,"N/A") if fum else"N/A"; dfc=d_lin.get(fudc,"") if fudc else""; vld=d_lin.get(ldm,"N/A") if ldm else"N/A"; ddir=d_lin.get(dd,"") if dd else""; vle=d_lin.get(lem,"N/A") if lem else"N/A"; desq=d_lin.get(ed,"") if ed else""
                        pts=[]
                        if vt!="N/A" and dfrente and dfrente!="-": pts.append(f"Frente: {vt} - Confrontante: {dfrente}") # Corrigido para dfrente
                        if vf!="N/A" and dfc and dfc!="-": pts.append(f"Fundo: {vf} - Confrontante: {dfc}")
                        if vld!="N/A" and ddir and ddir!="-": pts.append(f"Lado Direito: {vld} - Confrontante: {ddir}")
                        if vle!="N/A" and desq and desq!="-": pts.append(f"Lado Esquerdo: {vle} - Confrontante: {desq}")
                        d_lin['CONFRONTANTES']=" <br>".join(pts)
                    except Exception as ec: print(f"Err CONF L{linha_orig}: {ec}"); d_lin['CONFRONTANTES']="Erro Conf."
                    dados_proc.append(d_lin)
        print(f"(Fmt Lote) Varredura FIM. {len(dados_proc)} linhas.")
        if not dados_proc: raise ValueError("Nenhum dado de lote encontrado.")
        df_final=pd.DataFrame(dados_proc); df_final['ETAPA']=1
        total_a=df_final['_area_numerica'].sum()
        df_final['FRAÇÃO IDEAL']=df_final['_area_numerica']/total_a if total_a>0 else 0.0
        df_final=df_final.drop(columns=['_area_numerica'])
        if cabecalho:
            orig_ord=[h for h in cabecalho if h in df_final.columns and h not in ['QUADRA','ETAPA','CONFRONTANTES','FRAÇÃO IDEAL']]
            final_ord=['QUADRA','ETAPA']+orig_ord+['FRAÇÃO IDEAL','CONFRONTANTES']
            final_ex=[c for c in final_ord if c in df_final.columns]; df_final=df_final[final_ex]
        else: print("(Fmt Lote) Warn: Header não detectado, não reordenado.")
        for c in ['QUADRA','ETAPA']:
            if c in df_final.columns: df_final[c]=pd.to_numeric(df_final[c],errors='coerce').astype('Int64')
        if 'FRAÇÃO IDEAL' in df_final.columns: df_final['FRAÇÃO IDEAL']=pd.to_numeric(df_final['FRAÇÃO IDEAL'],errors='coerce')
        print("(Fmt Lote) DF final pronto.")
        output=io.BytesIO(); df_final.to_excel(output,index=False,header=True,engine='openpyxl'); output.seek(0)
        print("(Fmt Lote) Excel em memória."); return output
    except Exception as e: print(f"(Fmt Lote) ERRO GERAL: {e}"); traceback.print_exc(); raise e

# --- Rotas Flask ---

@app.route('/')
def home():
    return render_template('home.html', active_page='home')

# === ROTAS IMPORTAÇÃO CV ===
@app.route('/importacao-cv')
def importacao_cv_index():
    session.pop('cv_uploaded_filename', None); session.pop('cv_basic_info', None)
    session.pop('cv_tipos_unicos', None); session.pop('cv_is_casa_project', None)
    return render_template('importacao_cv.html', active_page='importacao_cv')

@app.route('/upload-cv', methods=['POST'])
def upload_file_cv():
    tool_prefix = 'cv_'
    if 'arquivo_entrada' not in request.files: flash('Nenhum arquivo!', 'error'); return redirect(url_for('importacao_cv_index'))
    file = request.files['arquivo_entrada']
    if file.filename == '': flash('Nenhum arquivo!', 'error'); return redirect(url_for('importacao_cv_index'))
    if file and allowed_file(file.filename):
        filename = secure_filename(f"{tool_prefix}{file.filename}")
        temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        try:
            file.save(temp_filepath)
            df_chk = pd.read_excel(temp_filepath, engine="openpyxl")
            df_chk.columns = df_chk.columns.str.strip()
            is_casa = "CASA" in df_chk.columns or "Quadra" in df_chk.columns
            n_cols = {normalize_text(c): c for c in df_chk.columns}
            t_col_orig = n_cols.get("TIPO")
            if t_col_orig:
                if t_col_orig.upper() != 'TIPO': df_chk.rename(columns={t_col_orig: "TIPO"}, inplace=True)
            else:
                found_alternative = False; alternatives = ["Tipologia", "Tipo da Unidade"]
                for alt in alternatives:
                    t_col_alt_orig = n_cols.get(normalize_text(alt))
                    if t_col_alt_orig: df_chk.rename(columns={t_col_alt_orig: "TIPO"}, inplace=True); found_alternative = True; break
                if not found_alternative: raise ValueError(f"Coluna 'TIPO' (ou alt: {', '.join(alternatives)}) não encontrada!")
            if "TIPO" not in df_chk.columns: raise ValueError("Erro TIPO.")
            tipos = sorted(df_chk["TIPO"].dropna().astype(str).str.strip().unique())
            if not tipos: flash("Aviso: Coluna 'TIPO' vazia.", 'warning')
            session[f'{tool_prefix}uploaded_filename'] = filename; session[f'{tool_prefix}basic_info'] = request.form.to_dict()
            session[f'{tool_prefix}tipos_unicos'] = tipos; session[f'{tool_prefix}is_casa_project'] = is_casa
            return redirect(url_for('map_tipologias_cv_route'))
        except Exception as e:
            if 'temp_filepath' in locals() and os.path.exists(temp_filepath): os.remove(temp_filepath)
            flash(f'Erro CV Upload: {e}','error'); print(f"Err CV Up: {e}"); traceback.print_exc()
            return redirect(url_for('importacao_cv_index'))
    else: flash('Arquivo inválido.','error'); return redirect(url_for('importacao_cv_index'))

@app.route('/map-tipologias-cv')
def map_tipologias_cv_route():
    tool_prefix = 'cv_'
    if f'{tool_prefix}uploaded_filename' not in session: flash('Upload CV primeiro.','warning'); return redirect(url_for('importacao_cv_index'))
    tipos=session.get(f'{tool_prefix}tipos_unicos',[]); is_casa=session.get(f'{tool_prefix}is_casa_project', False)
    return render_template('map_tipologias_cv.html', active_page='importacao_cv', tipos_unicos=tipos, is_casa_project=is_casa,
                           tipologias_padrao=TIPOLOGIAS_PADRAO, tipologias_superior=TIPOLOGIAS_SUPERIOR, tipologias_pcd=TIPOLOGIAS_PCD)

@app.route('/process-cv', methods=['POST'])
def process_file_cv():
    tool_prefix = 'cv_'
    if f'{tool_prefix}uploaded_filename' not in session: flash('Sessão expirada CV.','error'); return redirect(url_for('importacao_cv_index'))
    fname=session[f'{tool_prefix}uploaded_filename']; basic=session[f'{tool_prefix}basic_info']; is_casa=session.get(f'{tool_prefix}is_casa_project',False); tipos_orig=session.get(f'{tool_prefix}tipos_unicos',[])
    fpath=os.path.join(app.config['UPLOAD_FOLDER'],fname)
    if not os.path.exists(fpath): flash('Arquivo temp sumiu.','error'); return redirect(url_for('importacao_cv_index'))
    try:
        tip_map={}
        for t in tipos_orig:
            p,pc,s=request.form.get(f'tipo_{t}_padrao','').strip(), request.form.get(f'tipo_{t}_pcd','').strip(), request.form.get(f'tipo_{t}_superior','').strip() if not is_casa else None
            cp,cpc,cs = TIPOLOGIAS_PADRAO.get(p,p or None), TIPOLOGIAS_PCD.get(pc,pc or None), TIPOLOGIAS_SUPERIOR.get(s,s or None) if s is not None else None
            tip_map[t]={'padrao':cp,'pcd':cpc,'superior':cs}
        df=pd.read_excel(fpath,engine="openpyxl"); df.columns=df.columns.str.strip()
        n_cols={normalize_text(c):c for c in df.columns}; t_col=n_cols.get("TIPO")
        if t_col and t_col.upper()!='TIPO': df.rename(columns={t_col:"TIPO"},inplace=True)
        elif "TIPO" not in df.columns: raise ValueError("Coluna TIPO sumiu.")
        g_col=encontrar_coluna_garagem(df.columns)
        if g_col: df.rename(columns={g_col:"GARAGEM_ORIG"},inplace=True); g_col="GARAGEM_ORIG"
        col_map_ui={"Nome do Empreendimento":"Nome (Empreendimento)","Sigla":"Sigla (Empreendimento)","Empresa":"Empresa (Empreendimento)","Tipo":"Tipo (Empreendimento)","Segmento":"Segmento (Empreendimento)"}
        for k,v in col_map_ui.items(): df[v]=basic.get(k,'')
        col_map_fix={"Endereço":"Endereço (Empreendimento)","CEP":"CEP (Empreendimento)","Região":"Região (Empreendimento)","Bairro":"Bairro (Empreendimento)","Número":"Número (Empreendimento)","Estado":"Estado (Empreendimento)","Cidade":"Cidade (Empreendimento)","Data da Entrega (Empreendimento)":"Data da Entrega (Empreendimento)"}
        for k,v in ENDERECO_FIXO.items():
            if k in col_map_fix: df[col_map_fix[k]]=v
        df["Matrícula (Empreendimento)"]="XXXXX"; df["Ativo no painel (Empreendimento)"]="Ativo"; df["Nome (Etapa)"]="ETAPA 01"; df["Nome (Bloco)"]="BLOCO 01"; df["Ativo no painel (Unidade)"]="Ativo"
        df["Nome (Unidade)"]=df.apply(formatar_nome_unidade,axis=1)
        v_num_mode=basic.get('vaga_por_numero')=='on'
        df["Vagas de garagem (Unidade)"]=df[g_col].apply(lambda x: verificar_vaga(x, v_num_mode)) if g_col else "01 VAGA"
        df["Área de Garagem (Unidade)"]=df[g_col] if g_col else ""
        q_col=next((c for c in df.columns if normalize_text(c)=='QUINTAL'),None); df["Jardim (Unidade)"]=df[q_col].apply(formatar_jardim) if q_col else ""
        a_col=next((c for c in df.columns if normalize_text(c)=='AREA CONSTRUIDA'),None); df["Área privativa (Unidade)"]=df[a_col] if a_col else ""
        f_col=next((c for c in df.columns if normalize_text(c)=='FRACAO IDEAL'),None); df["Fração Ideal (Unidade)"]=df[f_col] if f_col else ""
        df["Tipo (Unidade)"]=df["TIPO"].astype(str).fillna(''); df["Tipologia (Unidade)"]=df.apply(lambda r: mapear_tipologia_web(r, tip_map, is_casa), axis=1)
        cols_out=["Nome (Empreendimento)","Sigla (Empreendimento)","Matrícula (Empreendimento)","Empresa (Empreendimento)","Tipo (Empreendimento)","Segmento (Empreendimento)","Ativo no painel (Empreendimento)","Região (Empreendimento)","CEP (Empreendimento)","Endereço (Empreendimento)","Bairro (Empreendimento)","Número (Empreendimento)","Estado (Empreendimento)","Cidade (Empreendimento)","Data da Entrega (Empreendimento)","Nome (Etapa)","Nome (Bloco)","Nome (Unidade)","Tipologia (Unidade)","Tipo (Unidade)","Área privativa (Unidade)","Jardim (Unidade)","Área de Garagem (Unidade)","Vagas de garagem (Unidade)","Fração Ideal (Unidade)","Ativo no painel (Unidade)"]
        df_final=df[[c for c in cols_out if c in df.columns]]
        output=io.StringIO(); df_final.to_csv(output,index=False,encoding='utf-8-sig',sep=';',quoting=csv.QUOTE_MINIMAL,decimal=',')
        output.seek(0)
        if os.path.exists(fpath): os.remove(fpath)
        session.pop(f'{tool_prefix}uploaded_filename',None); session.pop(f'{tool_prefix}basic_info',None); session.pop(f'{tool_prefix}tipos_unicos',None); session.pop(f'{tool_prefix}is_casa_project',None)
        out_fname=f"importacao_cv_{basic.get('Sigla','output')}.csv"
        return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name=out_fname)
    except Exception as e:
        flash(f'Erro CV Process: {e}','error'); print(f"Err CV Proc: {e}"); traceback.print_exc()
        if 'fpath' in locals() and os.path.exists(fpath): os.remove(fpath)
        session.pop(f'{tool_prefix}uploaded_filename',None); session.pop(f'{tool_prefix}basic_info',None); session.pop(f'{tool_prefix}tipos_unicos',None); session.pop(f'{tool_prefix}is_casa_project',None)
        return redirect(url_for('importacao_cv_index'))

# === ROTAS IMPORTAÇÃO CV LOTE ===
@app.route('/importacao-cv-lote', methods=['GET', 'POST'])
def importacao_cv_lote_tool():
    tool_prefix = 'cv_lote_'
    if request.method == 'POST':
        if 'arquivo_entrada' not in request.files: flash('Nenhum arquivo Lote!', 'error'); return redirect(url_for('importacao_cv_lote_tool'))
        file=request.files['arquivo_entrada']
        if file.filename=='': flash('Nenhum arquivo Lote!','error'); return redirect(url_for('importacao_cv_lote_tool'))
        if not file or not allowed_file(file.filename): flash('Tipo inválido Lote.','error'); return redirect(url_for('importacao_cv_lote_tool'))
        basic=request.form.to_dict(); fname=secure_filename(f"{tool_prefix}{file.filename}"); fpath=os.path.join(app.config['UPLOAD_FOLDER'],fname)
        try:
            file.save(fpath); print(f"(Lote) Salvo: {fpath}")
            df=pd.read_excel(fpath,engine="openpyxl",dtype=str); df.columns=df.columns.str.strip()
            n_cols={normalize_text_lote(c):c for c in df.columns}
            cols_norm={"QUADRA":"QUADRA","LOTE":"LOTE","AREACONSTRUIDA":"ÁREA(M2)","AREA CONSTRUIDA":"ÁREA(M2)","AREACONSTRUIDAM2":"ÁREA(M2)","AREA CONSTRUIDA M2":"ÁREA(M2)","AREA(M2)":"ÁREA(M2)","AREAM2":"ÁREA(M2)","FRACAOIDEAL":"FRAÇÃO IDEAL","FRACAO IDEAL":"FRAÇÃO IDEAL","TIPO":"TIPO","CONFRONTANTES":"CONFRONTANTES"}
            cols_found={}; needed=["QUADRA","LOTE","ÁREA(M2)","FRAÇÃO IDEAL","TIPO","CONFRONTANTES"]; missing=set(needed)
            for norm,concept in cols_norm.items():
                orig=n_cols.get(norm);
                if orig and orig in df.columns and concept not in cols_found: cols_found[concept]=orig;
                if concept in missing: missing.remove(concept)
            if missing: raise ValueError(f"Colunas Lote faltando: {', '.join(missing)}")
            print(f"(Lote) Colunas: {cols_found}")
            df["Nome (Empreendimento)"]=basic.get("Nome do Empreendimento",""); df["Sigla (Empreendimento)"]=basic.get("Sigla",""); df["Empresa (Empreendimento)"]=basic.get("Empresa",""); df["Tipo (Empreendimento)"]=basic.get("Tipo","Loteamento"); df["Segmento (Empreendimento)"]=basic.get("Segmento","Residencial");
            df["Matrícula (Empreendimento)"]="XXXXX";
            # <<< CORREÇÃO APLICADA AQUI >>>
            df["Ativo no painel (Empreendimento)"]="Ativo"; # Corrigido de "panel" para "painel"
            # <<< FIM DA CORREÇÃO >>>
            df["Região (Empreendimento)"]=ENDERECO_FIXO["Região"]; df["CEP (Empreendimento)"]=ENDERECO_FIXO["CEP"]; df["Endereço (Empreendimento)"]=ENDERECO_FIXO["Endereço"]; df["Bairro (Empreendimento)"]=ENDERECO_FIXO["Bairro"]; df["Número (Empreendimento)"]=ENDERECO_FIXO["Número"]; df["Estado (Empreendimento)"]=ENDERECO_FIXO["Estado"]; df["Cidade (Empreendimento)"]=ENDERECO_FIXO["Cidade"]; df["Data da Entrega (Empreendimento)"]=ENDERECO_FIXO["Data da Entrega (Empreendimento)"]; df["Nome (Etapa)"]="ETAPA ÚNICA"; df["Ativo no painel (Unidade)"]="Ativo"
            df["Nome (Bloco)"]=df.apply(lambda r: formatar_nome_bloco_lote(r,col_q=cols_found["QUADRA"]),axis=1)
            df["Nome (Unidade)"]=df.apply(lambda r: formatar_nome_unidade_lote(r,col_q=cols_found["QUADRA"],col_l=cols_found["LOTE"]),axis=1)
            a_num=df[cols_found["ÁREA(M2)"]].apply(limpar_converter_numerico_lote); df["Área privativa m² (Unidade)"]=a_num.apply(formatar_area_privativa_lote)
            f_num=df[cols_found["FRAÇÃO IDEAL"]].apply(limpar_converter_numerico_lote); df["Fração Ideal (Unidade)"]=f_num.apply(formatar_fracao_ideal_lote)
            df["Tipo (Unidade)"]=df[cols_found["TIPO"]].astype(str).fillna(''); df["Descrição do Lote (Unidade)"]=df[cols_found["CONFRONTANTES"]].astype(str).fillna('')
            cols_out=["Nome (Empreendimento)","Sigla (Empreendimento)","Matrícula (Empreendimento)","Empresa (Empreendimento)","Tipo (Empreendimento)","Segmento (Empreendimento)","Ativo no painel (Empreendimento)","Região (Empreendimento)","CEP (Empreendimento)","Endereço (Empreendimento)","Bairro (Empreendimento)","Número (Empreendimento)","Estado (Empreendimento)","Cidade (Empreendimento)","Data da Entrega (Empreendimento)","Nome (Etapa)","Nome (Bloco)","Nome (Unidade)","Área privativa m² (Unidade)","Ativo no painel (Unidade)","Fração Ideal (Unidade)","Tipo (Unidade)","Descrição do Lote (Unidade)"]
            missing_out=[c for c in cols_out if c not in df.columns];
            if missing_out: raise ValueError(f"Erro Lote: Colunas finais faltando: {', '.join(missing_out)}")
            df_final=df[cols_out].copy()
            output=io.StringIO(); df_final.astype(str).to_csv(output,index=False,encoding='utf-8-sig',sep=';',quoting=csv.QUOTE_MINIMAL)
            output.seek(0)
            if os.path.exists(fpath): os.remove(fpath)
            out_fname=f"importacao_cv_lote_{basic.get('Sigla','output')}.csv"
            return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')),mimetype='text/csv',as_attachment=True,download_name=out_fname)
        except Exception as e:
            flash(f"Erro Lote: {e}",'error'); print(f"(Lote) Err: {e}"); traceback.print_exc()
            if 'fpath' in locals() and os.path.exists(fpath): os.remove(fpath)
            return redirect(url_for('importacao_cv_lote_tool'))
    else: # GET
        return render_template('importacao_cv_lote.html', active_page='importacao_cv_lote')

# === ROTAS IMPORTAÇÃO SIENGE ===
@app.route('/importacao-sienge')
def importacao_sienge_index():
    session.pop('sienge_uploaded_filename', None); session.pop('sienge_etapas_unicas', None)
    return render_template('importacao_sienge.html', active_page='importacao_sienge')

@app.route('/upload-sienge', methods=['POST'])
def upload_file_sienge():
    tool_prefix = 'sienge_'
    if 'arquivo_entrada' not in request.files: flash('Nenhum arquivo SIENGE!', 'error'); return redirect(url_for('importacao_sienge_index'))
    file = request.files['arquivo_entrada']
    if file.filename == '': flash('Nenhum arquivo SIENGE!', 'error'); return redirect(url_for('importacao_sienge_index'))
    if not file or not allowed_file(file.filename): flash('Tipo inválido SIENGE.', 'error'); return redirect(url_for('importacao_sienge_index'))
    filename = secure_filename(f"{tool_prefix}{file.filename}")
    temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        file.save(temp_filepath); print(f"(SIENGE) Arquivo salvo: {temp_filepath}")
        df = pd.read_excel(temp_filepath, engine="openpyxl"); df.columns = df.columns.str.upper().str.strip()
        if "ETAPA" not in df.columns: raise ValueError("Coluna 'ETAPA' não encontrada!")
        try: etapas_u = sorted(df["ETAPA"].dropna().astype(str).unique())
        except Exception as e: raise ValueError(f"Erro ao processar coluna 'ETAPA': {e}")
        if not etapas_u: flash("Nenhuma etapa encontrada.", 'warning') # Permite continuar
        session[f'{tool_prefix}uploaded_filename'] = filename
        session[f'{tool_prefix}etapas_unicas'] = etapas_u
        print(f"(SIENGE) Etapas encontradas: {etapas_u}")
        return redirect(url_for('map_etapas_sienge_route'))
    except Exception as e:
        flash(f"Erro SIENGE: {e}", 'error'); print(f"(SIENGE) Erro upload: {e}"); traceback.print_exc()
        if 'temp_filepath' in locals() and os.path.exists(temp_filepath): os.remove(temp_filepath)
        return redirect(url_for('importacao_sienge_index'))

@app.route('/map-etapas-sienge')
def map_etapas_sienge_route():
    tool_prefix = 'sienge_'
    if f'{tool_prefix}uploaded_filename' not in session: flash('Faça upload SIENGE primeiro.', 'warning'); return redirect(url_for('importacao_sienge_index'))
    etapas = session.get(f'{tool_prefix}etapas_unicas', [])
    return render_template('map_etapas_sienge.html',
                           active_page='importacao_sienge',
                           etapas_unicas=etapas,
                           tool_name="SIENGE",
                           process_url=url_for('process_file_sienge'),
                           cancel_url=url_for('importacao_sienge_index')
                           )

@app.route('/process-sienge', methods=['POST'])
def process_file_sienge():
    tool_prefix = 'sienge_'
    if f'{tool_prefix}uploaded_filename' not in session: flash('Sessão expirada SIENGE.','error'); return redirect(url_for('importacao_sienge_index'))
    fname=session[f'{tool_prefix}uploaded_filename']; fpath=os.path.join(app.config['UPLOAD_FOLDER'],fname); etapas_orig=session.get(f'{tool_prefix}etapas_unicas',[])
    if not os.path.exists(fpath): flash('Arquivo temp SIENGE sumiu.','error'); return redirect(url_for('importacao_sienge_index'))
    try:
        etapas_map={}; any_map=False
        print("(SIENGE) Coletando mapeamento:");
        for et_o in etapas_orig:
            val=request.form.get(f'etapa_{et_o}','').strip(); et_dig=''.join(filter(str.isdigit,str(et_o)))
            if et_dig and val: etapas_map[et_dig]=val; any_map=True; print(f" '{et_dig}' -> '{val}'")
            elif et_dig: print(f" Aviso: Etapa '{et_o}' não mapeada.")
        if not any_map and etapas_orig: print(" Nenhum mapeamento.")
        print("-"*30)
        df=pd.read_excel(fpath,engine="openpyxl"); df.columns=df.columns.str.upper().str.strip()
        bloco_col="QUADRA" if "QUADRA" in df.columns else "BLOCO" if "BLOCO" in df.columns else None
        apt_col="CASA" if "CASA" in df.columns else "APT" if "APT" in df.columns else None
        cols_ess=["ETAPA","ÁREA CONSTRUÍDA","FRAÇÃO IDEAL"]
        if not bloco_col and not apt_col: raise ValueError("Faltando cols ID (QUADRA/BLOCO ou CASA/APT)")
        if bloco_col: cols_ess.append(bloco_col);
        if apt_col: cols_ess.append(apt_col)
        missing=[c for c in cols_ess if c not in df.columns];
        if missing: raise ValueError(f"Colunas SIENGE faltando: {', '.join(missing)}")
        def map_et_int(row): et_s=str(row.get('ETAPA','')); et_n=''.join(filter(str.isdigit,et_s)); return etapas_map.get(et_n,None)
        df["EMPREENDIMENTO_CODIGO"]=df.apply(map_et_int,axis=1)
        df_out=pd.DataFrame(); df_out['EMPREENDIMENTO']=df['EMPREENDIMENTO_CODIGO']
        df_out['UNIDADE']=df.apply(lambda r: formatar_unidade_sienge(r,bloco_col,apt_col),axis=1)
        df_out['ÁREA PRIVATIVA']=pd.to_numeric(df['ÁREA CONSTRUÍDA'],errors='coerce').fillna(0)
        df_out['ÁREA COMUM']=0; df_out['FRAÇÃO IDEAL']=pd.to_numeric(df['FRAÇÃO IDEAL'],errors='coerce').fillna(0)
        df_out['TIPO DE IMÓVEL']=df.apply(lambda r: determinar_tipo_imovel_sienge(r,apt_col),axis=1)
        df_out['ESTOQUE COMERCIAL']='D'; df_out['ESTOQUE LEGAL']='L'; df_out['ESTOQUE DE OBRA']='C'
        output=io.BytesIO(); wb=xlwt.Workbook(encoding='utf-8'); sheet=wb.add_sheet("Dados")
        for c,h in enumerate(df_out.columns): sheet.write(0,c,h)
        for r, row_data in enumerate(df_out.itertuples(index=False),start=1):
            for c,val in enumerate(row_data):
                if pd.isna(val): sheet.write(r,c,None)
                else:
                    try:
                        if isinstance(val,str) and len(val)>32767: val=val[:32767]
                        sheet.write(r,c,val)
                    except: sheet.write(r,c,str(val))
        wb.save(output); output.seek(0); print("(SIENGE) XLS gerado.")
        if os.path.exists(fpath): os.remove(fpath)
        session.pop(f'{tool_prefix}uploaded_filename',None); session.pop(f'{tool_prefix}etapas_unicas',None)
        out_fname=f"importacao_sienge_{fname.replace(tool_prefix,'').rsplit('.',1)[0]}.xls"
        return send_file(output,mimetype='application/vnd.ms-excel',as_attachment=True,download_name=out_fname)
    except Exception as e:
        flash(f'Erro SIENGE: {e}','error'); print(f"(SIENGE) Err: {e}"); traceback.print_exc()
        if 'fpath' in locals() and os.path.exists(fpath): os.remove(fpath)
        session.pop(f'{tool_prefix}uploaded_filename',None); session.pop(f'{tool_prefix}etapas_unicas',None)
        if f'{tool_prefix}uploaded_filename' in session: return redirect(url_for('map_etapas_sienge_route'))
        else: return redirect(url_for('importacao_sienge_index'))

# === ROTAS IMPORTAÇÃO SIENGE LOTE ===
@app.route('/importacao-sienge-lote')
def importacao_sienge_lote_index():
    session.pop('sienge_lote_uploaded_filename', None); session.pop('sienge_lote_etapas_unicas', None)
    return render_template('importacao_sienge_lote.html', active_page='importacao_sienge_lote')

@app.route('/upload-sienge-lote', methods=['POST'])
def upload_file_sienge_lote():
    tool_prefix = 'sienge_lote_'
    if 'arquivo_entrada' not in request.files: flash('Nenhum arquivo S Lote!', 'error'); return redirect(url_for('importacao_sienge_lote_index'))
    file = request.files['arquivo_entrada']
    if file.filename == '': flash('Nenhum arquivo S Lote!', 'error'); return redirect(url_for('importacao_sienge_lote_index'))
    if not file or not allowed_file(file.filename): flash('Tipo inválido S Lote.', 'error'); return redirect(url_for('importacao_sienge_lote_index'))
    filename = secure_filename(f"{tool_prefix}{file.filename}")
    temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    try:
        file.save(temp_filepath); print(f"(S Lote) Salvo: {temp_filepath}")
        df=pd.read_excel(temp_filepath, engine="openpyxl")
        orig_cols=df.columns.tolist(); df.columns=[normalize_column_name_sienge_lote(c) for c in df.columns] # Aplica normalização S Lote
        print(f"(S Lote) Cols Orig: {orig_cols}"); print(f"(S Lote) Cols Norm: {df.columns.tolist()}")
        cols_nec=["ETAPA","QUADRA","LOTE","ÁREA(M2)","FRAÇÃO IDEAL"]
        missing=[c for c in cols_nec if c not in df.columns]
        if missing: raise ValueError(f"Colunas S Lote faltando: {', '.join(missing)}")
        etapas_u=sorted(df["ETAPA"].dropna().astype(str).unique())
        if not etapas_u: flash("Nenhuma etapa encontrada.",'warning')
        session[f'{tool_prefix}uploaded_filename']=filename; session[f'{tool_prefix}etapas_unicas']=etapas_u
        print(f"(S Lote) Etapas: {etapas_u}")
        return redirect(url_for('map_etapas_sienge_lote_route'))
    except Exception as e:
        flash(f"Erro S Lote: {e}",'error'); print(f"(S Lote) Err Upload: {e}"); traceback.print_exc()
        if 'temp_filepath' in locals() and os.path.exists(temp_filepath): os.remove(temp_filepath)
        return redirect(url_for('importacao_sienge_lote_index'))

@app.route('/map-etapas-sienge-lote')
def map_etapas_sienge_lote_route():
    tool_prefix = 'sienge_lote_'
    if f'{tool_prefix}uploaded_filename' not in session: flash('Upload S Lote primeiro.','warning'); return redirect(url_for('importacao_sienge_lote_index'))
    etapas=session.get(f'{tool_prefix}etapas_unicas',[])
    return render_template('map_etapas_sienge.html', active_page='importacao_sienge_lote',
                           etapas_unicas=etapas, tool_name="SIENGE Lote",
                           process_url=url_for('process_file_sienge_lote'),
                           cancel_url=url_for('importacao_sienge_lote_index'))

@app.route('/process-sienge-lote', methods=['POST'])
def process_file_sienge_lote():
    tool_prefix = 'sienge_lote_'
    if f'{tool_prefix}uploaded_filename' not in session: flash('Sessão expirada S Lote.','error'); return redirect(url_for('importacao_sienge_lote_index'))
    fname=session[f'{tool_prefix}uploaded_filename']; fpath=os.path.join(app.config['UPLOAD_FOLDER'],fname); etapas_orig=session.get(f'{tool_prefix}etapas_unicas',[])
    if not os.path.exists(fpath): flash('Arquivo temp S Lote sumiu.','error'); return redirect(url_for('importacao_sienge_lote_index'))
    try:
        etapas_map={}; any_map=False
        print("(S Lote) Coletando mapeamento:");
        for et_o in etapas_orig:
            val=request.form.get(f'etapa_{et_o}','').strip(); et_dig=''.join(filter(str.isdigit,str(et_o)))
            if et_dig and val: etapas_map[et_dig]=val; any_map=True; print(f" '{et_dig}' -> '{val}'")
            elif et_dig: print(f" Aviso S Lote: Etapa '{et_o}' não mapeada.")
        if not any_map and etapas_orig: print(" Nenhum mapeamento S Lote.")
        print("-"*30)
        df=pd.read_excel(fpath,engine="openpyxl"); df.columns=[normalize_column_name_sienge_lote(c) for c in df.columns] # Renormaliza
        col_q="QUADRA"; col_l="LOTE"; col_a="ÁREA(M2)"; col_f="FRAÇÃO IDEAL"; col_e="ETAPA" # Nomes já normalizados
        cols_nec=[col_e,col_q,col_l,col_a,col_f]; missing=[c for c in cols_nec if c not in df.columns]
        if missing: raise ValueError(f"Colunas S Lote faltando no proc: {', '.join(missing)}")
        def map_et_int(row): et_s=str(row.get(col_e,'')); et_n=''.join(filter(str.isdigit,et_s)); return etapas_map.get(et_n,None)
        df["EMPREENDIMENTO_CODIGO"]=df.apply(map_et_int,axis=1)
        df_out=pd.DataFrame(); df_out['EMPREENDIMENTO']=df['EMPREENDIMENTO_CODIGO']
        df_out['UNIDADE']=df.apply(lambda r: formatar_unidade_sienge_lote(r,col_q,col_l),axis=1)
        df_out['ÁREA PRIVATIVA']=df[col_a].apply(limpar_converter_numerico_sienge_lote)
        df_out['ÁREA COMUM']=0; df_out['FRAÇÃO IDEAL']=df[col_f].apply(limpar_converter_numerico_sienge_lote)
        df_out['TIPO DE IMÓVEL']="LOTE"
        df_out['ESTOQUE COMERCIAL']='D'; df_out['ESTOQUE LEGAL']='L'; df_out['ESTOQUE DE OBRA']='C'
        output=io.BytesIO(); wb=xlwt.Workbook(encoding='utf-8'); sheet=wb.add_sheet("Dados")
        style_a=xlwt.XFStyle(); style_a.num_format_str='0.00'; style_e=xlwt.XFStyle(); style_e.num_format_str='0'; style_f=xlwt.XFStyle(); style_f.num_format_str='0.00000000'; def_s=xlwt.Style.default_style
        try: col_idx={n:i for i,n in enumerate(df_out.columns)}; emp_i,area_i,frac_i = col_idx.get('EMPREENDIMENTO'),col_idx.get('ÁREA PRIVATIVA'),col_idx.get('FRAÇÃO IDEAL')
        except: emp_i=area_i=frac_i=None
        for c,h in enumerate(df_out.columns): sheet.write(0,c,h)
        print(f"(S Lote) Escrevendo {len(df_out)} linhas...")
        for r,row_data in enumerate(df_out.itertuples(index=False),start=1):
            for c,val in enumerate(row_data):
                st=def_s; p_val=val
                if pd.isna(p_val): sheet.write(r,c,None); continue
                if emp_i is not None and c==emp_i:
                    try: p_val=int(float(val)); st=style_e
                    except: pass # Mantem string se não converter
                elif area_i is not None and c==area_i and isinstance(p_val,(int,float)): st=style_a
                elif frac_i is not None and c==frac_i and isinstance(p_val,(int,float)): st=style_f
                try:
                    if isinstance(p_val,str) and len(p_val)>32767: p_val=p_val[:32767]
                    sheet.write(r,c,p_val,st)
                except: sheet.write(r,c,str(p_val),def_s) # Fallback
        wb.save(output); output.seek(0); print("(S Lote) XLS gerado.")
        if os.path.exists(fpath): os.remove(fpath)
        session.pop(f'{tool_prefix}uploaded_filename',None); session.pop(f'{tool_prefix}etapas_unicas',None)
        out_fname=f"importacao_sienge_lote_{fname.replace(tool_prefix,'').rsplit('.',1)[0]}.xls"
        return send_file(output,mimetype='application/vnd.ms-excel',as_attachment=True,download_name=out_fname)
    except Exception as e:
        flash(f'Erro S Lote: {e}','error'); print(f"(S Lote) Err: {e}"); traceback.print_exc()
        if 'fpath' in locals() and os.path.exists(fpath): os.remove(fpath)
        session.pop(f'{tool_prefix}uploaded_filename',None); session.pop(f'{tool_prefix}etapas_unicas',None)
        if f'{tool_prefix}uploaded_filename' in session: return redirect(url_for('map_etapas_sienge_lote_route'))
        else: return redirect(url_for('importacao_sienge_lote_index'))

# === ROTA PARA FORMATADOR INCORPORAÇÃO ===
@app.route('/formatador-incorporacao', methods=['GET', 'POST'])
def formatador_incorporacao_tool():
    tool_prefix = 'incorp_'
    temp_filepath = None # Definir fora do try para garantir acesso no finally
    output_stream = None

    if request.method == 'POST':
        if 'arquivo_entrada' not in request.files: flash('Nenhum arquivo selecionado!', 'error'); return redirect(url_for('formatador_incorporacao_tool'))
        file = request.files['arquivo_entrada']
        if file.filename == '': flash('Nenhum arquivo selecionado!', 'error'); return redirect(url_for('formatador_incorporacao_tool'))
        if not file or not allowed_file(file.filename): flash('Tipo de arquivo inválido.', 'error'); return redirect(url_for('formatador_incorporacao_tool'))
        filename = secure_filename(f"{tool_prefix}{file.filename}"); temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename);
        try:
            file.save(temp_filepath); print(f"(Incorp) Arquivo salvo: {temp_filepath}")
            output_stream = processar_incorporacao_web(temp_filepath) # Chama a função de processamento
            input_basename = file.filename.rsplit('.', 1)[0]; output_filename = f"planilha_processada_{input_basename}.xlsx"
            print(f"(Incorp) Enviando: {output_filename}")
            return send_file(output_stream, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=output_filename)
        except Exception as e:
            flash(f"Erro Incorp: {e}", 'error'); print(f"(Incorp) Erro: {e}"); traceback.print_exc()
            # Limpeza em caso de erro ANTES do send_file
            if os.path.exists(temp_filepath):
                try: os.remove(temp_filepath)
                except OSError: pass
            if output_stream: output_stream.close() # Fecha o stream se deu erro ANTES do send_file
            return redirect(url_for('formatador_incorporacao_tool'))
        finally:
             # Limpeza do ARQUIVO temporário SEMPRE
             if temp_filepath and os.path.exists(temp_filepath):
                try: os.remove(temp_filepath); print(f"(Incorp) Temp removido: {temp_filepath}")
                except OSError as oe: print(f"(Incorp) Erro remover temp: {oe}")
            # NÃO FECHA output_stream aqui

    else: # GET
        return render_template('formatador_incorporacao.html', active_page='formatador_incorporacao')

# === ROTA PARA FORMATADOR LOTE ===
@app.route('/formatador-lote', methods=['GET', 'POST'])
def formatador_lote_tool():
    tool_prefix = 'fmt_lote_'
    temp_filepath = None # Definir fora do try
    output_stream = None

    if request.method == 'POST':
        if 'arquivo_entrada' not in request.files: flash('Nenhum arquivo selecionado!', 'error'); return redirect(url_for('formatador_lote_tool'))
        file = request.files['arquivo_entrada']
        if file.filename == '': flash('Nenhum arquivo selecionado!', 'error'); return redirect(url_for('formatador_lote_tool'))
        if not file or not allowed_file(file.filename): flash('Tipo de arquivo inválido.', 'error'); return redirect(url_for('formatador_lote_tool'))
        filename = secure_filename(f"{tool_prefix}{file.filename}"); temp_filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename);
        try:
            file.save(temp_filepath); print(f"(Fmt Lote) Arquivo salvo: {temp_filepath}")
            output_stream = processar_formatador_lote_web(temp_filepath) # Chama a função de processamento
            input_basename = file.filename.rsplit('.', 1)[0]; output_filename = f"{input_basename}_PROCESSADO.xlsx"
            print(f"(Fmt Lote) Enviando: {output_filename}")
            return send_file(output_stream, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=output_filename)
        except Exception as e:
            flash(f"Erro Fmt Lote: {e}", 'error'); print(f"(Fmt Lote) Erro: {e}"); traceback.print_exc()
             # Limpeza em caso de erro ANTES do send_file
            if os.path.exists(temp_filepath):
                try: os.remove(temp_filepath)
                except OSError: pass
            if output_stream: output_stream.close() # Fecha o stream se deu erro ANTES do send_file
            return redirect(url_for('formatador_lote_tool'))
        finally:
             # Limpeza do ARQUIVO temporário SEMPRE
             if temp_filepath and os.path.exists(temp_filepath):
                try: os.remove(temp_filepath); print(f"(Fmt Lote) Temp removido: {temp_filepath}")
                except OSError as oe: print(f"(Fmt Lote) Erro remover temp: {oe}")
            # NÃO FECHA output_stream aqui

    else: # GET
        return render_template('formatador_lote.html', active_page='formatador_lote')

# --- Roda a aplicação ---
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5001)