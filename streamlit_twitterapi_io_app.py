# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Optimizado por "JP" Persona - V6.8.0 (Enhanced with AI Summary + DEBUG MODE)
# UI: Español | Feat: Stealth Credentials + Email Reporting + AI Analyst (Specific Citations) + Debug Tools


import os, re, io, time, json, pytz, requests, pandas as pd, streamlit as st
import matplotlib.pyplot as plt
import asyncio
import httpx
import smtplib
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
from typing import Optional, List, Dict, Any
from collections import Counter
import logging
import traceback


# ============================================================================
# CONFIGURACIÓN INICIAL & LOGGING
# ============================================================================


st.set_page_config(page_title="SocialListening Pro", page_icon="📡", layout="wide")


BUILD_TAG = "JP Release v6.8.0 - AI Summary, Citations & DEBUG MODE"
st.caption(f"Build: {BUILD_TAG}")


# Configuración de logging mejorado
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


# Constantes
SCL_TZ = pytz.timezone("America/Santiago")
API_URL_X = "https://api.twitterapi.io/twitter/tweet/advanced_search"
ASYNC_POLL_INTERVAL = 3


load_dotenv()


# ============================================================================
# SESSION STATE & UTILS (ENHANCED WITH DEBUG)
# ============================================================================


# Agregamos 'debug_logs' y 'debug_mode' al estado
default_state = {
    "df": None, 
    "params": {}, 
    "query_str": None, 
    "logs": [], 
    "report_figures": {}, 
    "ai_summary": None,
    "debug_mode": False,
    "debug_logs": [],
    "api_responses": {},
    "execution_times": {}
}

for k, v in default_state.items():
    if k not in st.session_state:
        st.session_state[k] = v


def env(name: str) -> Optional[str]:
    try: return st.secrets.get(name) or os.getenv(name)
    except: return os.getenv(name)


def log_message(msg: str, level: str = "info", debug_data: Optional[Dict] = None):
    """Sistema de logging mejorado con soporte para debug"""
    timestamp = datetime.now(SCL_TZ).strftime("%H:%M:%S.%f")[:-3]
    log_entry = f"[{timestamp}] {msg}"
    
    # Log normal
    st.session_state["logs"].append(log_entry)
    
    # Log debug con datos adicionales
    if st.session_state.get("debug_mode", False):
        debug_entry = {
            "timestamp": timestamp,
            "level": level.upper(),
            "message": msg,
            "data": debug_data or {}
        }
        st.session_state["debug_logs"].append(debug_entry)
    
    # Logging tradicional
    if level == "error": 
        logger.error(msg)
        if debug_data:
            logger.debug(f"Error data: {json.dumps(debug_data, indent=2, default=str)}")
    elif level == "warning": 
        logger.warning(msg)
    elif level == "debug":
        logger.debug(msg)
    else: 
        logger.info(msg)


def measure_time(func_name: str):
    """Decorador para medir tiempos de ejecución"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                if st.session_state.get("debug_mode"):
                    st.session_state["execution_times"][func_name] = elapsed
                    log_message(f"⏱️ {func_name} ejecutado en {elapsed:.2f}s", "debug")
                return result
            except Exception as e:
                elapsed = time.time() - start
                log_message(f"❌ {func_name} falló después de {elapsed:.2f}s: {str(e)}", "error", 
                           {"exception": str(e), "traceback": traceback.format_exc()})
                raise
        return wrapper
    return decorator


# ============================================================================
# DEBUG PANEL (NUEVO)
# ============================================================================


def render_debug_panel():
    """Panel de depuración avanzado"""
    if not st.session_state.get("debug_mode"):
        return
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("🐛 Debug Tools")
    
    debug_tabs = st.sidebar.tabs(["📋 Logs", "⏱️ Tiempos", "🔍 Datos", "📡 APIs"])
    
    with debug_tabs[0]:
        if st.button("🗑️ Limpiar Logs", key="clear_logs"):
            st.session_state["debug_logs"] = []
            st.session_state["logs"] = []
        
        log_count = len(st.session_state.get("debug_logs", []))
        st.caption(f"Total: {log_count} entradas")
        
        if st.session_state.get("debug_logs"):
            log_df = pd.DataFrame(st.session_state["debug_logs"])
            st.dataframe(log_df.tail(20), use_container_width=True, height=200)
            
            # Botón para descargar logs
            log_json = json.dumps(st.session_state["debug_logs"], indent=2, default=str)
            st.download_button(
                "💾 Exportar Logs JSON",
                log_json,
                "debug_logs.json",
                "application/json",
                key="download_logs"
            )
    
    with debug_tabs[1]:
        times = st.session_state.get("execution_times", {})
        if times:
            times_df = pd.DataFrame([
                {"Función": k, "Tiempo (s)": f"{v:.3f}"} 
                for k, v in sorted(times.items(), key=lambda x: x[1], reverse=True)
            ])
            st.dataframe(times_df, use_container_width=True, height=200)
            
            total_time = sum(times.values())
            st.metric("Tiempo Total", f"{total_time:.2f}s")
        else:
            st.info("No hay tiempos registrados")
    
    with debug_tabs[2]:
        df = st.session_state.get("df")
        if df is not None and not df.empty:
            st.write(f"**Shape:** {df.shape}")
            st.write(f"**Columns:** {', '.join(df.columns.tolist())}")
            st.write(f"**Memoria:** {df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
            
            if st.checkbox("Ver primeras filas", key="show_head"):
                st.dataframe(df.head(10))
            
            if st.checkbox("Ver info de columnas", key="show_info"):
                buffer = io.StringIO()
                df.info(buf=buffer)
                st.text(buffer.getvalue())
        else:
            st.info("No hay DataFrame cargado")
    
    with debug_tabs[3]:
        responses = st.session_state.get("api_responses", {})
        if responses:
            selected_api = st.selectbox("API", list(responses.keys()))
            if selected_api:
                resp_data = responses[selected_api]
                st.json(resp_data)
        else:
            st.info("No hay respuestas de API registradas")


# ============================================================================
# LOGIN SEGURO
# ============================================================================


ADMIN_USER = env("ADMIN_USER") or "admin"
ADMIN_PASS = env("ADMIN_PASS") or "admin123"


def login():
    st.title("🔐 Acceso Seguro")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        user = st.text_input("Usuario")
        pwd = st.text_input("Contraseña", type="password")
        if st.button("Iniciar Sesión", use_container_width=True):
            if user == ADMIN_USER and pwd == ADMIN_PASS:
                st.session_state['logged_in'] = True
                st.rerun()
            else:
                st.error("Credenciales incorrectas.")


if "logged_in" not in st.session_state or not st.session_state['logged_in']:
    login()
    st.stop()


# ============================================================================
# FUNCIONES DE CORREO (SMTP)
# ============================================================================


def fig_to_bytes(fig) -> bytes:
    """Convierte una figura de Matplotlib a bytes PNG para adjuntar."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    buf.seek(0)
    return buf.read()


