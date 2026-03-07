# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Optimizado por "JP" Persona - V6.8.2 (IG keyword fixed + FB search actor + Apify v2 robust runs + Excel export dedup)
# UI: EspaÃ±ol | Feat: Stealth Credentials + Email Reporting + AI Analyst (Specific Citations) + Debug Tools

import os, re, io, time, json, random, pytz, requests, pandas as pd, streamlit as st
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
from pandas.api.types import is_datetime64tz_dtype, is_datetime64_any_dtype
from typing import Optional, List, Dict, Any
from collections import Counter
import logging
import traceback
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# =============================================================================
# CONFIG
# =============================================================================

st.set_page_config(page_title="SocialListening Pro", page_icon="SLP", layout="wide")

BUILD_TAG = "JP Release v6.9.0 - FB/Apify resiliency + dedup + run metrics + date filtering controls"
st.caption(f"Build: {BUILD_TAG}")

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

SCL_TZ = pytz.timezone("America/Santiago")
API_URL_X = "https://api.twitterapi.io/twitter/tweet/advanced_search"

# Apify actors (mejor elecciÃ³n por modo)
APIFY_ACTOR_IG_HASHTAG = "apidojo/instagram-hashtag-scraper"          # keyword + hashtag -> posts/captions (ideal para temÃ¡tica)
APIFY_ACTOR_IG_POSTS   = "apify/instagram-post-scraper"              # por usuario -> posts
APIFY_ACTOR_FB_SEARCH  = "scraper_one/facebook-posts-search"         # bÃºsqueda por keywords/hashtag (temÃ¡tica)
APIFY_ACTOR_FB_PAGES   = "apify/facebook-posts-scraper"              # por usuario/url (pages/groups)

# Polling / sync improvements
ASYNC_POLL_INTERVAL = 3
APIFY_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}
APIFY_RETRY_MAX_ATTEMPTS = 4
APIFY_RETRY_BASE_DELAY = 1.5

load_dotenv()

# =============================================================================
# SESSION STATE
# =============================================================================

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
    "execution_times": {},
    "apify_runs": []
}
for k, v in default_state.items():
    if k not in st.session_state:
        st.session_state[k] = v

def env(name: str) -> Optional[str]:
    try:
        return st.secrets.get(name) or os.getenv(name)
    except Exception:
        return os.getenv(name)

def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")

REQUIRE_LOGIN = env_bool("REQUIRE_LOGIN", True)
ENABLE_DEBUG_TOOLS = env_bool("ENABLE_DEBUG_TOOLS", False)
AI_FAST_MODE = env_bool("AI_FAST_MODE", True)
AI_MAX_TEXTS = int(env("AI_MAX_TEXTS") or 300)

def log_message(msg: str, level: str = "info", debug_data: Optional[Dict] = None):
    timestamp = datetime.now(SCL_TZ).strftime("%H:%M:%S.%f")[:-3]
    log_entry = f"[{timestamp}] {msg}"
    st.session_state["logs"].append(log_entry)

    if st.session_state.get("debug_mode", False):
        debug_entry = {
            "timestamp": timestamp,
            "level": level.upper(),
            "message": msg,
            "data": debug_data or {}
        }
        st.session_state["debug_logs"].append(debug_entry)

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
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start
                if st.session_state.get("debug_mode"):
                    st.session_state["execution_times"][func_name] = elapsed
                    log_message(f"{func_name} ejecutado en {elapsed:.2f}s", "debug")
                return result
            except Exception as e:
                elapsed = time.time() - start
                log_message(
                    f"{func_name} fallo despues de {elapsed:.2f}s: {str(e)}",
                    "error",
                    {"exception": str(e), "traceback": traceback.format_exc()}
                )
                raise
        return wrapper
    return decorator

# =============================================================================
# DEBUG PANEL
# =============================================================================

def render_debug_panel():
    if not st.session_state.get("debug_mode"):
        return

    st.sidebar.markdown("---")
    st.sidebar.subheader("Debug Tools")

    debug_tabs = st.sidebar.tabs(["Logs", "Tiempos", "Datos", "APIs"])

    with debug_tabs[0]:
        if st.button("Limpiar Logs", key="clear_logs"):
            st.session_state["debug_logs"] = []
            st.session_state["logs"] = []

        log_count = len(st.session_state.get("debug_logs", []))
        st.caption(f"Total: {log_count} entradas")

        if st.session_state.get("debug_logs"):
            log_df = pd.DataFrame(st.session_state["debug_logs"])
            st.dataframe(log_df.tail(20), use_container_width=True, height=200)
            log_json = json.dumps(st.session_state["debug_logs"], indent=2, default=str)
            st.download_button(
                "Exportar Logs JSON",
                log_json,
                "debug_logs.json",
                "application/json",
                key="download_logs"
            )

    with debug_tabs[1]:
        times = st.session_state.get("execution_times", {})
        if times:
            times_df = pd.DataFrame(
                [{"Funcion": k, "Tiempo (s)": f"{v:.3f}"} for k, v in sorted(times.items(), key=lambda x: x[1], reverse=True)]
            )
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
        apify_runs = st.session_state.get("apify_runs", [])
        if apify_runs:
            st.caption(f"Apify runs registrados: {len(apify_runs)}")
            st.dataframe(pd.DataFrame(apify_runs).tail(20), use_container_width=True, height=180)
        if responses:
            selected_api = st.selectbox("API", list(responses.keys()))
            if selected_api:
                st.json(responses[selected_api])
        elif not apify_runs:
            st.info("No hay respuestas de API registradas")

# =============================================================================
# LOGIN SEGURO
# =============================================================================
load_dotenv(override=False)

def login():
    st.title("Acceso Seguro")
    env_user = (env("ADMIN_USER") or "").strip()
    env_pass = (env("ADMIN_PASS") or "").strip()

    if not env_user or not env_pass:
        st.error("Configuracion incompleta de login.")
        st.info("Define ADMIN_USER y ADMIN_PASS en Streamlit Secrets para habilitar acceso.")
        st.stop()

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        with st.form("login_form"):
            user = st.text_input("Usuario")
            pwd = st.text_input("Contrasena", type="password")
            submit = st.form_submit_button("Iniciar sesion", use_container_width=True)

            if submit:
                if user.strip() == env_user and pwd.strip() == env_pass:
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas.")

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False

if not REQUIRE_LOGIN:
    st.session_state["logged_in"] = True
elif not st.session_state['logged_in']:
    login()
    st.stop()

# =============================================================================
# EXPORTS + EMAIL HELPERS
# =============================================================================

def fig_to_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    buf.seek(0)
    return buf.read()

_EXCEL_MAX_CELL_CHARS = 32767
_CTRL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

def limpiar_celda_excel(x: Any) -> str:
    """Limpia un valor individual para que Excel no falle."""
    if x is None:
        return ""

    try:
        na_flag = pd.isna(x)
    except Exception:
        na_flag = False

    if isinstance(na_flag, bool) and na_flag:
        return ""
    if hasattr(na_flag, "all"):
        try:
            if na_flag.all():
                return ""
        except Exception:
            pass

    if isinstance(x, (dict, list, tuple, set)):
        try:
            return json.dumps(x, ensure_ascii=False, default=str)
        except Exception:
            return str(x)

    if isinstance(x, (datetime, pd.Timestamp)):
        try:
            ts = pd.to_datetime(x, utc=True, errors="coerce")
            if pd.notna(ts):
                return ts.tz_localize(None).isoformat(sep=" ")
        except Exception:
            return str(x)

    s = str(x)
    s = _CTRL_CHARS_RE.sub(" ", s)
    if len(s) > _EXCEL_MAX_CELL_CHARS:
        s = s[:_EXCEL_MAX_CELL_CHARS - 3] + "..."
    return s

