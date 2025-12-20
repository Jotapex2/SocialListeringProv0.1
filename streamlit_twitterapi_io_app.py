# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Optimizado por "JP" Persona - V8.0 (PRODUCTION HEAVY)
# UI: Español | Features: 
#   1. Stealth Credentials (.env priority)
#   2. Async DeepSeek Engine (Sentiment + Emotion + Executive Summary)
#   3. SMTP Email Reporting (Native Python) with Attachments (XLSX, CSV, PNGs)
#   4. Robust Fetching (Pagination for X, Polling for Apify, Token Rotation)
#   5. Crisis Detection Algorithm

import os
import re
import io
import time
import json
import pytz
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import asyncio
import httpx
import smtplib
import logging

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email import encoders

from wordcloud import WordCloud, STOPWORDS
from unidecode import unidecode
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from pandas.api.types import is_datetime64tz_dtype
from typing import Optional, List, Dict, Any, Union
from collections import Counter

# ============================================================================
# 1. CONFIGURACIÓN DEL SISTEMA Y LOGGING
# ============================================================================

st.set_page_config(
    page_title="SocialListening Pro Enterprise", 
    page_icon="📡", 
    layout="wide",
    initial_sidebar_state="expanded"
)

BUILD_TAG = "JP Release v8.0 - Production Heavy (Full Features)"
st.caption(f"Build: {BUILD_TAG}")

# Configuración de Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Constantes Globales
SCL_TZ = pytz.timezone("America/Santiago")
API_URL_X = "https://api.twitterapi.io/twitter/tweet/advanced_search"
ASYNC_POLL_INTERVAL = 3
MAX_RETRIES = 3

# Cargar variables de entorno
load_dotenv()

# ============================================================================
# 2. GESTIÓN DE ESTADO (SESSION STATE)
# ============================================================================

# Inicializamos todas las variables necesarias para persistencia
if "init_done" not in st.session_state:
    st.session_state.update({
        "df": None,
        "params": {},
        "query_str": None,
        "logs": [],
        "report_figures": {},     # Almacena los bytes de las imágenes para el correo
        "ai_summary": None,       # Almacena el resumen generado por IA
        "logged_in": False,
        "init_done": True
    })

def log_message(msg: str, level: str = "info"):
    """Registra mensajes en el log visual y en consola"""
    timestamp = datetime.now(SCL_TZ).strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    st.session_state["logs"].append(entry)
    if level == "error": logger.error(msg)
    elif level == "warning": logger.warning(msg)
    else: logger.info(msg)

def env(name: str) -> Optional[str]:
    """Helper para obtener secretos con fallback a os.getenv"""
    try: return st.secrets.get(name) or os.getenv(name)
    except: return os.getenv(name)

# ============================================================================
# 3. SEGURIDAD Y LOGIN
# ============================================================================

ADMIN_USER = env("ADMIN_USER") or "admin"
ADMIN_PASS = env("ADMIN_PASS") or "admin123"

def login_screen():
    st.title("🔐 Acceso Corporativo")
    st.markdown("Por favor ingrese sus credenciales para acceder al sistema.")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            user = st.text_input("Usuario")
            pwd = st.text_input("Contraseña", type="password")
            submitted = st.form_submit_button("Iniciar Sesión", use_container_width=True)
            
            if submitted:
                if user == ADMIN_USER and pwd == ADMIN_PASS:
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("Credenciales inválidas.")

if not st.session_state['logged_in']:
    login_screen()
    st.stop()

# ============================================================================
# 4. UTILIDADES DE EXPORTACIÓN Y GRÁFICOS
# ============================================================================