@measure_time("send_email_report")
def send_email_report(to_email, subject, body, df_xlsx, df_csv, figures_dict):
    """Envía correo con Excel, CSV y gráficos adjuntos."""
    smtp_server = env("SMTP_HOST") or "smtp.gmail.com"
    smtp_port = int(env("SMTP_PORT") or 587)
    smtp_user = env("SMTP_USER")
    smtp_pass = env("SMTP_PASS")


    if not smtp_user or not smtp_pass:
        log_message("Faltan credenciales SMTP", "error")
        return False, "Faltan credenciales SMTP en .env"


    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    
    msg.attach(MIMEText(body, 'plain', 'utf-8'))


    # Adjuntar Excel
    if df_xlsx:
        part = MIMEBase('application', "octet-stream")
        part.set_payload(df_xlsx)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="reporte_data.xlsx"')
        msg.attach(part)


    # Adjuntar CSV
    if df_csv:
        part = MIMEBase('application', "octet-stream")
        part.set_payload(df_csv)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="reporte_data.csv"')
        msg.attach(part)


    # Adjuntar Imágenes
    for name, fig_bytes in figures_dict.items():
        image = MIMEImage(fig_bytes, name=f"{name}.png")
        image.add_header('Content-Disposition', f'attachment; filename="{name}.png"')
        msg.attach(image)


    try:
        log_message(f"Conectando a {smtp_server}:{smtp_port}", "debug")
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
        server.quit()
        log_message(f"Email enviado exitosamente a {to_email}", "info")
        return True, "Correo enviado exitosamente."
    except Exception as e:
        log_message(f"Error SMTP: {str(e)}", "error", {"smtp_server": smtp_server, "exception": str(e)})
        return False, f"Error SMTP: {str(e)}"


# ============================================================================
# MOTOR IA (DEEPSEEK: SENTIMIENTO + RESUMEN)
# ============================================================================


@measure_time("generate_executive_summary")
def generate_executive_summary(df: pd.DataFrame, query: str) -> str:
    """Genera un resumen narrativo citando posts específicos."""
    key = env("DEEPSEEK_API_KEY")
    if not key:
        log_message("Falta DEEPSEEK_API_KEY", "warning")
        return "Resumen no disponible (Falta API Key)."
    
    if df.empty:
        return "Resumen no disponible (Sin datos)."
    
    # 1. Preparar Contexto
    total = len(df)
    sent_counts = df["sentiment"].value_counts(normalize=True).to_dict() if "sentiment" in df else {}
    
    # Extraer Top 3 Posts por Likes para citarlos
    if "likes" in df.columns and "text" in df.columns:
        top_posts = df.sort_values("likes", ascending=False).head(3)
        top_texts_list = []
        for _, row in top_posts.iterrows():
            user = row.get("username", "Anon")
            txt = row["text"][:100].replace("\n", " ")
            likes = row["likes"]
            top_texts_list.append(f"- Usuario @{user}: '{txt}...' ({int(likes)} likes)")
        top_posts_str = "\n".join(top_texts_list)
    else:
        top_posts_str = "No hay datos de likes disponibles."


    context = (
        f"Análisis para: '{query}'.\n"
        f"Volumen Total: {total} posts.\n"
        f"Sentimiento: {sent_counts.get('POS',0):.1%} Positivo, {sent_counts.get('NEG',0):.1%} Negativo.\n"
        f"TOP POSTS VIRALES:\n{top_posts_str}"
    )


    prompt = (
        f"Actúa como un analista de inteligencia digital. "
        f"Escribe un 'Resumen Ejecutivo' breve (máx 500 palabras) en español basado en los datos proporcionados.\n\n"
        f"DATOS:\n{context}\n\n"
        f"INSTRUCCIONES CLAVE:\n"
        f"1. Resume la tendencia general de sentimiento y emociones.\n"
        f"2. IMPORTANTE: Debes citar explícitamente al menos uno de los 'TOP POSTS VIRALES' mencionados en los datos para explicar qué está impulsando la conversación. Menciona el usuario y qué dijo brevemente.\n"
        f"3. Entrega un resumen de métricas: posteos, interacciones y visualizaciones en el caso de que estén\n"
        f"4. Mantén un tono profesional."
    )


    try:
        log_message("Solicitando resumen ejecutivo a DeepSeek", "debug", {"query": query, "total_posts": total})
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 300
            }, timeout=25
        )
        
        if st.session_state.get("debug_mode"):
            st.session_state["api_responses"]["deepseek_summary"] = {
                "status_code": r.status_code,
                "response": r.json() if r.status_code == 200 else r.text
            }
        
        if r.status_code == 200:
            summary = r.json()['choices'][0]['message']['content'].strip()
            log_message("Resumen generado exitosamente", "info")
            return summary
        else:
            log_message(f"Error API DeepSeek: {r.status_code}", "error", {"response": r.text})
            return f"Error API DeepSeek: {r.status_code}"
    except Exception as e:
        log_message(f"Error generando resumen: {e}", "error", {"exception": str(e)})
        return f"Error generando resumen: {e}"


# --- Funciones Async con Debug ---
async def async_fetch_deepseek(client: httpx.AsyncClient, prompt: str, sem: asyncio.Semaphore, max_tokens: int = 10) -> str:
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
                headers={"Authorization": f"Bearer {deepseek_key}", "Content-Type": "application/json"}, 
                timeout=45.0
            )
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content'].strip().upper()
                return re.sub(r'[^\w]', '', content)
            return "NEU"
        except Exception as e:
            if st.session_state.get("debug_mode"):
                log_message(f"Error en async_fetch_deepseek: {e}", "debug")
            return "NEU"