def sanitize_df_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    if df.empty:
        return df.copy()

    out = df.copy()

    for col in out.columns:
        try:
            if is_datetime64tz_dtype(out[col]):
                out[col] = pd.to_datetime(out[col], utc=True, errors='coerce').dt.tz_localize(None)
            elif is_datetime64_any_dtype(out[col]):
                out[col] = pd.to_datetime(out[col], errors='coerce')
        except Exception:
            out[col] = out[col].apply(limpiar_celda_excel)

    for col in out.columns:
        if out[col].dtype == 'object':
            out[col] = out[col].apply(limpiar_celda_excel)

    out.columns = [str(c)[:255] for c in out.columns]
    return out

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Convierte DataFrame a bytes Excel (robusto, sin duplicados)."""
    output = io.BytesIO()
    try:
        if df is None or df.empty:
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                pd.DataFrame().to_excel(writer, index=False, sheet_name='Datos')
            output.seek(0)
            return output.getvalue()

        safe_df = sanitize_df_for_excel(df)

        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            safe_df.to_excel(writer, index=False, sheet_name='Datos')

        output.seek(0)
        return output.getvalue()

    except Exception as e:
        log_message(f"Fallo Excel estandar: {e}. Intentando fallback texto plano.", "warning")
        try:
            output = io.BytesIO()
            fallback_df = df.copy()
            for col in fallback_df.columns:
                fallback_df[col] = fallback_df[col].apply(limpiar_celda_excel)

            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                fallback_df.to_excel(writer, index=False, sheet_name='Datos')
            output.seek(0)
            return output.getvalue()
        except Exception as e2:
            log_message(f"Error fatal en Excel fallback: {e2}", "error", {"traceback": traceback.format_exc()})
            return b""

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    if df is None:
        return b""
    safe_df = df.copy()
    for col in safe_df.columns:
        try:
            if is_datetime64tz_dtype(safe_df[col]):
                safe_df[col] = pd.to_datetime(safe_df[col], utc=True, errors="coerce").dt.tz_localize(None)
        except Exception:
            pass
    for col in safe_df.columns:
        if safe_df[col].dtype == "object":
            safe_df[col] = safe_df[col].apply(
                lambda x: json.dumps(x, ensure_ascii=False, default=str)
                if isinstance(x, (dict, list, tuple, set)) else x
            )
    return safe_df.to_csv(index=False).encode("utf-8")

@measure_time("send_email_report")
def send_email_report(to_email, subject, body, df_xlsx, df_csv, figures_dict):
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

    if df_xlsx:
        part = MIMEBase('application', "octet-stream")
        part.set_payload(df_xlsx)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="reporte_data.xlsx"')
        msg.attach(part)

    if df_csv:
        part = MIMEBase('application', "octet-stream")
        part.set_payload(df_csv)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment; filename="reporte_data.csv"')
        msg.attach(part)

    for name, fig_bytes in (figures_dict or {}).items():
        try:
            image = MIMEImage(fig_bytes, name=f"{name}.png")
            image.add_header('Content-Disposition', f'attachment; filename="{name}.png"')
            msg.attach(image)
        except Exception as e:
            log_message(f"No se pudo adjuntar imagen {name}: {e}", "warning")

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

# =============================================================================
# MOTOR IA (DEEPSEEK)
# =============================================================================

@measure_time("generate_executive_summary")
def generate_executive_summary(df: pd.DataFrame, query: str) -> str:
    key = env("DEEPSEEK_API_KEY")
    if not key:
        log_message("Falta DEEPSEEK_API_KEY", "warning")
        return "Resumen no disponible (Falta API Key)."
    if df.empty:
        return "Resumen no disponible (Sin datos)."

    total = len(df)
    sent_counts = df["sentiment"].value_counts(normalize=True).to_dict() if "sentiment" in df else {}

    if "likes" in df.columns and "text" in df.columns:
        top_posts = df.sort_values("likes", ascending=False).head(3)
        top_texts_list = []
        for _, row in top_posts.iterrows():
            user = row.get("username", "Anon")
            txt = str(row.get("text", ""))[:100].replace("\n", " ")
            likes = int(row.get("likes", 0) or 0)
            top_texts_list.append(f"- Usuario @{user}: '{txt}...' ({likes} likes)")
        top_posts_str = "\n".join(top_texts_list)
    else:
        top_posts_str = "No hay datos de likes disponibles."

    context = (
        f"Analisis para: '{query}'.\n"
        f"Volumen Total: {total} posts.\n"
        f"Sentimiento: {sent_counts.get('POS',0):.1%} Positivo, {sent_counts.get('NEG',0):.1%} Negativo.\n"
        f"TOP POSTS VIRALES:\n{top_posts_str}"
    )

    prompt = (
        f"Actua como un analista de inteligencia digital. "
        f"Escribe un 'Resumen Ejecutivo' breve (max 500 palabras) en espanol basado en los datos proporcionados.\n\n"
        f"DATOS:\n{context}\n\n"
        f"INSTRUCCIONES CLAVE:\n"
        f"1. Resume la tendencia general de sentimiento y emociones.\n"
        f"2. IMPORTANTE: Debes citar explicitamente al menos uno de los 'TOP POSTS VIRALES' mencionados.\n"
        f"3. Entrega un resumen de metricas: posteos, interacciones y visualizaciones si estan.\n"
        f"4. Tono profesional."
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
            },
            timeout=25
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

async def async_fetch_deepseek(client: httpx.AsyncClient, prompt: str, sem: asyncio.Semaphore, max_tokens: int = 10) -> str:
    deepseek_key = env("DEEPSEEK_API_KEY")
    if not deepseek_key:
        return "NEU"
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
            safe_text = (text or "")[:300]
            prompt = f"Clasifica el sentimiento: '{safe_text}'. Responde EXCLUSIVAMENTE con una palabra: POS, NEG o NEU."
            tasks.append(async_fetch_deepseek(client, prompt, sem, 5))
        results = await asyncio.gather(*tasks)

        final_results = []
        for r in results:
            if r in ["POS", "NEG", "NEU"]:
                final_results.append(r)
            elif "POS" in r:
                final_results.append("POS")
            elif "NEG" in r:
                final_results.append("NEG")
            else:
                final_results.append("NEU")
        return final_results

@measure_time("process_emotions_batch")
async def process_emotions_batch_async(texts: List[str]) -> List[str]:
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    valid_emotions = ["RISA", "IRA", "MIEDO", "TRISTEZA", "DISGUSTO", "SORPRESA", "NEUTRAL"]
    sem = asyncio.Semaphore(10)
    async with httpx.AsyncClient(base_url="https://api.deepseek.com", limits=limits, timeout=60.0) as client:
        tasks = []
        for text in texts:
            safe_text = (text or "")[:300]
            prompt = f"Detecta la emocion en: '{safe_text}'. Opciones: {', '.join(valid_emotions)}. Responde SOLO con la palabra clave."
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
            if not found:
                clean_results.append("NEUTRAL")
        return clean_results

def analyze_sentiment_deepseek_optimized(texts: List[str]) -> List[str]:
    if not texts:
        return []
    try:
        log_message(f"Analizando sentimiento de {len(texts)} textos", "debug")
        return asyncio.run(process_sentiment_batch_async(texts))
    except Exception as e:
        log_message(f"Error Sentiment Async: {e}", "error")
        return ["NEU"] * len(texts)

def analyze_emotions_deepseek_optimized(texts: List[str]) -> List[str]:
    if not texts:
        return []
    try:
        log_message(f"Analizando emociones de {len(texts)} textos", "debug")
        return asyncio.run(process_emotions_batch_async(texts))
    except Exception as e:
        log_message(f"Error Emotions Async: {e}", "error")
        return ["NEUTRAL"] * len(texts)

# =============================================================================
# APIFY CORE (API V2 mejorado)
# =============================================================================

def apify_headers(token: str) -> Dict[str, str]:
    # MÃ¡s seguro que ?token= en URL (evita leaks en logs/historial)
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def apify_timeout_for_limit(limit_hint: int, base_secs: int = 180, per_100_items: int = 20, max_secs: int = 900) -> int:
    safe_limit = max(1, int(limit_hint or 1))
    return min(max_secs, base_secs + ((safe_limit - 1) // 100) * per_100_items)

def _parse_retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        seconds = float(value.strip())
        return seconds if seconds >= 0 else None
    except Exception:
        return None

def apify_request_with_retry(
    method: str,
    url: str,
    token: str,
    timeout: int,
    params: Optional[Dict[str, Any]] = None,
    json_payload: Optional[Dict[str, Any]] = None,
    op_name: str = "apify_request"
) -> Optional[requests.Response]:
    last_response: Optional[requests.Response] = None
    for attempt in range(1, APIFY_RETRY_MAX_ATTEMPTS + 1):
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                headers=apify_headers(token),
                params=params,
                json=json_payload,
                timeout=timeout
            )
            last_response = response
            if response.status_code not in APIFY_RETRYABLE_STATUS:
                return response

            if attempt == APIFY_RETRY_MAX_ATTEMPTS:
                break

            retry_after = _parse_retry_after_seconds(response.headers.get("Retry-After"))
            backoff = APIFY_RETRY_BASE_DELAY * (2 ** (attempt - 1))
            wait_time = retry_after if retry_after is not None else (backoff + random.uniform(0, 0.75))
            log_message(
                f"{op_name}: status {response.status_code}, reintento {attempt}/{APIFY_RETRY_MAX_ATTEMPTS} en {wait_time:.2f}s",
                "warning"
            )
            time.sleep(wait_time)
        except requests.RequestException as exc:
            if attempt == APIFY_RETRY_MAX_ATTEMPTS:
                log_message(f"{op_name}: excepcion final {exc}", "error")
                break
            backoff = APIFY_RETRY_BASE_DELAY * (2 ** (attempt - 1)) + random.uniform(0, 0.75)
            log_message(
                f"{op_name}: excepcion {exc}, reintento {attempt}/{APIFY_RETRY_MAX_ATTEMPTS} en {backoff:.2f}s",
                "warning"
            )
            time.sleep(backoff)
    return last_response

def canonicalize_post_url(raw_url: Optional[str]) -> Optional[str]:
    if not raw_url:
        return None
    try:
        parsed = urlparse(str(raw_url).strip())
        if not parsed.scheme or not parsed.netloc:
            return str(raw_url).strip()
        clean_query = [
            (k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
            if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "ref"}
        ]
        normalized_path = parsed.path.rstrip("/")
        normalized = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            path=normalized_path,
            query=urlencode(clean_query, doseq=True),
            fragment=""
        )
        return urlunparse(normalized)
    except Exception:
        return str(raw_url).strip()

def dedup_normalized_posts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    unique = []
    for row in rows:
        row_id = str(row.get("id") or "").strip()
        row_url = canonicalize_post_url(row.get("url"))
        text = str(row.get("text") or "").strip().lower()
        created = str(row.get("created_at") or "").strip()
        if not (row_id or row_url or text or created):
            unique.append(row)
            continue
        key = (row_id, row_url, text[:120], created)
        if key in seen:
            continue
        seen.add(key)
        row["url"] = row_url or row.get("url")
        unique.append(row)
    return unique

@measure_time("apify_dataset_items_paginated")
def apify_dataset_items_paginated(dataset_id: str, token: str, limit_total: int = 5000) -> List[Dict]:
    """Descarga items con paginaciÃ³n limit/offset (robusto)."""
    items: List[Dict] = []
    offset = 0
    page_limit = 1000  # Apify puede capear; se ajusta por respuesta
    while True:
        url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
        params = {
            "format": "json",
            "clean": "1",
            "limit": page_limit,
            "offset": offset
        }
        r = apify_request_with_retry(
            method="GET",
            url=url,
            token=token,
            timeout=60,
            params=params,
            op_name=f"dataset_items:{dataset_id}"
        )
        if r is None or r.status_code != 200:
            status = r.status_code if r is not None else "no_response"
            txt = r.text[:300] if r is not None else ""
            log_message(f"Error dataset items {dataset_id}: {status}", "warning", {"text": txt})
            break

        batch = r.json()
        if not isinstance(batch, list):
            # dataset-items-get suele retornar array para /items, pero igual protegemos
            batch = batch.get("data", {}).get("items", [])

        if not batch:
            break

        items.extend(batch)
        offset += len(batch)

        if st.session_state.get("debug_mode"):
            st.session_state["api_responses"][f"apify_dataset_{dataset_id}_page_{offset}"] = {"count": len(batch), "offset": offset}

        if len(items) >= limit_total:
            items = items[:limit_total]
            break

        # Si el batch vino mÃ¡s chico, se acabÃ³
        if len(batch) < page_limit:
            break

    return items

@measure_time("run_apify_actor_v2")
def run_apify_actor_v2(actor_id: str, tokens: List[str], payload: Dict, timeout_secs: int = 300) -> List[Dict]:
    """
    Arranca un actor y espera SUCCEEDED (robusto):
    - POST /v2/acts/:actorId/runs
    - Poll /v2/actor-runs/:runId?waitForFinish=60 (reduce polling)
    - Descarga dataset resultante con paginaciÃ³n
    """
    valid_tokens = [t for t in tokens if t and t.strip()]
    if not valid_tokens:
        log_message("No hay tokens Apify validos", "warning")
        return []

    actor_path = actor_id.replace("/", "~")
    for i, token in enumerate(valid_tokens):
        run_metrics = {
            "actor_id": actor_id,
            "token_attempt": i + 1,
            "started_at": datetime.now(SCL_TZ).isoformat(),
            "status": "NOT_STARTED",
            "run_id": None,
            "dataset_id": None,
            "duration_secs": None,
            "items_count": 0
        }
        started = time.time()
        try:
            url_run = f"https://api.apify.com/v2/acts/{actor_path}/runs"
            log_message(f"Iniciando actor {actor_id} (intento {i+1}/{len(valid_tokens)})", "debug", {"payload": payload})

            r = apify_request_with_retry(
                method="POST",
                url=url_run,
                token=token,
                timeout=30,
                json_payload=payload,
                op_name=f"run_start:{actor_id}"
            )
            if r is None or r.status_code not in [200, 201]:
                status = r.status_code if r is not None else "no_response"
                txt = r.text[:300] if r is not None else ""
                log_message(f"Error iniciando actor: {status}", "warning", {"text": txt})
                run_metrics["status"] = "START_FAILED"
                run_metrics["duration_secs"] = round(time.time() - started, 2)
                st.session_state["apify_runs"].append(run_metrics)
                continue

            run_data = r.json().get("data") or r.json().get("data", {})
            run_id = run_data.get("id")
            dataset_id = run_data.get("defaultDatasetId")
            run_metrics["run_id"] = run_id
            run_metrics["dataset_id"] = dataset_id

            if not run_id:
                log_message("No vino run_id desde Apify", "error", {"resp": r.text[:500]})
                run_metrics["status"] = "MISSING_RUN_ID"
                run_metrics["duration_secs"] = round(time.time() - started, 2)
                st.session_state["apify_runs"].append(run_metrics)
                continue

            log_message(f"Actor iniciado - Run ID: {run_id}", "info", {"dataset_id": dataset_id})

            start_time = time.time()
            status = "RUNNING"
            final_data = None

            while time.time() - start_time < timeout_secs:
                # waitForFinish reduce polling (mÃ¡x 60s por request)
                poll_url = f"https://api.apify.com/v2/actor-runs/{run_id}"
                r_poll = apify_request_with_retry(
                    method="GET",
                    url=poll_url,
                    token=token,
                    timeout=75,
                    params={"waitForFinish": 60},
                    op_name=f"run_poll:{run_id}"
                )
                if r_poll is None or r_poll.status_code != 200:
                    status = r_poll.status_code if r_poll is not None else "no_response"
                    log_message(f"Error polling run {run_id}: {status}", "warning")
                    time.sleep(ASYNC_POLL_INTERVAL)
                    continue

                final_data = r_poll.json().get("data", {})
                status = final_data.get("status", status)
                log_message(f"Estado actor: {status}", "debug")

                if status == "SUCCEEDED":
                    dataset_id = dataset_id or final_data.get("defaultDatasetId")
                    break
                if status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                    log_message(f"Actor fallo con estado: {status}", "error", {"run": final_data})
                    break

            if status != "SUCCEEDED":
                run_metrics["status"] = status
                run_metrics["dataset_id"] = dataset_id
                run_metrics["duration_secs"] = round(time.time() - started, 2)
                st.session_state["apify_runs"].append(run_metrics)
                continue

            if not dataset_id:
                log_message("Run SUCCEEDED pero sin defaultDatasetId", "warning", {"run": final_data})
                run_metrics["status"] = "SUCCEEDED_NO_DATASET"
                run_metrics["duration_secs"] = round(time.time() - started, 2)
                st.session_state["apify_runs"].append(run_metrics)
                return []

            items = apify_dataset_items_paginated(
                dataset_id,
                token,
                limit_total=int(payload.get("maxItems") or payload.get("resultsLimit") or payload.get("resultsCount") or 5000)
            )
            run_metrics["status"] = "SUCCEEDED"
            run_metrics["dataset_id"] = dataset_id
            run_metrics["duration_secs"] = round(time.time() - started, 2)
            run_metrics["items_count"] = len(items)
            st.session_state["apify_runs"].append(run_metrics)
            return items

        except Exception as e:
            log_message(f"Excepcion en run_apify_actor_v2: {e}", "error", {"traceback": traceback.format_exc()})
            run_metrics["status"] = "EXCEPTION"
            run_metrics["duration_secs"] = round(time.time() - started, 2)
            st.session_state["apify_runs"].append(run_metrics)
            continue

    return []

# =============================================================================
# NORMALIZACIÃ“N
# =============================================================================

@measure_time("normalize_common")
def normalize_common_optimized(rows: List[Dict], platform: str) -> pd.DataFrame:
    log_message(f"Normalizando {len(rows)} filas de {platform}", "debug")
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    col_map = {
        "text": ["caption", "description", "title", "text", "message", "postText", "content", "postTextTranslated"],
        "likes": ["likeCount", "likesCount", "diggCount", "likes", "reactionCount", "likes_count", "like_count"],
        "comments": ["commentCount", "commentsCount", "comments", "comments_count"],
        "shares": ["shareCount", "retweetCount", "shares", "share_count"],
        "views": ["playCount", "viewCount", "videoPlayCount", "views", "views_count"],
        "followers": ["followers", "followersCount", "fans", "followerCount", "userFollowers"],
        "created_at": ["timestamp", "takenAt", "createTimeISO", "createdAt", "date", "time", "publishedAt", "posted_date"]
    }

    for target, candidates in col_map.items():
        if target not in df.columns:
            for c in candidates:
                if c in df.columns:
                    df[target] = df[c]
                    break
            if target not in df.columns:
                df[target] = 0 if target in ["likes", "comments", "shares", "views", "followers"] else None

    if "created_at" in df.columns:
        try:
            df["created_at_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
            df["fecha_cl"] = df["created_at_utc"].dt.date
            df["created_at_display"] = df["created_at_utc"].dt.tz_localize(None)

            failed = df["created_at_utc"].isna().sum()
            if failed > 0:
                log_message(f"{failed} fechas no convertidas", "warning")
        except Exception as e:
            log_message(f"Error en conversion de fechas: {e}", "error")
            df["created_at_utc"] = pd.NaT
            df["fecha_cl"] = None
            df["created_at_display"] = pd.NaT

    if "username" not in df.columns:
        for c in ["ownerUsername", "authorUsername", "username", "author", "pageName", "profileName"]:
            if c in df.columns:
                df["username"] = df[c].apply(lambda x: x.get('name') if isinstance(x, dict) else x)
                break
        if "username" not in df.columns:
            df["username"] = "unknown"

    if "url" not in df.columns:
        for c in ["postUrl", "link", "permalink", "href"]:
            if c in df.columns:
                df["url"] = df[c]
                break
        if "url" not in df.columns:
            df["url"] = None

    if "text" in df.columns:
        df["text"] = df["text"].fillna("").astype(str)

    for col in ["likes", "comments", "shares", "views", "followers"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)

    df["platform"] = platform
    log_message(f"Normalizacion completa: {df.shape}", "debug")
    return df

# =============================================================================
# FETCHERS
# =============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_x_cached(api_key: str, query: str, limit: int) -> pd.DataFrame:
    log_message(f"Fetching X con query: {query}", "info")
    headers = {"x-api-key": api_key}
    all_rows = []
    cursor = None
    max_loops = (limit // 20) + 5

    for loop_num in range(max_loops):
        params = {"query": query, "queryType": "Latest"}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(API_URL_X, headers=headers, params=params, timeout=20)

            if st.session_state.get("debug_mode"):
                st.session_state["api_responses"][f"x_request_{loop_num}"] = {
                    "status_code": r.status_code,
                    "cursor": cursor,
                    "tweets_count": len(r.json().get("tweets", [])) if r.status_code == 200 else 0
                }

            if r.status_code != 200:
                log_message(f"Error API X: {r.status_code}", "warning", {"text": r.text[:250]})
                break

            data = r.json()
            tweets = data.get("tweets", [])
            if not tweets:
                break

            for t in tweets:
                u = t.get("author", {}) or {}
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

            if len(all_rows) >= limit:
                break

            cursor = data.get("next_cursor") if data.get("has_next_page") else None
            if not cursor:
                break

        except Exception as e:
            log_message(f"Excepcion en fetch_x: {e}", "error", {"traceback": traceback.format_exc()})
            break

    log_message(f"Total tweets obtenidos: {len(all_rows)}", "info")
    return normalize_common_optimized(all_rows, "x")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_facebook_cached(tokens: List[str], query: str, limit: int, mode: str, location: Optional[str] = None, fb_search_type: str = "latest") -> pd.DataFrame:
    """
    Facebook:
    - mode == "search" => usa scraper_one/facebook-posts-search (query/resultsCount/searchType/location) para temÃ¡tica.
    - mode == "user"   => usa apify/facebook-posts-scraper (startUrls) para pÃ¡ginas/usuarios/urls.
    """
    if mode == "search":
        log_message(f"Fetching Facebook SEARCH: {query}", "info")
        effective_limit = max(1, min(100, int(limit)))
        if effective_limit < int(limit):
            log_message(
                f"Facebook SEARCH permite maximo 100 resultados por ejecucion, se ajusta de {limit} a {effective_limit}",
                "warning"
            )
        payload = {
            "query": query,
            "resultsCount": effective_limit,  # actor schema: 1..100
            "searchType": "latest" if fb_search_type == "latest" else "top"
        }
        if location:
            payload["location"] = location

        timeout_secs = apify_timeout_for_limit(effective_limit)
        items = run_apify_actor_v2(APIFY_ACTOR_FB_SEARCH, tokens, payload, timeout_secs=timeout_secs)

        # Normalizamos campos tÃ­picos que vienen de distintos actores
        normalized = []
        for i in items:
            normalized.append({
                "id": i.get("postId") or i.get("id"),
                "text": i.get("text") or i.get("content") or i.get("postText") or i.get("message"),
                "username": (i.get("author") or {}).get("name") or (i.get("user") or {}).get("name") or i.get("pageName"),
                "likes": i.get("likes") or i.get("reactionCount") or i.get("reactions") or 0,
                "comments": i.get("comments") or i.get("commentCount") or 0,
                "shares": i.get("shares") or i.get("shareCount") or 0,
                "url": i.get("url") or i.get("postUrl") or i.get("permalink"),
                "created_at": i.get("time") or i.get("timestamp") or i.get("publishedAt"),
            })
        normalized = dedup_normalized_posts(normalized)
        return normalize_common_optimized(normalized, "facebook")

    # mode == "user"
    log_message(f"Fetching Facebook USER/URL: {query}", "info")
    payload = {"resultsLimit": int(limit), "maxPosts": int(limit)}
    actor = APIFY_ACTOR_FB_PAGES

    urls = []
    for u in query.split(","):
        u = u.strip()
        if not u:
            continue
        if "facebook.com" in u:
            urls.append({"url": u})
        else:
            urls.append({"url": f"https://www.facebook.com/{u}"})
    payload["startUrls"] = urls

    timeout_secs = apify_timeout_for_limit(int(limit))
    items = run_apify_actor_v2(actor, tokens, payload, timeout_secs=timeout_secs)

    normalized = []
    for i in items:
        normalized.append({
            "id": i.get("postId") or i.get("id"),
            "text": i.get("text") or i.get("postText") or i.get("message"),
            "username": (i.get("user") or {}).get("name") or i.get("pageName"),
            "likes": i.get("likes", 0),
            "comments": i.get("comments", 0),
            "shares": i.get("shares", 0),
            "url": i.get("url") or i.get("postUrl"),
            "created_at": i.get("time") or i.get("timestamp")
        })
    normalized = dedup_normalized_posts(normalized)
    return normalize_common_optimized(normalized, "facebook")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_instagram_cached(tokens: List[str], query: str, limit: int, mode: str) -> pd.DataFrame:
    """
    Instagram:
    - mode == "hashtag" => apidojo/instagram-hashtag-scraper con startUrls o keyword
    - mode == "keyword" => apidojo/instagram-hashtag-scraper con keyword (tema/palabra) => posts/captions
    - mode == "user"    => apify/instagram-post-scraper por usernames (posts)
    """
    if mode == "keyword":
        log_message(f"Fetching Instagram KEYWORD: {query}", "info")
        keywords = [k.strip().replace("#", "") for k in re.split(r"[,;\n]+", query or "") if k.strip()]
        items: List[Dict] = []

        for kw in keywords:
            payload = {
                "keyword": kw,
                "getPosts": True,
                "getReels": True,
                "maxItems": int(limit)
            }
            batch = run_apify_actor_v2(
                APIFY_ACTOR_IG_HASHTAG,
                tokens,
                payload,
                timeout_secs=apify_timeout_for_limit(int(limit))
            )
            if batch:
                items.extend(batch)
            if len(items) >= int(limit):
                break

        if not items and keywords:
            # Fallback con startUrls por hashtag para mejorar recall
            start_urls = [f"https://www.instagram.com/explore/tags/{kw}/" for kw in keywords]
            payload = {
                "startUrls": start_urls,
                "getPosts": True,
                "getReels": True,
                "maxItems": int(limit)
            }
            items = run_apify_actor_v2(
                APIFY_ACTOR_IG_HASHTAG,
                tokens,
                payload,
                timeout_secs=apify_timeout_for_limit(int(limit))
            )

        if items:
            # Dedup por id/url para evitar repetidos al combinar keywords
            seen = set()
            unique = []
            for it in items:
                dedup_key = str(it.get("id") or it.get("postId") or it.get("url") or it.get("postUrl") or "")
                if dedup_key and dedup_key in seen:
                    continue
                if dedup_key:
                    seen.add(dedup_key)
                unique.append(it)
            items = unique[: int(limit)]

        return normalize_common_optimized(items, "instagram")

    if mode == "hashtag":
        log_message(f"Fetching Instagram HASHTAG: {query}", "info")
        # Este actor espera startUrls como lista de strings
        start_urls = []
        for h in query.split(","):
            h = h.strip().replace("#", "")
            if not h:
                continue
            start_urls.append(f"https://www.instagram.com/explore/tags/{h}/")
        payload = {
            "startUrls": start_urls,
            "getPosts": True,
            "getReels": True,
            "maxItems": int(limit)
        }
        items = run_apify_actor_v2(
            APIFY_ACTOR_IG_HASHTAG,
            tokens,
            payload,
            timeout_secs=apify_timeout_for_limit(int(limit))
        )
        return normalize_common_optimized(items, "instagram")

    # mode == "user"
    log_message(f"Fetching Instagram USER: {query}", "info")
    payload = {
        "usernames": [u.strip().lstrip("@") for u in query.split(",") if u.strip()],
        "resultsLimit": int(limit),
        "resultsType": "posts"
    }
    items = run_apify_actor_v2(
        APIFY_ACTOR_IG_POSTS,
        tokens,
        payload,
        timeout_secs=apify_timeout_for_limit(int(limit))
    )
    return normalize_common_optimized(items, "instagram")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tiktok_cached(tokens: List[str], query: str, limit: int, mode: str) -> pd.DataFrame:
    log_message(f"Fetching TikTok ({mode}): {query}", "info")
    payload = {"resultsPerPage": 100, "shouldDownloadVideos": False, "limit": int(limit)}
    if mode == "user":
        payload["usernames"] = [u.strip().lstrip("@") for u in query.split(",") if u.strip()]
    else:
        payload["hashtags"] = [h.strip().replace("#", "") for h in query.split(",") if h.strip()]
    items = run_apify_actor_v2(
        "clockworks/tiktok-scraper",
        tokens,
        payload,
        timeout_secs=apify_timeout_for_limit(int(limit))
    )
    return normalize_common_optimized(items, "tiktok")

# =============================================================================
# FILTRO FECHAS
# =============================================================================

def enforce_date_window(df: pd.DataFrame, d1: Optional[date], d2: Optional[date], include_undated: bool = False) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    if "fecha_cl" not in df.columns:
        log_message("Columna 'fecha_cl' no encontrada, saltando filtrado", "warning")
        return df

    current = datetime.now(SCL_TZ).date()
    if d1 and d1 > current:
        log_message(f"Ajustando fecha 'desde' futura: {d1} -> {current}", "warning")
        d1 = current
    if d2 and d2 > current:
        log_message(f"Ajustando fecha 'hasta' futura: {d2} -> {current}", "warning")
        d2 = current

    try:
        def safe_date_str(x):
            if pd.isna(x):
                return None
            try:
                if isinstance(x, str):
                    return x[:10]
                elif isinstance(x, date):
                    return x.isoformat()
                elif isinstance(x, pd.Timestamp):
                    return x.date().isoformat()
                elif hasattr(x, 'strftime'):
                    return pd.to_datetime(x).date().isoformat()
                else:
                    return str(x)[:10]
            except Exception:
                return None

        df_work = df.copy()
        df_work["_fecha_str"] = df_work["fecha_cl"].apply(safe_date_str)

        d1_str = d1.isoformat() if d1 else None
        d2_str = d2.isoformat() if d2 else None

        mask = pd.Series(True, index=df_work.index)
        if d1_str:
            if include_undated:
                mask &= ((df_work["_fecha_str"] >= d1_str) | (df_work["_fecha_str"].isna()))
            else:
                mask &= (df_work["_fecha_str"] >= d1_str)
        if d2_str:
            if include_undated:
                mask &= ((df_work["_fecha_str"] <= d2_str) | (df_work["_fecha_str"].isna()))
            else:
                mask &= (df_work["_fecha_str"] <= d2_str)

        filtered = df.loc[mask].copy()
        removed = len(df) - len(filtered)
        log_message(f"Filtrado: {len(df)} -> {len(filtered)} ({removed} removidos)", "info")

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
                    "include_undated": include_undated,
                    "null_dates": df_work["_fecha_str"].isna().sum(),
                    "fecha_cl_dtype": str(df["fecha_cl"].dtype),
                    "sample_dates": df_work["_fecha_str"].dropna().head(3).tolist()
                }
            )

        return filtered

    except Exception as e:
        log_message(f"Error en filtrado: {e}", "error", {"traceback": traceback.format_exc()})
        st.warning(f"Error al filtrar fechas: {e}. Mostrando todos los datos.")
        return df

# =============================================================================
# VISUALES + NLP
# =============================================================================

def plot_pie_chart(series, title):
    if series is None or series.empty:
        return None
    counts = series.value_counts()
    fig, ax = plt.subplots(figsize=(6, 6))
    fig.patch.set_facecolor('white')
    ax.pie(counts, labels=counts.index, autopct='%1.1f%%', startangle=90)
    ax.set_title(title, fontsize=12, fontweight='bold')
    return fig

def plot_bar_chart(series, title, color_hex="#3498db"):
    if series is None or series.empty:
        return None
    counts = series.value_counts()
    fig, ax = plt.subplots(figsize=(6, 5))
    fig.patch.set_facecolor('white')
    ax.bar(counts.index, counts.values, color=color_hex)
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
    if not blob.strip():
        return None
    wc = WordCloud(width=1200, height=500, background_color="white", max_words=max_words, colormap="viridis").generate(blob)
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.imshow(wc, interpolation='bilinear')
    ax.axis("off")
    return fig

def extract_topics(texts: List[str], top_n: int = 10) -> Dict[str, int]:
    blob = clean_texts(pd.Series(texts))
    return dict(Counter(blob.split()).most_common(top_n))

@measure_time("select_ai_subset")
def select_ai_subset(df: pd.DataFrame, max_texts: int, fast_mode: bool) -> List[Any]:
    if df is None or df.empty:
        return []
    if not fast_mode or max_texts <= 0 or len(df) <= max_texts:
        return df.index.tolist()

    score_cols = [c for c in ["likes", "comments", "shares", "views"] if c in df.columns]
    if score_cols:
        ranked = df.copy()
        ranked["_ai_score"] = 0
        for col in score_cols:
            ranked["_ai_score"] = ranked["_ai_score"] + pd.to_numeric(ranked[col], errors="coerce").fillna(0)
        selected = ranked.sort_values("_ai_score", ascending=False).head(max_texts).index.tolist()
    else:
        selected = df.sample(n=max_texts, random_state=42).index.tolist()

    log_message(
        f"AI fast-mode activo: analizando muestra {len(selected)}/{len(df)} posts",
        "info",
        {"fast_mode": fast_mode, "max_texts": max_texts}
    )
    return selected

@measure_time("detect_crisis_signals")
def detect_crisis_signals(df: pd.DataFrame) -> Dict[str, Any]:
    if df.empty:
        return {"score": 0, "severity": "none", "signals": [], "crisis_posts": pd.DataFrame()}

    signals = []
    crisis_score = 0
    keywords = ["crisis", "emergencia", "caida", "fallo", "problema", "error", "incidente", "demanda", "denuncia", "escandalo", "fraude", "robo", "ataque"]

    if "sentiment" in df.columns:
        neg_ratio = (df["sentiment"] == "NEG").sum() / max(1, len(df))
        if neg_ratio > 0.3:
            signals.append(f"Sentimiento negativo alto: {neg_ratio*100:.1f}%")
            crisis_score += 25

    crisis_posts = pd.DataFrame()
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
                    signals.append(f"{len(influencers)} cuenta(s) influyente(s) involucrada(s)")

    crisis_score = min(100, crisis_score)
    severity = "critical" if crisis_score >= 80 else "high" if crisis_score >= 60 else "medium" if crisis_score >= 30 else "low"

    log_message(f"Deteccion de crisis: score={crisis_score}, severity={severity}", "info", {"signals": signals})
    return {"score": crisis_score, "severity": severity, "signals": signals, "crisis_posts": crisis_posts}

# =============================================================================
# X QUERY BUILDERS
# =============================================================================

def compose_query_x(topic: str, lang: str, exclude_rt: bool, exclude_repl: bool, d1: Optional[date], d2: Optional[date], filter_chile: bool) -> str:
    q = (topic or "").strip()
    if not q.startswith("("):
        q = f"({q})"
    if lang:
        q += f" lang:{lang}"
    if exclude_rt:
        q += " -is:retweet"
    if exclude_repl:
        q += " -is:reply"
    if filter_chile:
        q += " place_country:CL"
    if d1:
        q += f" since:{d1.isoformat()}_00:00:00_UTC"
    if d2:
        q += f" until:{(d2 + timedelta(days=1)).isoformat()}_00:00:00_UTC"
    log_message(f"Query X generado: {q}", "debug")
    return q

def compose_query_x_user(username: str, lang: str, exclude_rt: bool, exclude_repl: bool, d1: Optional[date], d2: Optional[date], filter_chile: bool) -> str:
    u = (username or "").strip().lstrip("@")
    q = f"from:{u}"
    if lang:
        q += f" lang:{lang}"
    if exclude_rt:
        q += " -is:retweet"
    if exclude_repl:
        q += " -is:reply"
    if filter_chile:
        q += " place_country:CL"
    if d1:
        q += f" since:{d1.isoformat()}_00:00:00_UTC"
    if d2:
        q += f" until:{(d2 + timedelta(days=1)).isoformat()}_00:00:00_UTC"
    log_message(f"Query X user generado: {q}", "debug")
    return q

# =============================================================================
# UI
# =============================================================================

st.title("Social Listening Pro - X + Instagram + Facebook + TikTok")
st.markdown("**Analisis avanzado con deteccion de crisis, sentimiento y reporte por email**")

st.sidebar.header("Configuracion")

st.sidebar.markdown("---")
if ENABLE_DEBUG_TOOLS:
    debug_mode = st.sidebar.checkbox(
        "Modo Debug",
        value=st.session_state.get("debug_mode", False),
        key="toggle_debug_mode"
    )
else:
    debug_mode = False
st.session_state["debug_mode"] = debug_mode
if debug_mode:
    st.sidebar.info("Modo Debug activo. Ver panel abajo.")
st.sidebar.markdown("---")

platform = st.sidebar.selectbox("Plataforma", ["X (Twitter)", "Instagram", "Facebook", "TikTok"])

if platform == "Instagram":
    search_mode = st.sidebar.radio("Modo", ["Por tematica (hashtags)", "Por tematica (busqueda IG)", "Por usuario"])
elif platform == "Facebook":
    search_mode = st.sidebar.radio("Modo", ["Por tematica", "Por usuario"])
else:
    search_mode = st.sidebar.radio("Modo", ["Por tematica", "Por usuario"])

topic = ""
username_input = ""
hashtags_str = ""

if search_mode.startswith("Por tematica"):
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
filter_chile = st.sidebar.checkbox("Filtrar solo Chile (X)")

# Facebook search extras
fb_search_type = "latest"
fb_location = None
if platform == "Facebook" and search_mode == "Por tematica":
    fb_search_type = st.sidebar.selectbox("FB Search Type", ["latest", "top"], index=0)
    fb_location = st.sidebar.text_input("FB Location (opcional)", placeholder="Santiago, Chile")

st.sidebar.divider()

current_date_cl = datetime.now(SCL_TZ).date()
default_start = current_date_cl - timedelta(days=14)

d1 = st.sidebar.date_input("Desde", value=default_start, max_value=current_date_cl, key="date_input_from")
d2 = st.sidebar.date_input("Hasta", value=current_date_cl, max_value=current_date_cl, min_value=d1 if d1 else None, key="date_input_to")

if d1 and d2 and d1 > d2:
    st.sidebar.error("Fecha 'Desde' no puede ser posterior a 'Hasta'")

limit = st.sidebar.slider("Limite de posts", 50, 2000, 200)
if platform == "Facebook" and search_mode == "Por tematica" and limit > 100:
    st.sidebar.warning("Facebook por tematica permite maximo 100 posts por ejecucion. Se usara 100.")
max_words = st.sidebar.slider("Max. palabras nube", 50, 500, 200)
include_undated_posts = st.sidebar.checkbox("Incluir posts sin fecha", value=False)

sentiment = st.sidebar.checkbox("Analizar Sentimiento", value=True)
emotions = st.sidebar.checkbox("Analizar Emociones", value=False)

ai_fast_mode_runtime = AI_FAST_MODE
ai_max_texts_runtime = AI_MAX_TEXTS
if ENABLE_DEBUG_TOOLS and debug_mode:
    st.sidebar.markdown("### IA (Debug/Admin)")
    ai_fast_mode_runtime = st.sidebar.checkbox(
        "IA modo rapido",
        value=AI_FAST_MODE,
        help="Si se activa, sentimiento/emociones se calculan sobre una muestra priorizada."
    )
    if ai_fast_mode_runtime:
        ai_max_texts_runtime = st.sidebar.slider(
            "IA maximo textos",
            min_value=50,
            max_value=2000,
            value=max(50, min(AI_MAX_TEXTS, 2000)),
            step=50,
            help="Cantidad maxima de textos a enviar a IA en modo rapido."
        )

st.sidebar.divider()

st.sidebar.subheader("Credenciales API")

env_x = env("TWITTERAPI_IO_KEY")
if env_x:
    api_x = env_x
    st.sidebar.success("X API cargada desde secrets/config")
else:
    api_x = None
    st.sidebar.error("X API no configurada (define TWITTERAPI_IO_KEY en Streamlit Secrets)")

env_apify = env("APIFY_TOKEN")
if env_apify:
    api_apify = env_apify
    st.sidebar.success("Apify Token cargado desde secrets/config")
else:
    api_apify = None
    st.sidebar.error("Apify Token no configurado (define APIFY_TOKEN en Streamlit Secrets)")

st.sidebar.divider()

run_btn = st.sidebar.button("Buscar", type="primary", use_container_width=True)

if debug_mode:
    render_debug_panel()

# =============================================================================
# EJECUCION
# =============================================================================

if run_btn:
    st.session_state["logs"] = []
    st.session_state["debug_logs"] = []
    st.session_state["execution_times"] = {}
    st.session_state["api_responses"] = {}
    st.session_state["report_figures"] = {}
    st.session_state["ai_summary"] = None
    st.session_state["apify_runs"] = []

    log_message("Iniciando busqueda", "info")
    prog = st.progress(0.0, text="Iniciando...")
    df = pd.DataFrame()
    tokens = [t for t in [api_apify] if t]

    try:
        prog.progress(0.1, text="Obteniendo datos...")

        if platform.startswith("X"):
            if not api_x:
                st.error("Falta API Key X. Configura TWITTERAPI_IO_KEY en Streamlit Secrets.")
                log_message("API Key X no configurada", "error")
                st.stop()
            if "usuario" in search_mode:
                q = compose_query_x_user(username_input, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            else:
                q = compose_query_x(topic, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            df = fetch_x_cached(api_x, q, limit)

        elif platform == "Facebook":
            if not tokens:
                st.error("Falta Token Apify. Configura APIFY_TOKEN en Streamlit Secrets.")
                log_message("Token Apify no configurada", "error")
                st.stop()
            mode = "user" if "usuario" in search_mode else "search"
            q = username_input if mode == "user" else topic
            df = fetch_facebook_cached(tokens, q, limit, mode, location=fb_location, fb_search_type=fb_search_type)

        elif platform == "Instagram":
            if not tokens:
                st.error("Falta Token Apify. Configura APIFY_TOKEN en Streamlit Secrets.")
                log_message("Token Apify no configurada", "error")
                st.stop()
            search_mode_norm = unidecode((search_mode or "").lower())
            mode = "hashtag" if "hashtag" in search_mode_norm else "keyword" if "busqueda" in search_mode_norm else "user"
            q = hashtags_str if mode == "hashtag" else (username_input if mode == "user" else topic)
            df = fetch_instagram_cached(tokens, q, limit, mode)

        elif platform == "TikTok":
            if not tokens:
                st.error("Falta Token Apify. Configura APIFY_TOKEN en Streamlit Secrets.")
                log_message("Token Apify no configurada", "error")
                st.stop()
            mode = "user" if "usuario" in search_mode else "hashtag"
            q = username_input if mode == "user" else topic
            df = fetch_tiktok_cached(tokens, q, limit, mode)

        prog.progress(0.3, text="Aplicando filtros de fecha...")

        try:
            df = enforce_date_window(df, d1, d2, include_undated=include_undated_posts)
        except Exception as date_error:
            log_message(
                f"Error al filtrar fechas: {date_error}",
                "error",
                {"d1": str(d1), "d2": str(d2), "traceback": traceback.format_exc()}
            )
            st.warning("No se pudo aplicar el filtro de fechas. Mostrando todos los resultados.")

        prog.progress(0.4, text="Verificando datos...")

        if df.empty:
            st.warning("No se encontraron resultados.")
            log_message("Busqueda sin resultados", "warning")
            st.stop()

        log_message(f"Obtenidos {len(df)} posts", "info")

        prog.progress(0.5, text="Procesando IA...")

        if "text" in df.columns:
            ai_idx = select_ai_subset(df, ai_max_texts_runtime, ai_fast_mode_runtime)
            if len(ai_idx) < len(df):
                st.info(
                    f"Modo rapido IA activo: se analizaron {len(ai_idx)} de {len(df)} posts "
                    f"(configurable con AI_FAST_MODE/AI_MAX_TEXTS)."
                )
            elif not ai_fast_mode_runtime:
                st.info("Modo precision IA activo: se analizaron todos los posts.")
            texts_ai = df.loc[ai_idx, "text"].tolist() if ai_idx else []

            if sentiment:
                prog.progress(0.6, text="Analizando sentimiento...")
                with st.spinner("DeepSeek Sentimiento..."):
                    df["sentiment"] = "NEU"
                    if texts_ai:
                        sent_ai = analyze_sentiment_deepseek_optimized(texts_ai)
                        df.loc[ai_idx, "sentiment"] = sent_ai

            if emotions:
                prog.progress(0.7, text="Analizando emociones...")
                with st.spinner("DeepSeek Emociones..."):
                    df["emotion"] = "NEUTRAL"
                    if texts_ai:
                        emo_ai = analyze_emotions_deepseek_optimized(texts_ai)
                        df.loc[ai_idx, "emotion"] = emo_ai

            prog.progress(0.8, text="Generando resumen ejecutivo...")
            with st.spinner("Redactando Resumen Ejecutivo y analizando posts virales..."):
                query_context = topic or username_input or hashtags_str
                summary = generate_executive_summary(df, query_context)
                st.session_state["ai_summary"] = summary

        prog.progress(1.0, text="Listo")
        st.session_state["df"] = df
        log_message("Proceso completado exitosamente", "info")

    except Exception as e:
        st.error(f"Error critico: {e}")
        log_message(str(e), "error", {"traceback": traceback.format_exc()})
        if st.session_state.get("debug_mode"):
            st.exception(e)
    finally:
        prog.empty()

# =============================================================================
# VISUALIZACION & REPORTE
# =============================================================================

df = st.session_state.get("df")
ai_summary = st.session_state.get("ai_summary")

if df is not None and not df.empty:

    if ai_summary:
        st.info(f"**Resumen Ejecutivo (IA):**\n\n{ai_summary}")

    crisis_data = detect_crisis_signals(df)
    if crisis_data["score"] > 0:
        c_color = {"critical":"[CRITICO]","high":"[ALTO]","medium":"[MEDIO]","low":"[BAJO]"}.get(crisis_data["severity"],"[INFO]")
        st.header(f"{c_color} Alerta de Crisis")
        col1, col2 = st.columns([1,3])
        col1.metric("Score Crisis", f"{crisis_data['score']}/100")
        with col2:
            for s in crisis_data["signals"]:
                st.write(f"- {s}")

        if not crisis_data["crisis_posts"].empty:
            st.warning("Se han detectado los siguientes posts conflictivos:")
            cols_to_show = ["created_at", "username", "text", "likes", "url"]
            cols_existentes = [c for c in cols_to_show if c in crisis_data["crisis_posts"].columns]
            st.dataframe(crisis_data["crisis_posts"][cols_existentes], use_container_width=True)

            try:
                crisis_xlsx = df_to_excel_bytes(crisis_data["crisis_posts"])
                st.download_button(
                    label="Descargar Posts de Crisis (Excel)",
                    data=crisis_xlsx,
                    file_name="reporte_crisis.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="btn_download_crisis"
                )
            except Exception as e:
                log_message(f"Error exportando crisis_posts a Excel: {e}", "error", {"traceback": traceback.format_exc()})
                st.error("No se pudo generar el Excel de crisis. Revisa debug logs.")
        st.divider()

    st.header("Dashboard")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Posts", len(df))
    k2.metric("Likes", int(df["likes"].sum()) if "likes" in df.columns else 0)
    k3.metric("Comentarios", int(df["comments"].sum()) if "comments" in df.columns else 0)
    k4.metric("Vistas", int(df["views"].sum()) if "views" in df.columns else 0)

    st.header("Visualizaciones")
    tabs = st.tabs(["Temporal", "Sentimiento", "Emociones", "Temas", "Nube"])
    current_figures = {}

    with tabs[0]:
        if "fecha_cl" in df.columns:
            by_day = df["fecha_cl"].value_counts().sort_index()
            if not by_day.empty:
                fig, ax = plt.subplots(figsize=(10,4))
                dates_str = [str(d) for d in by_day.index]
                ax.bar(dates_str, by_day.values, color="#2ca02c")
                ax.set_title("Evolucion diaria")
                plt.xticks(rotation=45)
                st.pyplot(fig)
                current_figures["evolucion"] = fig_to_bytes(fig)
                plt.close(fig)

    with tabs[1]:
        if "sentiment" in df.columns:
            c1, c2 = st.columns(2)
            with c1:
                fig1 = plot_pie_chart(df["sentiment"], "Distribucion Sentimiento")
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
                fig3 = plot_pie_chart(df["emotion"], "Distribucion Emociones")
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
            ax_t.set_title("Top Topicos")
            plt.xticks(rotation=45)
            current_figures["top_topicos"] = fig_to_bytes(fig_t)
            plt.close(fig_t)

    with tabs[4]:
        if "text" in df.columns:
            blob = clean_texts(df["text"])
            fig_wc = wordcloud_from_blob(blob, max_words=max_words)
            if fig_wc:
                st.pyplot(fig_wc)
                current_figures["wordcloud"] = fig_to_bytes(fig_wc)
                plt.close(fig_wc)

    st.session_state["report_figures"] = current_figures
    st.divider()

    st.header("Enviar Reporte")
    with st.expander("Configuracion de Envio", expanded=True):
        email_to = st.text_input("Destinatario", placeholder="jp@empresa.com")
        if st.button("Enviar Reporte Completo", use_container_width=True):
            if not email_to:
                st.error("Ingresa un correo.")
            elif not st.session_state["report_figures"]:
                st.warning("Genera graficos primero.")
            else:
                with st.spinner("Enviando..."):
                    query_val = topic or username_input or hashtags_str
                    fecha_reporte = datetime.now(SCL_TZ).strftime('%d/%m/%Y %H:%M')

                    email_body = (
                        f"REPORTE SOCIAL LISTENING PRO\n"
                        f"============================\n"
                        f"Fecha de generacion: {fecha_reporte}\n"
                        f"Plataforma: {platform}\n"
                        f"Busqueda: {query_val}\n\n"
                        f"RESUMEN EJECUTIVO (IA):\n"
                        f"{ai_summary if ai_summary else 'No disponible.'}\n\n"
                        f"METRICAS GENERALES:\n"
                        f"- Total Posts: {len(df)}\n"
                        f"- Interacciones Totales: {int(df.get('likes',0).sum() + df.get('comments',0).sum())}\n"
                        f"- Visualizaciones: {int(df.get('views',0).sum())}\n\n"
                        f"Se adjuntan los datos detallados (Excel/CSV) y los graficos del dashboard.\n"
                    )

                    success, msg = send_email_report(
                        email_to,
                        f"Reporte: {platform} - {query_val}",
                        email_body,
                        df_to_excel_bytes(df),
                        df_to_csv_bytes(df),
                        st.session_state["report_figures"]
                    )
                    if success:
                        st.success(msg)
                    else:
                        st.error(msg)

    c1, c2 = st.columns(2)
    c1.download_button("Excel", df_to_excel_bytes(df), "reporte.xlsx")
    c2.download_button("CSV", df_to_csv_bytes(df), "reporte.csv")

# =============================================================================
# FOOTER LOGS
# =============================================================================

if st.session_state.get("logs"):
    with st.expander("Logs de Ejecucion", expanded=False):
        for log in st.session_state["logs"][-50:]:
            st.text(log)