def fig_to_bytes(fig) -> bytes:
    """Convierte una figura de Matplotlib a bytes PNG para adjuntar al correo."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight', dpi=100)
    buf.seek(0)
    return buf.read()

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Convierte DataFrame a Excel en memoria."""
    bio = io.BytesIO()
    # Copia para evitar errores de timezone en Excel
    df_exp = df.copy()
    for c in df_exp.columns:
        if is_datetime64tz_dtype(df_exp[c]):
            df_exp[c] = df_exp[c].dt.tz_localize(None)
    
    with pd.ExcelWriter(bio, engine="xlsxwriter") as xw:
        df_exp.to_excel(xw, sheet_name="Data", index=False)
    bio.seek(0)
    return bio.read()

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convierte DataFrame a CSV UTF-8-SIG en memoria."""
    return df.to_csv(index=False).encode("utf-8-sig")

# ============================================================================
# 5. MÓDULO DE CORREO (SMTP)
# ============================================================================

def send_email_report(to_email: str, subject: str, body_text: str, df_xlsx: bytes, df_csv: bytes, figures_dict: Dict[str, bytes]) -> tuple[bool, str]:
    """
    Envía un correo electrónico completo con texto, Excel, CSV e imágenes adjuntas.
    """
    smtp_server = env("SMTP_HOST") or "smtp.gmail.com"
    smtp_port = int(env("SMTP_PORT") or 587)
    smtp_user = env("SMTP_USER")
    smtp_pass = env("SMTP_PASS")

    if not smtp_user or not smtp_pass:
        return False, "Credenciales SMTP no configuradas en .env o Secrets."

    try:
        msg = MIMEMultipart()
        msg['From'] = smtp_user
        msg['To'] = to_email
        msg['Subject'] = subject
        
        # Cuerpo del mensaje
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

        # Adjunto: Excel
        if df_xlsx:
            part = MIMEBase('application', "octet-stream")
            part.set_payload(df_xlsx)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment; filename="reporte_data.xlsx"')
            msg.attach(part)

        # Adjunto: CSV
        if df_csv:
            part = MIMEBase('application', "octet-stream")
            part.set_payload(df_csv)
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', 'attachment; filename="reporte_data.csv"')
            msg.attach(part)

        # Adjuntos: Imágenes
        for name, img_bytes in figures_dict.items():
            image = MIMEImage(img_bytes, name=f"{name}.png")
            image.add_header('Content-Disposition', f'attachment; filename="{name}.png"')
            msg.attach(image)

        # Conexión SMTP
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
        server.quit()
        
        return True, "Correo enviado exitosamente."

    except Exception as e:
        logger.error(f"Error SMTP: {e}")
        return False, f"Error al enviar correo: {str(e)}"

# ============================================================================
# 6. MOTOR DE INTELIGENCIA ARTIFICIAL (DEEPSEEK)
# ============================================================================

async def async_fetch_deepseek(client: httpx.AsyncClient, prompt: str, sem: asyncio.Semaphore, max_tokens: int = 10) -> str:
    """Llamada asíncrona unitaria a DeepSeek."""
    deepseek_key = env("DEEPSEEK_API_KEY")
    if not deepseek_key: return "NEU"
    
    async with sem:
        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": max_tokens
                },
                headers={
                    "Authorization": f"Bearer {deepseek_key}",
                    "Content-Type": "application/json"
                }, 
                timeout=45.0
            )
            
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content'].strip().upper()
                return re.sub(r'[^\w]', '', content) # Limpieza estricta
            elif response.status_code == 429:
                return "NEU" # Rate Limit
            else:
                return "NEU"
        except Exception:
            return "NEU"

async def process_batch_analysis(texts: List[str], analysis_type: str = "sentiment") -> List[str]:
    """Procesador por lotes asíncrono para Sentimiento o Emociones."""
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    sem = asyncio.Semaphore(10) # Control de concurrencia
    
    async with httpx.AsyncClient(base_url="https://api.deepseek.com", limits=limits, timeout=60.0) as client:
        tasks = []
        for text in texts:
            safe_text = text[:300].replace("\n", " ") if text else ""
            
            if analysis_type == "sentiment":
                prompt = f"Clasifica el sentimiento: '{safe_text}'. Responde EXCLUSIVAMENTE con una palabra: POS, NEG o NEU."
                tasks.append(async_fetch_deepseek(client, prompt, sem, 5))
            else:
                valid_emotions = "RISA, IRA, MIEDO, TRISTEZA, DISGUSTO, SORPRESA, NEUTRAL"
                prompt = f"Detecta la emoción: '{safe_text}'. Opciones: {valid_emotions}. Responde SOLO con la palabra clave."
                tasks.append(async_fetch_deepseek(client, prompt, sem, 10))
        
        raw_results = await asyncio.gather(*tasks)
        
        # Post-procesamiento y validación
        clean_results = []
        for r in raw_results:
            if analysis_type == "sentiment":
                if r in ["POS", "NEG", "NEU"]: clean_results.append(r)
                elif "POS" in r: clean_results.append("POS")
                elif "NEG" in r: clean_results.append("NEG")
                else: clean_results.append("NEU")
            else:
                valid = ["RISA", "IRA", "MIEDO", "TRISTEZA", "DISGUSTO", "SORPRESA", "NEUTRAL"]
                found = next((v for v in valid if v in r), "NEUTRAL")
                clean_results.append(found)
                
        return clean_results

def analyze_sentiment(texts: List[str]) -> List[str]:
    if not texts: return []
    return asyncio.run(process_batch_analysis(texts, "sentiment"))

def analyze_emotions(texts: List[str]) -> List[str]:
    if not texts: return []
    return asyncio.run(process_batch_analysis(texts, "emotions"))

def generate_executive_summary(df: pd.DataFrame, query: str) -> str:
    """
    Genera un resumen narrativo de alto nivel utilizando DeepSeek (Modo Síncrono).
    """
    key = env("DEEPSEEK_API_KEY")
    if not key or df.empty: return "Resumen no disponible (Falta API Key o Datos)."
    
    # Preparar contexto estadístico
    total = len(df)
    sent_counts = df["sentiment"].value_counts(normalize=True).to_dict() if "sentiment" in df.columns else {}
    emo_counts = df["emotion"].value_counts().head(3).to_dict() if "emotion" in df.columns else {}
    
    # Extraer posts más virales
    df["engagement"] = df["likes"] + df["comments"] + df["shares"]
    top_posts = df.sort_values("engagement", ascending=False).head(3)
    top_texts = [f"- '{row['text'][:100]}...' (Eng: {int(row['engagement'])})" for _, row in top_posts.iterrows()]
    
    context = (
        f"Análisis para la búsqueda: '{query}'.\n"
        f"Total Posts Analizados: {total}.\n"
        f"Distribución Sentimiento: {sent_counts}.\n"
        f"Emociones Principales: {emo_counts}.\n"
        f"Posts con mayor engagement:\n" + "\n".join(top_texts)
    )

    prompt = (
        f"Actúa como un analista senior de inteligencia de redes sociales. "
        f"Escribe un 'Resumen Ejecutivo' de un solo párrafo (máximo 80 palabras) en español basado en los siguientes datos:\n\n"
        f"{context}\n\n"
        f"El tono debe ser profesional y directo. Menciona la tendencia general, si hay riesgo reputacional y qué está impulsando la conversación."
    )

    try:
        response = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3, # Baja temperatura para ser factual
                "max_tokens": 200
            }, 
            timeout=25
        )
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content'].strip()
        else:
            logger.error(f"Error DeepSeek Summary: {response.text}")
            return "No se pudo generar el resumen automáticamente."
    except Exception as e:
        logger.error(f"Exception DeepSeek Summary: {e}")
        return f"Error en generación de resumen: {str(e)}"

# ============================================================================
# 7. FETCHERS Y NORMALIZACIÓN (LÓGICA NÚCLEO)
# ============================================================================

def normalize_data_universal(rows: List[Dict], platform: str) -> pd.DataFrame:
    """Normaliza datos de cualquier fuente a un esquema común."""
    df = pd.DataFrame(rows)
    if df.empty: return df

    # Mapa de columnas extendido para cubrir X, FB, IG, TikTok
    col_map = {
        "text": ["caption", "description", "title", "text", "message", "postText", "full_text"],
        "likes": ["likeCount", "likesCount", "diggCount", "likes", "reactionCount", "favorite_count"],
        "comments": ["commentCount", "commentsCount", "comments", "reply_count"],
        "shares": ["shareCount", "retweetCount", "shares", "repost_count"],
        "views": ["playCount", "viewCount", "videoPlayCount", "views", "impression_count"],
        "followers": ["followers", "followersCount", "fans", "followerCount", "userFollowers"],
        "created_at": ["timestamp", "takenAt", "createTimeISO", "createdAt", "date", "time", "created_at"]
    }

    # 1. Renombrado inteligente
    for target, candidates in col_map.items():
        if target not in df.columns:
            for c in candidates:
                if c in df.columns: 
                    df[target] = df[c]
                    break
            # Si no se encuentra, rellenar con default
            if target not in df.columns: 
                df[target] = 0 if target in ["likes", "comments", "shares", "views", "followers"] else None

    # 2. Manejo de Fechas (Timezone Aware)
    if "created_at" in df.columns:
        # Forzar conversión a UTC primero
        df["created_at_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        # Convertir a Santiago
        df["created_at_cl"] = df["created_at_utc"].dt.tz_convert(SCL_TZ)
        df["fecha_cl"] = df["created_at_cl"].dt.date
    
    # 3. Extracción de Usuario (Manejo de diccionarios anidados)
    if "username" not in df.columns:
        for c in ["ownerUsername", "authorUsername", "username", "author", "pageName", "user"]:
            if c in df.columns:
                # Si la celda es un dict (ej: {'id': '...', 'name': 'JP'}), extraer 'name' o 'username'
                df["username"] = df[c].apply(lambda x: x.get('username') or x.get('name') if isinstance(x, dict) else x)
                break
    
    # 4. Limpieza final de Tipos
    if "text" in df.columns: 
        df["text"] = df["text"].fillna("").astype(str)
    
    for col in ["likes", "comments", "shares", "views", "followers"]:
        if col in df.columns: 
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["platform"] = platform
    return df

# --- Fetcher X (TwitterAPI.io) con Paginación ---
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_x_robust(api_key: str, query: str, limit: int) -> pd.DataFrame:
    headers = {"x-api-key": api_key}
    all_rows = []
    cursor = None
    
    # Cálculo de páginas necesarias (aprox 20 tweets por página)
    max_loops = (limit // 20) + 5 
    
    for i in range(max_loops):
        try:
            params = {"query": query, "queryType": "Latest"}
            if cursor: params["cursor"] = cursor
            
            r = requests.get(API_URL_X, headers=headers, params=params, timeout=25)
            
            if r.status_code == 429: # Rate limit manual handling
                time.sleep(5)
                continue
            if r.status_code != 200: 
                log_message(f"Error X API: {r.status_code}", "error")
                break
                
            data = r.json()
            tweets = data.get("tweets", [])
            
            if not tweets: break
            
            for t in tweets:
                u = t.get("author", {})
                all_rows.append({
                    "id": t.get("id"), 
                    "created_at": t.get("createdAt"),
                    "username": u.get("userName"), 
                    "text": t.get("text"),
                    "likes": t.get("likeCount", 0), 
                    "comments": t.get("replyCount", 0),
                    "shares": t.get("retweetCount", 0), 
                    "views": t.get("viewCount", 0),
                    "followers": u.get("followers") or u.get("followersCount") or 0,
                    "url": t.get("url"),
                })
            
            if len(all_rows) >= limit: break
            
            # Paginación
            cursor = data.get("next_cursor")
            if not data.get("has_next_page") or not cursor: break
            
        except Exception as e:
            log_message(f"Excepción Fetch X loop {i}: {e}", "error")
            break
            
    return normalize_data_universal(all_rows, "x")

# --- Fetcher Apify (Genérico con Polling y Rotación de Tokens) ---
def run_apify_actor_robust(actor_id: str, tokens: List[str], payload: Dict) -> List[Dict]:
    valid_tokens = [t for t in tokens if t and t.strip()]
    if not valid_tokens: return []

    # Intentar con cada token hasta que uno funcione
    for token in valid_tokens:
        url_run = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/runs"
        try:
            # 1. Iniciar ejecución
            r = requests.post(url_run, params={"token": token}, json=payload, timeout=30)
            
            if r.status_code == 201:
                run_data = r.json()["data"]
                run_id = run_data["id"]
                dataset_id = run_data["defaultDatasetId"]
                
                # 2. Polling (Esperar resultados)
                start_time = time.time()
                while time.time() - start_time < 300: # Timeout 5 min
                    time.sleep(ASYNC_POLL_INTERVAL)
                    try:
                        poll = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}", params={"token": token}, timeout=10)
                        status = poll.json()["data"]["status"]
                        
                        if status == "SUCCEEDED":
                            # 3. Obtener dataset
                            data_url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
                            d_r = requests.get(data_url, params={"token": token, "clean": "1", "format": "json"}, timeout=60)
                            return d_r.json() if d_r.status_code == 200 else []
                        
                        elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                            log_message(f"Actor {actor_id} falló con estado: {status}", "warning")
                            break # Salir del while para probar siguiente token
                            
                    except Exception: continue
            else:
                log_message(f"Error inicio Actor {r.status_code}", "warning")
                continue # Probar siguiente token

        except Exception as e:
            log_message(f"Excepción Apify: {e}", "error")
            continue
            
    return []

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_facebook_robust(tokens, query, limit, mode):
    payload = {"resultsLimit": limit, "maxPosts": limit}
    actor = "apify/facebook-posts-scraper"
    
    if mode == "user":
        # Manejo robusto de URLs de usuarios
        urls = []
        for u in query.split(","):
            u = u.strip()
            if "facebook.com" in u: urls.append({"url": u})
            else: urls.append({"url": f"https://www.facebook.com/{u}"})
        payload["startUrls"] = urls
    else:
        # Búsqueda general
        payload["startUrls"] = [{"url": f"https://www.facebook.com/search/posts?q={query}&filters=eyJzb3J0X2tleSI6InRECENT_POSTS_V2In0%3D"}]
        
    raw_data = run_apify_actor_robust(actor, tokens, payload)
    return normalize_data_universal(raw_data, "facebook")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_instagram_robust(tokens, query, limit, mode):
    payload = {"resultsLimit": limit, "resultsType": "posts"}
    
    if mode == "hashtag":
        actor = "apify/instagram-hashtag-scraper"
        payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
    elif mode == "keyword":
        actor = "apify/instagram-scraper"
        payload["search"] = query
        payload["searchType"] = "hashtag"
    else: # User
        actor = "apify/instagram-post-scraper"
        payload["usernames"] = [u.strip() for u in query.split(",")]
        
    raw_data = run_apify_actor_robust(actor, tokens, payload)
    return normalize_data_universal(raw_data, "instagram")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tiktok_robust(tokens, query, limit, mode):
    payload = {"resultsPerPage": 100, "limit": limit, "shouldDownloadVideos": False}
    actor = "clockworks/tiktok-scraper"
    
    if mode == "user":
        payload["usernames"] = [u.strip() for u in query.split(",")]
    else:
        payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
        
    raw_data = run_apify_actor_robust(actor, tokens, payload)
    return normalize_data_universal(raw_data, "tiktok")

# ============================================================================
# 8. PREPARACIÓN DE QUERIES & FILTROS
# ============================================================================

def build_x_query(topic, lang, exclude_rt, exclude_repl, d1, d2, filter_chile):
    """Construye query avanzada para Twitter API."""
    q = topic.strip()
    if not q.startswith("(") and " " in q: q = f"({q})"
    
    parts = [q]
    if lang: parts.append(f"lang:{lang}")
    if exclude_rt: parts.append("-is:retweet")
    if exclude_repl: parts.append("-is:reply")
    if filter_chile: parts.append("place_country:CL")
    if d1: parts.append(f"since:{d1.isoformat()}_00:00:00_UTC")
    if d2: parts.append(f"until:{(d2 + timedelta(days=1)).isoformat()}_00:00:00_UTC")
    
    return " ".join(parts)

def build_x_user_query(username, lang, exclude_rt, exclude_repl, d1, d2, filter_chile):
    u = username.strip().lstrip("@")
    q = f"from:{u}"
    
    parts = [q]
    if lang: parts.append(f"lang:{lang}")
    if exclude_rt: parts.append("-is:retweet")
    if exclude_repl: parts.append("-is:reply")
    if filter_chile: parts.append("place_country:CL")
    if d1: parts.append(f"since:{d1.isoformat()}_00:00:00_UTC")
    if d2: parts.append(f"until:{(d2 + timedelta(days=1)).isoformat()}_00:00:00_UTC")
    
    return " ".join(parts)

def clean_and_tokenize(texts: pd.Series) -> str:
    """Limpieza profunda de textos para Nube de Palabras."""
    blob = []
    # Stopwords extendidas en Español
    EXTRA_STOP = {"rt","https","http","t","co","amp","si","no","de","la","que","el","en","y","a","los","del","se","las","por","un","para","con","una","su","al","lo","como","mas","pero","sus","le","ya","o","fue","ha","porque","cuando","muy","sin","sobre","tambien","me","mis","nos","tu","te","eso","este","esta"}
    STOP = STOPWORDS.union(EXTRA_STOP)
    
    for s in texts.fillna("").astype(str):
        # 1. Minúsculas
        s = s.lower()
        # 2. Quitar URLs
        s = re.sub(r"http\S+|www\.\S+", " ", s)
        # 3. Quitar menciones y hashtags
        s = re.sub(r"@\w+|#", " ", s)
        # 4. Quitar acentos (unidecode)
        s = unidecode(s)
        # 5. Quitar no alfanuméricos
        s = re.sub(r"[^a-z\s]", " ", s)
        
        words = [w for w in s.split() if w not in STOP and len(w) > 2]
        blob.extend(words)
        
    return " ".join(blob)

def detect_crisis_signals(df: pd.DataFrame) -> Dict[str, Any]:
    """Algoritmo de detección de crisis basado en keywords, sentimiento y engagement."""
    if df.empty: return {"score": 0, "severity": "none", "signals": []}
    
    signals = []
    score = 0
    keywords = ["crisis", "emergencia", "caída", "fallo", "problema", "error", "incidente", "demanda", "denuncia", "escándalo", "fraude", "robo", "ataque", "funao", "funa"]
    
    # 1. Sentimiento Negativo Masivo
    if "sentiment" in df.columns:
        neg_pct = (df["sentiment"] == "NEG").sum() / len(df)
        if neg_pct > 0.35:
            score += 30
            signals.append(f"Sentimiento negativo dominante ({neg_pct*100:.1f}%)")
    
    # 2. Keywords Críticas
    if "text" in df.columns:
        pattern = "|".join(keywords)
        crit_posts = df[df["text"].str.lower().str.contains(pattern, regex=True, na=False)]
        count = len(crit_posts)
        
        if count > 0:
            added = min(40, count * 5) # Max 40 puntos por keywords
            score += added
            signals.append(f"{count} posts contienen palabras de riesgo")
            
            # 3. Amplificación por Influencers (si aplica)
            if "followers" in df.columns:
                influencers = crit_posts[crit_posts["followers"] > 50000] # Influencer > 50k
                if not influencers.empty:
                    score += 20
                    signals.append(f"⚠️ {len(influencers)} Influencers/Medios hablando del tema")

    score = min(100, score)
    sev = "critical" if score >= 80 else "high" if score >= 60 else "medium" if score >= 30 else "low"
    
    return {"score": score, "severity": sev, "signals": signals}

# ============================================================================
# 9. INTERFAZ DE USUARIO (SIDEBAR COMPLETO)
# ============================================================================

st.sidebar.header("⚙️ Panel de Control")

# Selector de Plataforma
platform = st.sidebar.selectbox("Plataforma", ["X (Twitter)", "Instagram", "Facebook", "TikTok"])

# Selector de Modo (Condicional complejo)
username_input, topic, hashtags_str = "", "", ""

if platform == "Instagram":
    search_mode = st.sidebar.radio("Modo de búsqueda", ["Por temática (hashtags)", "Por temática (búsqueda IG)", "Por usuario/perfil"])
    if "hashtags" in search_mode:
        hashtags_str = st.sidebar.text_input("Hashtag(s)", help="Sin #, separados por coma")
    elif "búsqueda" in search_mode:
        topic = st.sidebar.text_input("Palabra clave")
    else:
        username_input = st.sidebar.text_input("Usuario(s)", help="Separar por coma")
        
elif platform == "Facebook":
    search_mode = st.sidebar.radio("Modo de búsqueda", ["Por temática", "Por usuario/perfil"])
    if "temática" in search_mode:
        topic = st.sidebar.text_input("Tema / Consulta")
    else:
        username_input = st.sidebar.text_input("Usuario(s) / URL(s)")

elif platform == "TikTok":
    search_mode = st.sidebar.radio("Modo de búsqueda", ["Por temática (hashtag)", "Por usuario"])
    if "temática" in search_mode:
        hashtags_str = st.sidebar.text_input("Hashtag(s)")
    else:
        username_input = st.sidebar.text_input("Usuario(s)")

else: # X (Twitter)
    search_mode = st.sidebar.radio("Modo de búsqueda", ["Por temática", "Por usuario"])
    if "temática" in search_mode:
        topic = st.sidebar.text_input("Query Avanzada")
    else:
        username_input = st.sidebar.text_input("Usuario(s) (@)")

# Filtros Específicos X (Restaurados)
lang = "es"
exclude_rt, exclude_repl, filter_chile = True, True, False

if platform.startswith("X"):
    with st.sidebar.expander("Filtros Avanzados (X)", expanded=True):
        lang = st.selectbox("Idioma", ["", "es", "en", "pt"], index=1)
        c1, c2 = st.columns(2)
        exclude_rt = c1.checkbox("Excluir RTs", value=True)
        exclude_repl = c2.checkbox("Excluir Respuestas", value=True)
        filter_chile = st.checkbox("🇨🇱 Solo Chile (Geo)", value=False)

st.sidebar.markdown("---")

# Filtros Globales
col_d1, col_d2 = st.sidebar.columns(2)
d1 = col_d1.date_input("Desde", datetime.now() - timedelta(days=7))
d2 = col_d2.date_input("Hasta", datetime.now())

limit = st.sidebar.slider("Límite de resultados", 50, 5000, 200, step=50)
max_words = st.sidebar.slider("Máx. palabras Nube", 50, 500, 200)

st.sidebar.markdown("---")
sentiment_on = st.sidebar.checkbox("🧠 Análisis Sentimiento", True)
emotions_on = st.sidebar.checkbox("🎭 Análisis Emociones", False)

st.sidebar.markdown("---")
run_btn = st.sidebar.button("🚀 Ejecutar Búsqueda", type="primary", use_container_width=True)

# Credenciales (Stealth)
st.sidebar.markdown("### 🔐 Credenciales")
api_x = env("TWITTERAPI_IO_KEY")
if not api_x: api_x = st.sidebar.text_input("API Key X", type="password")

api_apify = env("APIFY_TOKEN")
if not api_apify: api_apify = st.sidebar.text_input("Token Apify", type="password")

# ============================================================================
# 10. ORQUESTACIÓN PRINCIPAL (MAIN LOOP)
# ============================================================================

if run_btn:
    # Reiniciar estado
    st.session_state["report_figures"] = {}
    st.session_state["ai_summary"] = None
    st.session_state["df"] = pd.DataFrame()
    st.session_state["logs"] = []
    
    # Contenedor de estado visual
    status_container = st.status("Iniciando motor de búsqueda...", expanded=True)
    
    try:
        df_result = pd.DataFrame()
        tokens_list = [t.strip() for t in api_apify.split(",") if t.strip()] if api_apify else []
        
        # ---------------------------------------------------------
        # FASE 1: FETCHING
        # ---------------------------------------------------------
        status_container.write("📡 Conectando a APIs externas...")
        
        if platform.startswith("X"):
            if not api_x: 
                status_container.update(label="Error: Falta API Key X", state="error")
                st.stop()
            
            if "usuario" in search_mode:
                final_q = build_x_user_query(username_input, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            else:
                final_q = build_x_query(topic, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            
            log_message(f"Query X: {final_q}")
            df_result = fetch_x_robust(api_x, final_q, limit)

        elif platform == "Facebook":
            if not tokens_list: 
                status_container.update(label="Error: Falta Token Apify", state="error"); st.stop()
            
            mode_fb = "user" if "usuario" in search_mode else "search"
            q_fb = username_input if mode_fb == "user" else topic
            df_result = fetch_facebook_robust(tokens_list, q_fb, limit, mode_fb)

        elif platform == "Instagram":
            if not tokens_list: 
                status_container.update(label="Error: Falta Token Apify", state="error"); st.stop()
            
            mode_ig = "hashtag" if "hashtags" in search_mode else ("keyword" if "búsqueda" in search_mode else "user")
            q_ig = hashtags_str if mode_ig == "hashtag" else (username_input if mode_ig == "user" else topic)
            df_result = fetch_instagram_robust(tokens_list, q_ig, limit, mode_ig)

        elif platform == "TikTok":
            if not tokens_list: 
                status_container.update(label="Error: Falta Token Apify", state="error"); st.stop()
            
            mode_tt = "user" if "usuario" in search_mode else "hashtag"
            q_tt = username_input if mode_tt == "user" else hashtags_str
            df_result = fetch_tiktok_robust(tokens_list, q_tt, limit, mode_tt)
            
        # ---------------------------------------------------------
        # FASE 2: FILTRADO LOCAL (FECHAS PRECISAS)
        # ---------------------------------------------------------
        if not df_result.empty and "created_at_cl" in df_result.columns:
            status_container.write("📅 Filtrando por rango de fechas...")
            
            mask = pd.Series(True, index=df_result.index)
            ts = df_result["created_at_cl"].dt.normalize()
            
            # timezone handling para filtros
            tz_d1 = pd.Timestamp(d1).tz_localize(SCL_TZ, nonexistent="shift_forward")
            tz_d2 = pd.Timestamp(d2).tz_localize(SCL_TZ, nonexistent="shift_forward")
            
            if d1: mask &= ((ts >= tz_d1) | ts.isna())
            if d2: mask &= ((ts <= tz_d2) | ts.isna())
            
            df_result = df_result.loc[mask].copy()
            log_message(f"Filtrado: {len(df_result)} registros remanentes")

        if df_result.empty:
            status_container.update(label="No se encontraron resultados", state="error")
            st.warning("La búsqueda no retornó datos. Intenta ampliar el rango de fechas o cambiar los términos.")
            st.stop()

        # ---------------------------------------------------------
        # FASE 3: ENRIQUECIMIENTO IA (DEEPSEEK)
        # ---------------------------------------------------------
        status_container.write("🧠 Ejecutando modelos cognitivos (Sentiment & Emotion)...")
        
        if "text" in df_result.columns:
            texts = df_result["text"].tolist()
            
            if sentiment_on:
                df_result["sentiment"] = analyze_sentiment(texts)
            
            if emotions_on:
                df_result["emotion"] = analyze_emotions(texts)
                
            # Generación de Resumen Ejecutivo
            status_container.write("📝 Redactando Resumen Ejecutivo...")
            search_term = topic or username_input or hashtags_str
            summary = generate_executive_summary(df_result, search_term)
            st.session_state["ai_summary"] = summary

        # Guardar en Session State
        st.session_state["df"] = df_result
        status_container.update(label="¡Proceso Finalizado!", state="complete")

    except Exception as e:
        status_container.update(label="Error Crítico", state="error")
        st.error(f"Se produjo un error durante la ejecución: {str(e)}")
        logger.error(f"Crash report: {e}", exc_info=True)

# ============================================================================
# 11. DASHBOARD DE RESULTADOS (VISUALIZACIÓN)
# ============================================================================

df = st.session_state.get("df")
ai_summary = st.session_state.get("ai_summary")

if df is not None and not df.empty:
    
    st.divider()
    
    # 1. Bloque de Inteligencia
    st.subheader("🤖 Análisis de Inteligencia")
    
    if ai_summary:
        st.info(f"**Resumen Ejecutivo (AI Analyst):**\n\n{ai_summary}", icon="ℹ️")
        
    # Crisis Check
    crisis_data = detect_crisis_signals(df)
    if crisis_data["score"] > 0:
        sev_color = {"critical":"🔴", "high":"🟠", "medium":"🟡", "low":"🟢"}[crisis_data["severity"]]
        with st.expander(f"{sev_color} **ALERTA DE CRISIS DETECTADA (Score: {crisis_data['score']})**", expanded=True):
            for signal in crisis_data["signals"]:
                st.write(f"- {signal}")

    # 2. KPIs Generales
    st.markdown("### 📈 Métricas Clave")
    k1, k2, k3, k4, k5 = st.columns(5)
    
    k1.metric("Total Posts", f"{len(df):,}")
    k2.metric("Likes Totales", f"{int(df['likes'].sum()):,}")
    k3.metric("Comentarios", f"{int(df['comments'].sum()):,}")
    k4.metric("Compartidos", f"{int(df['shares'].sum()):,}")
    
    pos_rate = (df['sentiment']=='POS').mean() if "sentiment" in df.columns else 0
    k5.metric("Tasa Positividad", f"{pos_rate:.1%}")

    # 3. Visualizaciones Avanzadas (Con captura para Email)
    st.subheader("📊 Visualizaciones")
    
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Tendencia Temporal", "Sentimiento", "Emociones", "Temas Clave", "Nube de Palabras"])
    
    figures_capture = {} # Diccionario para guardar imágenes
    
    # --- Tab 1: Tendencia ---
    with tab1:
        if "fecha_cl" in df.columns:
            daily_counts = df["fecha_cl"].value_counts().sort_index()
            fig1, ax1 = plt.subplots(figsize=(10, 4))
            daily_counts.plot(kind='bar', ax=ax1, color='#3498db', edgecolor='black')
            ax1.set_title("Volumen de Publicaciones por Día")
            ax1.set_ylabel("Cantidad")
            ax1.grid(axis='y', linestyle='--', alpha=0.5)
            plt.xticks(rotation=45)
            st.pyplot(fig1)
            figures_capture["tendencia_temporal"] = fig_to_bytes(fig1)
            plt.close(fig1)
        else:
            st.warning("No hay datos de fecha disponibles.")

    # --- Tab 2: Sentimiento ---
    with tab2:
        if "sentiment" in df.columns:
            c_pie, c_bar = st.columns(2)
            with c_pie:
                counts = df["sentiment"].value_counts()
                fig2, ax2 = plt.subplots()
                colors = {'POS': '#2ecc71', 'NEG': '#e74c3c', 'NEU': '#95a5a6'}
                ax2.pie(counts, labels=counts.index, autopct='%1.1f%%', startangle=90, colors=[colors.get(x, '#333') for x in counts.index])
                ax2.set_title("Distribución de Sentimiento")
                st.pyplot(fig2)
                figures_capture["sentimiento_pie"] = fig_to_bytes(fig2)
                plt.close(fig2)
            
            with c_bar:
                fig3, ax3 = plt.subplots()
                counts.plot(kind='bar', ax=ax3, color=[colors.get(x, '#333') for x in counts.index])
                ax3.set_title("Conteo por Sentimiento")
                st.pyplot(fig3)
                figures_capture["sentimiento_bar"] = fig_to_bytes(fig3)
                plt.close(fig3)
        else:
            st.info("Análisis de sentimiento no activado.")

    # --- Tab 3: Emociones ---
    with tab3:
        if "emotion" in df.columns:
            fig4, ax4 = plt.subplots(figsize=(8, 4))
            df["emotion"].value_counts().plot(kind='bar', ax=ax4, color='#9b59b6')
            ax4.set_title("Análisis Emocional (Ekman)")
            plt.xticks(rotation=45)
            st.pyplot(fig4)
            figures_capture["emociones_bar"] = fig_to_bytes(fig4)
            plt.close(fig4)
        else:
            st.info("Análisis de emociones no activado.")

    # --- Tab 4: Temas ---
    with tab4:
        if "text" in df.columns:
            from collections import Counter
            blob_clean = clean_and_tokenize(df["text"])
            if blob_clean:
                common_words = Counter(blob_clean.split()).most_common(15)
                words, freqs = zip(*common_words)
                fig5, ax5 = plt.subplots(figsize=(10, 5))
                ax5.barh(words, freqs, color='#e67e22')
                ax5.invert_yaxis()
                ax5.set_title("Top 15 Términos Recurrentes")
                st.pyplot(fig5)
                figures_capture["top_temas"] = fig_to_bytes(fig5)
                plt.close(fig5)
            else:
                st.warning("No hay suficiente texto para analizar.")

    # --- Tab 5: Wordcloud ---
    with tab5:
        if "text" in df.columns and blob_clean:
            wc = WordCloud(width=800, height=400, background_color="white", max_words=max_words, colormap="viridis").generate(blob_clean)
            fig6, ax6 = plt.subplots(figsize=(12, 6))
            ax6.imshow(wc, interpolation='bilinear')
            ax6.axis("off")
            st.pyplot(fig6)
            figures_capture["nube_palabras"] = fig_to_bytes(fig6)
            plt.close(fig6)

    # Actualizar estado con las figuras generadas para el envío
    st.session_state["report_figures"] = figures_capture

    # 4. Tabla de Datos
    st.markdown("### 📋 Datos Detallados")
    st.dataframe(df, use_container_width=True, height=400)

    # ============================================================================
    # 12. SECCIÓN DE ENVÍO DE CORREO
    # ============================================================================
    st.markdown("---")
    st.header("📧 Enviar Reporte Ejecutivo")
    
    with st.container(border=True):
        col_email_1, col_email_2 = st.columns([3, 1])
        with col_email_1:
            recipient = st.text_input("Destinatario(s)", placeholder="ejemplo@empresa.com, jefe@empresa.com")
        with col_email_2:
            st.write("") # Spacer
            st.write("")
            send_email_btn = st.button("📤 Enviar Ahora", use_container_width=True)

        if send_email_btn:
            if not recipient:
                st.error("Por favor ingrese al menos un correo destinatario.")
            else:
                with st.spinner("Generando adjuntos y enviando correo..."):
                    # Preparar Datos
                    excel_data = df_to_excel_bytes(df)
                    csv_data = df_to_csv_bytes(df)
                    
                    # Preparar Cuerpo
                    body_html = (
                        f"REPORTE SOCIAL LISTENING PRO\n"
                        f"============================\n"
                        f"Fecha: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                        f"Plataforma: {platform}\n"
                        f"Búsqueda: {topic or username_input or hashtags_str}\n\n"
                        f"RESUMEN EJECUTIVO (IA):\n"
                        f"{ai_summary if ai_summary else 'No disponible.'}\n\n"
                        f"MÉTRICAS CLAVE:\n"
                        f"- Total Publicaciones: {len(df)}\n"
                        f"- Engagement Total: {int(df['likes'].sum() + df['comments'].sum())}\n"
                        f"- Alerta Crisis: {crisis_data['severity'].upper()}\n\n"
                        f"Se adjuntan los datos crudos (Excel/CSV) y los gráficos del dashboard.\n\n"
                        f"Atte,\nTu Asistente de IA."
                    )
                    
                    # Enviar
                    success, message = send_email_report(
                        recipient, 
                        f"Reporte Ejecutivo: {platform} - {date.today()}",
                        body_html,
                        excel_data,
                        csv_data,
                        st.session_state["report_figures"]
                    )
                    
                    if success:
                        st.success(f"✅ {message}")
                        st.balloons()
                    else:
                        st.error(f"❌ {message}")