@measure_time("process_sentiment_batch")
async def process_sentiment_batch_async(texts: List[str]) -> List[str]:
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    sem = asyncio.Semaphore(10) 
    async with httpx.AsyncClient(base_url="https://api.deepseek.com", limits=limits, timeout=60.0) as client:
        tasks = []
        for text in texts:
            safe_text = text[:300] if text else ""
            prompt = f"Clasifica el sentimiento: '{safe_text}'. Responde EXCLUSIVAMENTE con una palabra: POS, NEG o NEU."
            tasks.append(async_fetch_deepseek(client, prompt, sem, 5))
        results = await asyncio.gather(*tasks)
        
        final_results = []
        for r in results:
            if r in ["POS", "NEG", "NEU"]: final_results.append(r)
            elif "POS" in r: final_results.append("POS")
            elif "NEG" in r: final_results.append("NEG")
            else: final_results.append("NEU")
        return final_results


@measure_time("process_emotions_batch")
async def process_emotions_batch_async(texts: List[str]) -> List[str]:
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    valid_emotions = ["RISA", "IRA", "MIEDO", "TRISTEZA", "DISGUSTO", "SORPRESA", "NEUTRAL"]
    sem = asyncio.Semaphore(10)
    async with httpx.AsyncClient(base_url="https://api.deepseek.com", limits=limits, timeout=60.0) as client:
        tasks = []
        for text in texts:
            safe_text = text[:300] if text else ""
            prompt = f"Detecta la emoción en: '{safe_text}'. Opciones: {', '.join(valid_emotions)}. Responde SOLO con la palabra clave."
            tasks.append(async_fetch_deepseek(client, prompt, sem, 10))
        results = await asyncio.gather(*tasks)
        
        clean_results = []
        for r in results:
            found = False
            for emo in valid_emotions:
                if emo in r:
                    clean_results.append(emo)
                    found = True
                    break
            if not found: clean_results.append("NEUTRAL")
        return clean_results


def analyze_sentiment_deepseek_optimized(texts: List[str]) -> List[str]:
    if not texts: return []
    try: 
        log_message(f"Analizando sentimiento de {len(texts)} textos", "debug")
        return asyncio.run(process_sentiment_batch_async(texts))
    except Exception as e:
        log_message(f"Error Sentiment Async: {e}", "error")
        return ["NEU"] * len(texts)


def analyze_emotions_deepseek_optimized(texts: List[str]) -> List[str]:
    if not texts: return []
    try: 
        log_message(f"Analizando emociones de {len(texts)} textos", "debug")
        return asyncio.run(process_emotions_batch_async(texts))
    except Exception as e:
        log_message(f"Error Emotions Async: {e}", "error")
        return ["NEUTRAL"] * len(texts)


# ============================================================================
# APIFY CORE & FETCHERS (CON DEBUG)
# ============================================================================


@measure_time("get_apify_items")
def get_apify_items_sync(dataset_id: str, token: str) -> List[Dict]:
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    try:
        log_message(f"Descargando dataset: {dataset_id}", "debug")
        r = requests.get(url, params={"token": token, "clean": "1", "format": "json"}, timeout=60)
        
        if st.session_state.get("debug_mode"):
            st.session_state["api_responses"][f"apify_dataset_{dataset_id}"] = {
                "status_code": r.status_code,
                "items_count": len(r.json()) if r.status_code == 200 else 0
            }
        
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        log_message(f"Error descargando dataset {dataset_id}: {e}", "error")
        return []


@measure_time("run_apify_actor")
def run_apify_actor(actor_id: str, tokens: List[str], payload: Dict) -> List[Dict]:
    valid_tokens = [t for t in tokens if t and t.strip()]
    if not valid_tokens: 
        log_message("No hay tokens Apify válidos", "warning")
        return []


    for i, token in enumerate(valid_tokens):
        url_run = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/runs"
        try:
            log_message(f"Iniciando actor {actor_id} (intento {i+1}/{len(valid_tokens)})", "debug", {"payload": payload})
            r = requests.post(url_run, params={"token": token}, json=payload, timeout=30)
            
            if r.status_code not in [200, 201]: 
                log_message(f"Error iniciando actor: {r.status_code}", "warning")
                continue


            run_data = r.json()["data"]
            run_id, dataset_id = run_data["id"], run_data["defaultDatasetId"]
            log_message(f"Actor iniciado - Run ID: {run_id}", "info")
            
            start_time = time.time()
            while time.time() - start_time < 300:
                time.sleep(ASYNC_POLL_INTERVAL)
                try:
                    r_poll = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}", params={"token": token}, timeout=10)
                    if r_poll.status_code == 200:
                        status = r_poll.json()["data"]["status"]
                        log_message(f"Estado actor: {status}", "debug")
                        if status == "SUCCEEDED": 
                            return get_apify_items_sync(dataset_id, token)
                        elif status in ["FAILED", "ABORTED", "TIMED-OUT"]: 
                            log_message(f"Actor falló con estado: {status}", "error")
                            break
                except Exception as e:
                    log_message(f"Error polling actor: {e}", "debug")
                    continue
        except Exception as e:
            log_message(f"Excepción en run_apify_actor: {e}", "error")
            if i < len(valid_tokens) - 1: continue
    return []


@measure_time("normalize_common")
def normalize_common_optimized(rows: List[Dict], platform: str) -> pd.DataFrame:
    """Normaliza datos de diferentes plataformas SIN conversión de timezone."""
    log_message(f"Normalizando {len(rows)} filas de {platform}", "debug")
    df = pd.DataFrame(rows)
    if df.empty: return df

    col_map = {
        "text": ["caption", "description", "title", "text", "message", "postText"],
        "likes": ["likeCount", "likesCount", "diggCount", "likes", "reactionCount"],
        "comments": ["commentCount", "commentsCount", "comments"],
        "shares": ["shareCount", "retweetCount", "shares"],
        "views": ["playCount", "viewCount", "videoPlayCount", "views"],
        "followers": ["followers", "followersCount", "fans", "followerCount", "userFollowers"],
        "created_at": ["timestamp", "takenAt", "createTimeISO", "createdAt", "date", "time"]
    }

    for target, candidates in col_map.items():
        if target not in df.columns:
            for c in candidates:
                if c in df.columns: 
                    df[target] = df[c]
                    break
            if target not in df.columns: 
                df[target] = 0 if target in ["likes", "comments", "shares", "views", "followers"] else None

    # CONVERSIÓN DE FECHAS SIMPLIFICADA (SIN TIMEZONE)
    if "created_at" in df.columns:
        try:
            # Convertir a datetime UTC
            df["created_at_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
            
            # Extraer SOLO la fecha como string o date object (sin timezone)
            df["fecha_cl"] = df["created_at_utc"].dt.date
            
            # Crear versión naive (sin timezone) para visualización
            df["created_at_display"] = df["created_at_utc"].dt.tz_localize(None)
            
            failed = df["created_at_utc"].isna().sum()
            if failed > 0:
                log_message(f"⚠️ {failed} fechas no convertidas", "warning")
                
        except Exception as e:
            log_message(f"Error en conversión de fechas: {e}", "error")
            df["created_at_utc"] = pd.NaT
            df["fecha_cl"] = None
            df["created_at_display"] = pd.NaT
    
    # Usuario
    if "username" not in df.columns:
        for c in ["ownerUsername", "authorUsername", "username", "author", "pageName"]:
            if c in df.columns:
                df["username"] = df[c].apply(lambda x: x.get('name') if isinstance(x, dict) else x)
                break
    
    # Texto
    if "text" in df.columns: 
        df["text"] = df["text"].fillna("").astype(str)
    
    # Métricas numéricas
    for col in ["likes", "comments", "shares", "views", "followers"]:
        if col in df.columns: 
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["platform"] = platform
    
    log_message(f"Normalización completa: {df.shape}", "debug")
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_x_cached(api_key: str, query: str, limit: int) -> pd.DataFrame:
    log_message(f"Fetching X con query: {query}", "info")
    headers = {"x-api-key": api_key}
    all_rows = []
    cursor = None
    max_loops = (limit // 20) + 5 
    for loop_num in range(max_loops):
        params = {"query": query, "queryType": "Latest"}
        if cursor: params["cursor"] = cursor
        try:
            r = requests.get(API_URL_X, headers=headers, params=params, timeout=20)
            
            if st.session_state.get("debug_mode"):
                st.session_state["api_responses"][f"x_request_{loop_num}"] = {
                    "status_code": r.status_code,
                    "cursor": cursor,
                    "tweets_count": len(r.json().get("tweets", [])) if r.status_code == 200 else 0
                }
            
            if r.status_code != 200: 
                log_message(f"Error API X: {r.status_code}", "warning")
                break
            data = r.json()
            tweets = data.get("tweets", [])
            if not tweets: break
            for t in tweets:
                u = t.get("author", {})
                all_rows.append({
                    "id": t.get("id"), "created_at": t.get("createdAt"),
                    "username": u.get("userName"), "text": t.get("text"),
                    "likes": t.get("likeCount", 0), "comments": t.get("replyCount", 0),
                    "shares": t.get("retweetCount", 0), "views": t.get("viewCount", 0),
                    "followers": u.get("followers") or u.get("followersCount") or 0,
                    "url": t.get("url"),
                })
            if len(all_rows) >= limit: break
            cursor = data.get("next_cursor") if data.get("has_next_page") else None
            if not cursor: break
        except Exception as e:
            log_message(f"Excepción en fetch_x: {e}", "error")
            break
    
    log_message(f"Total tweets obtenidos: {len(all_rows)}", "info")
    return normalize_common_optimized(all_rows, "x")


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_facebook_cached(tokens: List[str], query: str, limit: int, mode: str) -> pd.DataFrame:
    log_message(f"Fetching Facebook ({mode}): {query}", "info")
    payload = {"resultsLimit": limit, "maxPosts": limit}
    actor = "apify/facebook-posts-scraper"
    if mode == "user":
        urls = []
        for u in query.split(","):
            u = u.strip()
            if "facebook.com" in u: urls.append({"url": u})
            else: urls.append({"url": f"https://www.facebook.com/{u}"})
        payload["startUrls"] = urls
    else:
        recent_filter = "eyJzb3J0X2tleSI6InRECENT_POSTS_V2In0%3D"
        payload["startUrls"] = [{"url": f"https://www.facebook.com/search/posts?q={query}&filters={recent_filter}"}]
    try:
        items = run_apify_actor(actor, tokens, payload)
        normalized = []
        for i in items:
            normalized.append({
                "id": i.get("postId"), "text": i.get("text") or i.get("postText") or i.get("message"),
                "username": i.get("user", {}).get("name"), "likes": i.get("likes", 0), "comments": i.get("comments", 0),
                "shares": i.get("shares", 0), "url": i.get("url") or i.get("postUrl"), "created_at": i.get("time") or i.get("timestamp")
            })
        return normalize_common_optimized(normalized, "facebook")
    except Exception as e:
        log_message(f"Error fetch_facebook: {e}", "error")
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_instagram_cached(tokens: List[str], query: str, limit: int, mode: str) -> pd.DataFrame:
    log_message(f"Fetching Instagram ({mode}): {query}", "info")
    payload = {"resultsLimit": limit, "resultsType": "posts"}
    if mode == "hashtag":
        actor = "apify/instagram-hashtag-scraper"
        payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
    elif mode == "keyword":
        actor = "apify/instagram-scraper"
        payload["search"] = query
        payload["searchType"] = "hashtag"
    else:
        actor = "apify/instagram-post-scraper"
        payload["usernames"] = [u.strip() for u in query.split(",")]
    items = run_apify_actor(actor, tokens, payload)
    return normalize_common_optimized(items, "instagram")


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tiktok_cached(tokens: List[str], query: str, limit: int, mode: str) -> pd.DataFrame:
    log_message(f"Fetching TikTok ({mode}): {query}", "info")
    payload = {"resultsPerPage": 100, "shouldDownloadVideos": False, "limit": limit}
    if mode == "user": payload["usernames"] = [u.strip() for u in query.split(",")]
    else: payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
    items = run_apify_actor("clockworks/tiktok-scraper", tokens, payload)
    return normalize_common_optimized(items, "tiktok")


# ============================================================================
# UTILS DE FILTRADO Y EXPORT
# ============================================================================


def enforce_date_window(df: pd.DataFrame, d1: Optional[date], d2: Optional[date]) -> pd.DataFrame:
    """
    Filtra DataFrame por ventana de fechas.
    Versión robusta con comparación por strings ISO.
    """
    if df is None or df.empty:
        return df
    
    if "fecha_cl" not in df.columns:
        log_message("Columna 'fecha_cl' no encontrada, saltando filtrado", "warning")
        return df
    
    # Validar fechas
    current = datetime.now(SCL_TZ).date()
    if d1 and d1 > current:
        log_message(f"Ajustando fecha 'desde' futura: {d1} → {current}", "warning")
        d1 = current
    if d2 and d2 > current:
        log_message(f"Ajustando fecha 'hasta' futura: {d2} → {current}", "warning")
        d2 = current
    
    try:
        # Convertir fecha_cl a string de forma segura
        def safe_date_str(x):
            """Convierte cualquier tipo de fecha a string ISO"""
            if pd.isna(x):
                return None
            try:
                if isinstance(x, str):
                    return x[:10]  # Ya es string, tomar YYYY-MM-DD
                elif isinstance(x, date):
                    return x.isoformat()
                elif isinstance(x, pd.Timestamp):
                    return x.date().isoformat()
                elif hasattr(x, 'strftime'):  # datetime64
                    return pd.to_datetime(x).date().isoformat()
                else:
                    return str(x)[:10]
            except:
                return None
        
        # Crear columna temporal de trabajo
        df_work = df.copy()
        df_work["_fecha_str"] = df_work["fecha_cl"].apply(safe_date_str)
        
        # Convertir fechas de filtro a string ISO
        d1_str = d1.isoformat() if d1 else None
        d2_str = d2.isoformat() if d2 else None
        
        # Crear máscara de filtrado
        mask = pd.Series(True, index=df_work.index)
        
        if d1_str:
            mask &= ((df_work["_fecha_str"] >= d1_str) | (df_work["_fecha_str"].isna()))
        
        if d2_str:
            mask &= ((df_work["_fecha_str"] <= d2_str) | (df_work["_fecha_str"].isna()))
        
        # Aplicar filtro al DataFrame original
        filtered = df.loc[mask].copy()
        
        removed = len(df) - len(filtered)
        log_message(f"Filtrado: {len(df)} → {len(filtered)} ({removed} removidos)", "info")
        
        if st.session_state.get("debug_mode"):
            log_message(
                "Detalles filtrado",
                "debug",
                {
                    "original": len(df),
                    "filtered": len(filtered),
                    "removed": removed,
                    "d1": d1_str,
                    "d2": d2_str,
                    "null_dates": df_work["_fecha_str"].isna().sum(),
                    "fecha_cl_dtype": str(df["fecha_cl"].dtype),
                    "sample_dates": df_work["_fecha_str"].dropna().head(3).tolist()
                }
            )
        
        return filtered
        
    except Exception as e:
        log_message(
            f"Error en filtrado: {e}", 
            "error", 
            {"traceback": traceback.format_exc()}
        )
        st.warning(f"⚠️ Error al filtrar fechas: {e}. Mostrando todos los datos.")
        return df



# ============================================================================
# FUNCIONES VISUALES
# ============================================================================


def plot_pie_chart(series, title):
    if series.empty: return None
    counts = series.value_counts()
    fig, ax = plt.subplots(figsize=(6, 6))
    fig.patch.set_facecolor('white')
    wedges, texts, autotexts = ax.pie(counts, labels=counts.index, autopct='%1.1f%%', startangle=90)
    ax.set_title(title, fontsize=12, fontweight='bold')
    return fig


def plot_bar_chart(series, title, color_hex="#3498db"):
    if series.empty: return None
    counts = series.value_counts()
    fig, ax = plt.subplots(figsize=(6, 5))
    fig.patch.set_facecolor('white')
    bars = ax.bar(counts.index, counts.values, color=color_hex)
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.set_ylabel("Cantidad")
    plt.tight_layout()
    return fig


def clean_texts(texts: pd.Series) -> str:
    blob = []
    EXTRA_STOP = {"rt","https","http","t","co","amp","si","no","de","la","que","el","en","y","a","los","del","se","las","por","un","para","con","una","su","al","lo","como","mas","pero","sus","le","ya","o","fue","ha","porque","cuando","muy","sin","sobre","tambien","me"}
    STOP = STOPWORDS.union(EXTRA_STOP)
    for s in texts.fillna("").astype(str):
        s = re.sub(r"http\S+|www\.\S+|@\w+|#", " ", s.lower())
        s = unidecode(s)
        s = re.sub(r"[^a-z\s]", " ", s)
        words = [w for w in s.split() if w not in STOP and len(w) > 2]
        blob.extend(words)
    return " ".join(blob)


def wordcloud_from_blob(blob: str, max_words: int = 200):
    if not blob.strip(): return None
    wc = WordCloud(width=1200, height=500, background_color="white", max_words=max_words, colormap="viridis").generate(blob)
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.imshow(wc, interpolation='bilinear')
    ax.axis("off")
    return fig


def extract_topics(texts: List[str], top_n: int = 10) -> Dict[str, int]:
    blob = clean_texts(pd.Series(texts))
    return dict(Counter(blob.split()).most_common(top_n))


@measure_time("detect_crisis_signals")
def detect_crisis_signals(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty: return {"score": 0, "severity": "none", "signals": [], "crisis_posts": pd.DataFrame()}
    signals = []
    crisis_score = 0
    keywords = ["crisis", "emergencia", "caída", "fallo", "problema", "error", "incidente", "demanda", "denuncia", "escándalo", "fraude", "robo", "ataque"]
    
    if "sentiment" in df.columns:
        neg_ratio = (df["sentiment"] == "NEG").sum() / max(1, len(df))
        if neg_ratio > 0.3:
            signals.append(f"Sentimiento negativo alto: {neg_ratio*100:.1f}%")
            crisis_score += 25
            
    if "text" in df.columns:
        crisis_posts = df[df["text"].str.lower().str.contains("|".join(keywords), regex=True, na=False)].copy()
        if len(crisis_posts) > 0:
            count = len(crisis_posts)
            signals.append(f"Posts con palabras de crisis: {count}")
            crisis_score += min(30, count * 5)
            if "followers" in df.columns:
                influencers = crisis_posts[crisis_posts["followers"] > 10000]
                if not influencers.empty:
                    crisis_score += min(30, len(influencers) * 10)
                    signals.append(f"⚠️ {len(influencers)} cuenta(s) influyente(s) involucrada(s)")
    else: crisis_posts = pd.DataFrame()
        
    crisis_score = min(100, crisis_score)
    severity = "critical" if crisis_score >= 80 else "high" if crisis_score >= 60 else "medium" if crisis_score >= 30 else "low"
    
    log_message(f"Detección de crisis: score={crisis_score}, severity={severity}", "info", {"signals": signals})
    return {"score": crisis_score, "severity": severity, "signals": signals, "crisis_posts": crisis_posts}


def compose_query_x(topic: str, lang: str, exclude_rt: bool, exclude_repl: bool, d1: Optional[date], d2: Optional[date], filter_chile: bool) -> str:
    q = topic.strip()
    if not q.startswith("("): q = f"({q})"
    if lang: q += f" lang:{lang}"
    if exclude_rt: q += " -is:retweet"
    if exclude_repl: q += " -is:reply"
    if filter_chile: q += " place_country:CL"
    if d1: q += f" since:{d1.isoformat()}_00:00:00_UTC"
    if d2: q += f" until:{(d2 + timedelta(days=1)).isoformat()}_00:00:00_UTC"
    log_message(f"Query X generado: {q}", "debug")
    return q


def compose_query_x_user(username: str, lang: str, exclude_rt: bool, exclude_repl: bool, d1: Optional[date], d2: Optional[date], filter_chile: bool) -> str:
    u = username.strip().lstrip("@")
    q = f"from:{u}"
    if lang: q += f" lang:{lang}"
    if exclude_rt: q += " -is:retweet"
    if exclude_repl: q += " -is:reply"
    if filter_chile: q += " place_country:CL"
    if d1: q += f" since:{d1.isoformat()}_00:00:00_UTC"
    if d2: q += f" until:{(d2 + timedelta(days=1)).isoformat()}_00:00:00_UTC"
    log_message(f"Query X user generado: {q}", "debug")
    return q


# ============================================================================
# INTERFAZ STREAMLIT (CORREGIDA - CREDENCIALES EN EL LUGAR CORRECTO)
# ============================================================================

st.title("📡 Social Listening Pro — X + Instagram + Facebook + TikTok")
st.markdown("**Análisis avanzado con detección de crisis, sentimiento y reporte por email**")

st.sidebar.header("⚙️ Configuración")

# ============================================================================
# DEBUG MODE TOGGLE (PRIMERO)
# ============================================================================
st.sidebar.markdown("---")
debug_mode = st.sidebar.checkbox(
    "🐛 **Modo Debug**", 
    value=st.session_state.get("debug_mode", False),
    key="toggle_debug_mode"
)
st.session_state["debug_mode"] = debug_mode

if debug_mode:
    st.sidebar.info("⚠️ Modo Debug activo. Ver panel abajo.")

st.sidebar.markdown("---")

# ============================================================================
# CONFIGURACIÓN DE PLATAFORMA Y BÚSQUEDA
# ============================================================================

platform = st.sidebar.selectbox("Plataforma", ["X (Twitter)", "Instagram", "Facebook", "TikTok"])

if platform == "Instagram":
    search_mode = st.sidebar.radio("Modo", ["Por temática (hashtags)", "Por temática (búsqueda IG)", "Por usuario"])
elif platform == "Facebook":
    search_mode = st.sidebar.radio("Modo", ["Por temática", "Por usuario"])
else:
    search_mode = st.sidebar.radio("Modo", ["Por temática", "Por usuario"])

topic = ""
username_input = ""
hashtags_str = ""

if search_mode.startswith("Por temática"):
    if platform == "Instagram" and "hashtags" in search_mode:
        hashtags_str = st.sidebar.text_input("Hashtag(s) (sin #, separado por comas)")
    else:
        topic = st.sidebar.text_input("Tema / consulta")
else:
    username_input = st.sidebar.text_input("Usuario(s) (separar por coma)")

lang = st.sidebar.selectbox("Idioma (solo X)", ["", "es", "en", "pt"], index=1)
col1, col2 = st.sidebar.columns(2)
exclude_rt = col1.checkbox("Excluir RTs [X]", value=True)
exclude_repl = col2.checkbox("Excluir respuestas [X]", value=True)
filter_chile = st.sidebar.checkbox("🇨🇱 Filtrar solo Chile (X)")

st.sidebar.divider()

# ============================================================================
# FECHAS CON VALIDACIÓN
# ============================================================================

current_date_cl = datetime.now(SCL_TZ).date()
default_start = current_date_cl - timedelta(days=14)

d1 = st.sidebar.date_input(
    "Desde", 
    value=default_start,
    max_value=current_date_cl,
    key="date_input_from"
)

d2 = st.sidebar.date_input(
    "Hasta", 
    value=current_date_cl,
    max_value=current_date_cl,
    min_value=d1 if d1 else None,
    key="date_input_to"
)

# Validación de rango
if d1 and d2 and d1 > d2:
    st.sidebar.error("⚠️ Fecha 'Desde' no puede ser posterior a 'Hasta'")

limit = st.sidebar.slider("Límite de posts", 50, 2000, 200)
max_words = st.sidebar.slider("Máx. palabras nube", 50, 500, 200)

sentiment = st.sidebar.checkbox("🧠 Analizar Sentimiento", value=True)
emotions = st.sidebar.checkbox("😊 Analizar Emociones", value=False)

st.sidebar.divider()

# ============================================================================
# CREDENCIALES (AQUÍ, ANTES DEL BOTÓN)
# ============================================================================

st.sidebar.subheader("🔑 Credenciales API")

# X / Twitter API
env_x = env("TWITTERAPI_IO_KEY")
if env_x:
    api_x = env_x
    st.sidebar.success("✅ X API cargada desde .env")
else:
    api_x = st.sidebar.text_input(
        "API Key twitterapi.io", 
        type="password", 
        key="manual_api_x",
        help="Ingresa tu API Key de twitterapi.io"
    )
    if api_x:
        st.sidebar.success("✅ X API ingresada")
    else:
        st.sidebar.warning("⚠️ X API no configurada")

# Apify Token
env_apify = env("APIFY_TOKEN")
if env_apify:
    api_apify = env_apify
    st.sidebar.success("✅ Apify Token cargado desde .env")
else:
    api_apify = st.sidebar.text_input(
        "Token Apify", 
        type="password", 
        key="manual_api_apify",
        help="Ingresa tu token de Apify"
    )
    if api_apify:
        st.sidebar.success("✅ Apify Token ingresado")
    else:
        st.sidebar.warning("⚠️ Apify Token no configurado")

st.sidebar.divider()

# ============================================================================
# BOTÓN DE BÚSQUEDA
# ============================================================================

run_btn = st.sidebar.button("🔍 Buscar", type="primary", use_container_width=True)

# ============================================================================
# RENDER DEBUG PANEL (AL FINAL DEL SIDEBAR)
# ============================================================================

if debug_mode:
    render_debug_panel()


# ============================================================================
# EJECUCIÓN
# ============================================================================

if run_btn:
    # Reset states
    st.session_state["logs"] = []
    st.session_state["debug_logs"] = []
    st.session_state["execution_times"] = {}
    st.session_state["api_responses"] = {}
    st.session_state["report_figures"] = {}
    st.session_state["ai_summary"] = None
    
    log_message("🚀 Iniciando búsqueda", "info")
    prog = st.progress(0.0, text="Iniciando...")
    df = pd.DataFrame()
    tokens = [t for t in [api_apify] if t]

    try:
        # 1. FETCHING
        prog.progress(0.1, text="Obteniendo datos...")
        
        if platform.startswith("X"):
            if not api_x: 
                st.error("❌ Falta API Key X. Ingresa las credenciales en el sidebar.")
                log_message("API Key X no configurada", "error")
                st.stop()
            if "usuario" in search_mode: 
                q = compose_query_x_user(username_input, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            else: 
                q = compose_query_x(topic, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            df = fetch_x_cached(api_x, q, limit)
        
        elif platform == "Facebook":
            if not tokens: 
                st.error("❌ Falta Token Apify. Ingresa las credenciales en el sidebar.")
                log_message("Token Apify no configurado", "error")
                st.stop()
            mode = "user" if "usuario" in search_mode else "search"
            q = username_input if mode == "user" else topic
            df = fetch_facebook_cached(tokens, q, limit, mode)
            
        elif platform == "Instagram":
            if not tokens: 
                st.error("❌ Falta Token Apify. Ingresa las credenciales en el sidebar.")
                log_message("Token Apify no configurado", "error")
                st.stop()
            mode = "hashtag" if "hashtags" in search_mode else "keyword" if "búsqueda" in search_mode else "user"
            q = hashtags_str if mode == "hashtag" else (username_input if mode == "user" else topic)
            df = fetch_instagram_cached(tokens, q, limit, mode)
            
        elif platform == "TikTok":
            if not tokens: 
                st.error("❌ Falta Token Apify. Ingresa las credenciales en el sidebar.")
                log_message("Token Apify no configurado", "error")
                st.stop()
            mode = "user" if "usuario" in search_mode else "hashtag"
            q = username_input if mode == "user" else topic
            df = fetch_tiktok_cached(tokens, q, limit, mode)

        prog.progress(0.3, text="Aplicando filtros de fecha...")
        
        # APLICAR FILTRO DE FECHAS CON MANEJO DE ERRORES
        try:
            df = enforce_date_window(df, d1, d2)
        except Exception as date_error:
            log_message(
                f"Error al filtrar fechas: {date_error}", 
                "error",
                {"d1": str(d1), "d2": str(d2), "traceback": traceback.format_exc()}
            )
            st.warning("⚠️ No se pudo aplicar el filtro de fechas. Mostrando todos los resultados.")
        
        prog.progress(0.4, text="Verificando datos...")

        if df.empty:
            st.warning("No se encontraron resultados.")
            log_message("Búsqueda sin resultados", "warning")
            st.stop()

        log_message(f"✅ Obtenidos {len(df)} posts", "info")

        # 2. IA (DeepSeek Sentimiento + Resumen Ejecutivo)
        prog.progress(0.5, text="Procesando IA...")
        
        if "text" in df.columns:
            texts = df["text"].tolist()
            
            if sentiment:
                prog.progress(0.6, text="Analizando sentimiento...")
                with st.spinner("DeepSeek Sentimiento..."): 
                    df["sentiment"] = analyze_sentiment_deepseek_optimized(texts)
            
            if emotions:
                prog.progress(0.7, text="Analizando emociones...")
                with st.spinner("DeepSeek Emociones..."): 
                    df["emotion"] = analyze_emotions_deepseek_optimized(texts)
            
            # GENERAR RESUMEN EJECUTIVO
            prog.progress(0.8, text="Generando resumen ejecutivo...")
            with st.spinner("Redactando Resumen Ejecutivo y analizando posts virales..."):
                query_context = topic or username_input or hashtags_str
                summary = generate_executive_summary(df, query_context)
                st.session_state["ai_summary"] = summary

        prog.progress(1.0, text="✅ Listo")
        st.session_state["df"] = df
        log_message("✅ Proceso completado exitosamente", "info")
        
    except Exception as e:
        st.error(f"Error crítico: {e}")
        log_message(str(e), "error", {"traceback": traceback.format_exc()})
        if st.session_state.get("debug_mode"):
            st.exception(e)
    
    finally:
        prog.empty()


# ============================================================================
# VISUALIZACIÓN & REPORTE (SIN CAMBIOS)
# ============================================================================

df = st.session_state.get("df")
ai_summary = st.session_state.get("ai_summary")

if df is not None and not df.empty:
    
    # 0. MOSTRAR RESUMEN IA
    if ai_summary:
        st.info(f"🤖 **Resumen Ejecutivo (IA):**\n\n{ai_summary}")

    # Crisis Alert
    crisis_data = detect_crisis_signals(df)
    if crisis_data["score"] > 0:
        c_color = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}.get(crisis_data["severity"],"⚪")
        st.header(f"{c_color} Alerta de Crisis")
        col1, col2 = st.columns([1,3])
        col1.metric("Score Crisis", f"{crisis_data['score']}/100")
        with col2:
            for s in crisis_data["signals"]: st.write(f"• {s}")
        
        if not crisis_data["crisis_posts"].empty:
            st.warning("⚠️ Se han detectado los siguientes posts conflictivos:")
            cols_to_show = ["created_at", "username", "text", "likes", "url"]
            cols_existentes = [c for c in cols_to_show if c in crisis_data["crisis_posts"].columns]
            st.dataframe(crisis_data["crisis_posts"][cols_existentes], use_container_width=True)
            st.download_button(
                label="📥 Descargar Posts de Crisis (Excel)",
                data=dftoexcelbytes(crisis_data["crisis_posts"]),
                file_name="reporte_crisis.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="btn_download_crisis"
            )
        
        st.divider()

    # KPIs
    st.header("📈 Dashboard")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Posts", len(df))
    k2.metric("Likes", int(df["likes"].sum()))
    k3.metric("Comentarios", int(df["comments"].sum()))
    k4.metric("Vistas", int(df["views"].sum()) if "views" in df else 0)

    # Gráficos con CAPTURA
    st.header("📊 Visualizaciones")
    tabs = st.tabs(["📅 Temporal", "🧠 Sentimiento", "🎭 Emociones", "🏷️ Temas", "☁️ Nube"])
    current_figures = {}

    with tabs[0]:
        if "fecha_cl" in df.columns:
            by_day = df["fecha_cl"].value_counts().sort_index()
            if not by_day.empty:
                fig, ax = plt.subplots(figsize=(10,4))
                dates_str = [str(d) for d in by_day.index]
                ax.bar(dates_str, by_day.values, color="#2ca02c")
                ax.set_title("Evolución diaria")
                plt.xticks(rotation=45)
                st.pyplot(fig)
                current_figures["evolucion"] = fig_to_bytes(fig)
                plt.close(fig)

    with tabs[1]:
        if "sentiment" in df.columns:
            c1, c2 = st.columns(2)
            with c1:
                fig1 = plot_pie_chart(df["sentiment"], "Distribución Sentimiento")
                if fig1: 
                    st.pyplot(fig1)
                    current_figures["sentimiento_pie"] = fig_to_bytes(fig1)
                    plt.close(fig1)
            with c2:
                fig2 = plot_bar_chart(df["sentiment"], "Conteo Sentimiento", "#2ecc71")
                if fig2: 
                    st.pyplot(fig2)
                    current_figures["sentimiento_bar"] = fig_to_bytes(fig2)
                    plt.close(fig2)

    with tabs[2]:
        if "emotion" in df.columns:
            c1, c2 = st.columns(2)
            with c1:
                fig3 = plot_pie_chart(df["emotion"], "Distribución Emociones")
                if fig3:
                    st.pyplot(fig3)
                    current_figures["emociones_pie"] = fig_to_bytes(fig3)
                    plt.close(fig3)
            with c2:
                fig4 = plot_bar_chart(df["emotion"], "Conteo Emociones", "#9b59b6")
                if fig4:
                    st.pyplot(fig4)
                    current_figures["emociones_bar"] = fig_to_bytes(fig4)
                    plt.close(fig4)

    with tabs[3]:
        if "text" in df.columns:
            topics = extract_topics(df["text"].tolist())
            st.bar_chart(pd.Series(topics))
            fig_t, ax_t = plt.subplots()
            ax_t.bar(list(topics.keys()), list(topics.values()))
            ax_t.set_title("Top Tópicos")
            plt.xticks(rotation=45)
            current_figures["top_topicos"] = fig_to_bytes(fig_t)
            plt.close(fig_t)

    with tabs[4]:
        if "text" in df.columns:
            blob = clean_texts(df["text"])
            fig_wc = wordcloud_from_blob(blob)
            if fig_wc:
                st.pyplot(fig_wc)
                current_figures["wordcloud"] = fig_to_bytes(fig_wc)
                plt.close(fig_wc)

    st.session_state["report_figures"] = current_figures

    st.divider()
    
    # SECCIÓN EMAIL
    st.header("📧 Enviar Reporte")
    with st.expander("Configuración de Envío", expanded=True):
        email_to = st.text_input("Destinatario", placeholder="jp@empresa.com")
        if st.button("Enviar Reporte Completo", use_container_width=True):
            if not email_to: st.error("Ingresa un correo.")
            elif not st.session_state["report_figures"]: st.warning("Genera gráficos primero.")
            else:
                with st.spinner("Enviando..."):
                    query_val = topic or username_input or hashtags_str
                    fecha_reporte = datetime.now(SCL_TZ).strftime('%d/%m/%Y %H:%M')
                    
                    email_body = (
                        f"REPORTE SOCIAL LISTENING PRO\n"
                        f"============================\n"
                        f"Fecha de generación: {fecha_reporte}\n"
                        f"Plataforma: {platform}\n"
                        f"Búsqueda: {query_val}\n\n"
                        f"RESUMEN EJECUTIVO (IA):\n"
                        f"{ai_summary if ai_summary else 'No disponible.'}\n\n"
                        f"METRICAS GENERALES:\n"
                        f"- Total Posts: {len(df)}\n"
                        f"- Interacciones Totales: {int(df['likes'].sum() + df['comments'].sum())}\n"
                        f"- Visualizaciones: {int(df['views'].sum())}\n\n"
                        f"Se adjuntan los datos detallados (Excel/CSV) y los gráficos del dashboard.\n"
                    )
                    success, msg = send_email_report(
                        email_to, 
                        f"Reporte: {platform} - {query_val}", 
                        email_body, 
                        df_to_excel_bytes(df), 
                        df_to_csv_bytes(df), 
                        st.session_state["report_figures"]
                    )
                    if success: st.success(f"✅ {msg}")
                    else: st.error(f"❌ {msg}")

    # Descargas Manuales
    c1, c2 = st.columns(2)
    c1.download_button("📥 Excel", df_to_excel_bytes(df), "reporte.xlsx")
    c2.download_button("📥 CSV", df_to_csv_bytes(df), "reporte.csv")


# ============================================================================
# FOOTER CON LOGS (SIEMPRE VISIBLE)
# ============================================================================

if st.session_state.get("logs"):
    with st.expander("📋 Logs de Ejecución", expanded=False):
        for log in st.session_state["logs"][-50:]:  # Últimos 50 logs
            st.text(log)
