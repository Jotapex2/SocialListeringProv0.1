# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Optimizado por "JP" Persona - V6.7 (Full Release)
# UI: Español | Feat: Stealth Credentials + Email Reporting + Crisis Detection

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

# ============================================================================
# CONFIGURACIÓN INICIAL & LOGGING
# ============================================================================

st.set_page_config(page_title="SocialListening Pro", page_icon="📡", layout="wide")

BUILD_TAG = "JP Release v6.7 - Full Email Integration"
st.caption(f"Build: {BUILD_TAG}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constantes
SCL_TZ = pytz.timezone("America/Santiago")
API_URL_X = "https://api.twitterapi.io/twitter/tweet/advanced_search"
ASYNC_POLL_INTERVAL = 3

load_dotenv()

# ============================================================================
# SESSION STATE & UTILS
# ============================================================================

for k, v in {"df": None, "params": {}, "query_str": None, "logs": [], "report_figures": {}}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def env(name: str) -> Optional[str]:
    try: return st.secrets.get(name) or os.getenv(name)
    except: return os.getenv(name)

def log_message(msg: str, level: str = "info"):
    timestamp = datetime.now(SCL_TZ).strftime("%H:%M:%S")
    st.session_state["logs"].append(f"[{timestamp}] {msg}")
    if level == "error": logger.error(msg)
    elif level == "warning": logger.warning(msg)
    else: logger.info(msg)

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

def send_email_report(to_email, subject, body, df_xlsx, df_csv, figures_dict):
    """Envía correo con Excel, CSV y gráficos adjuntos."""
    smtp_server = env("SMTP_HOST") or "smtp.gmail.com"
    smtp_port = int(env("SMTP_PORT") or 587)
    smtp_user = env("SMTP_USER")
    smtp_pass = env("SMTP_PASS")

    if not smtp_user or not smtp_pass:
        return False, "Faltan credenciales SMTP en .env"

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))

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
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_email, msg.as_string())
        server.quit()
        return True, "Correo enviado exitosamente."
    except Exception as e:
        return False, f"Error SMTP: {str(e)}"

# ============================================================================
# MOTOR ASÍNCRONO (DEEPSEEK)
# ============================================================================

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
        except Exception: return "NEU"

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
    try: return asyncio.run(process_sentiment_batch_async(texts))
    except Exception as e:
        logger.error(f"Error Sentiment Async: {e}")
        return ["NEU"] * len(texts)

def analyze_emotions_deepseek_optimized(texts: List[str]) -> List[str]:
    if not texts: return []
    try: return asyncio.run(process_emotions_batch_async(texts))
    except Exception as e:
        logger.error(f"Error Emotions Async: {e}")
        return ["NEUTRAL"] * len(texts)

# ============================================================================
# APIFY CORE & FETCHERS
# ============================================================================

def get_apify_items_sync(dataset_id: str, token: str) -> List[Dict]:
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    try:
        r = requests.get(url, params={"token": token, "clean": "1", "format": "json"}, timeout=60)
        return r.json() if r.status_code == 200 else []
    except Exception: return []

def run_apify_actor(actor_id: str, tokens: List[str], payload: Dict) -> List[Dict]:
    valid_tokens = [t for t in tokens if t and t.strip()]
    if not valid_tokens: return []

    for i, token in enumerate(valid_tokens):
        url_run = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/runs"
        try:
            r = requests.post(url_run, params={"token": token}, json=payload, timeout=30)
            if r.status_code not in [200, 201]: continue

            run_data = r.json()["data"]
            run_id, dataset_id = run_data["id"], run_data["defaultDatasetId"]
            
            start_time = time.time()
            while time.time() - start_time < 300:
                time.sleep(ASYNC_POLL_INTERVAL)
                try:
                    r_poll = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}", params={"token": token}, timeout=10)
                    if r_poll.status_code == 200:
                        status = r_poll.json()["data"]["status"]
                        if status == "SUCCEEDED": return get_apify_items_sync(dataset_id, token)
                        elif status in ["FAILED", "ABORTED", "TIMED-OUT"]: break
                except: continue
        except Exception:
            if i < len(valid_tokens) - 1: continue
    return []

def normalize_common_optimized(rows: List[Dict], platform: str) -> pd.DataFrame:
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
                if c in df.columns: df[target] = df[c]; break
            if target not in df.columns: 
                df[target] = 0 if target in ["likes", "comments", "shares", "views", "followers"] else None

    if "created_at" in df.columns:
        df["created_at_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        df["created_at_cl"] = df["created_at_utc"].dt.tz_convert(SCL_TZ)
        df["fecha_cl"] = df["created_at_cl"].dt.date
    
    if "username" not in df.columns:
        for c in ["ownerUsername", "authorUsername", "username", "author", "pageName"]:
            if c in df.columns:
                df["username"] = df[c].apply(lambda x: x.get('name') if isinstance(x, dict) else x)
                break
    
    if "text" in df.columns: df["text"] = df["text"].fillna("").astype(str)
    
    for col in ["likes", "comments", "shares", "views", "followers"]:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["platform"] = platform
    return df

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_x_cached(api_key: str, query: str, limit: int) -> pd.DataFrame:
    headers = {"x-api-key": api_key}
    all_rows = []
    cursor = None
    max_loops = (limit // 20) + 5 
    for _ in range(max_loops):
        params = {"query": query, "queryType": "Latest"}
        if cursor: params["cursor"] = cursor
        try:
            r = requests.get(API_URL_X, headers=headers, params=params, timeout=20)
            if r.status_code != 200: break
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
        except Exception: break
    return normalize_common_optimized(all_rows, "x")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_facebook_cached(tokens: List[str], query: str, limit: int, mode: str) -> pd.DataFrame:
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
    except Exception: return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_instagram_cached(tokens: List[str], query: str, limit: int, mode: str) -> pd.DataFrame:
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
    payload = {"resultsPerPage": 100, "shouldDownloadVideos": False, "limit": limit}
    if mode == "user": payload["usernames"] = [u.strip() for u in query.split(",")]
    else: payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
    items = run_apify_actor("clockworks/tiktok-scraper", tokens, payload)
    return normalize_common_optimized(items, "tiktok")

# ============================================================================
# UTILS DE FILTRADO Y EXPORT
# ============================================================================

def enforce_date_window(df: pd.DataFrame, d1: Optional[date], d2: Optional[date]) -> pd.DataFrame:
    if df is None or df.empty or "created_at_cl" not in df.columns: return df
    mask = pd.Series(True, index=df.index)
    series_normalized = df["created_at_cl"].dt.normalize()
    if d1: mask &= ((series_normalized >= pd.Timestamp(d1).tz_localize(SCL_TZ, nonexistent="shift_forward")) | (series_normalized.isna()))
    if d2: mask &= ((series_normalized <= pd.Timestamp(d2).tz_localize(SCL_TZ, nonexistent="shift_forward")) | (series_normalized.isna()))
    return df.loc[mask].copy()

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    df_exp = df.copy()
    for c in df_exp.columns:
        if is_datetime64tz_dtype(df_exp[c]): df_exp[c] = df_exp[c].dt.tz_localize(None)
    with pd.ExcelWriter(bio, engine="xlsxwriter") as xw: df_exp.to_excel(xw, sheet_name="posts", index=False)
    bio.seek(0)
    return bio.read()

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

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
    return q

# ============================================================================
# INTERFAZ STREAMLIT
# ============================================================================

st.title("📡 Social Listening Pro — X + Instagram + Facebook + TikTok")
st.markdown("**Análisis avanzado con detección de crisis, sentimiento y reporte por email**")

st.sidebar.header("⚙️ Configuración")
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
d1 = st.sidebar.date_input("Desde", value=datetime.now(SCL_TZ).date() - timedelta(days=14))
d2 = st.sidebar.date_input("Hasta", value=datetime.now(SCL_TZ).date())

limit = st.sidebar.slider("Límite de posts", 50, 2000, 200)
max_words = st.sidebar.slider("Máx. palabras nube", 50, 500, 200)

sentiment = st.sidebar.checkbox("🧠 Analizar Sentimiento", value=True)
emotions = st.sidebar.checkbox("😊 Analizar Emociones", value=False)

st.sidebar.divider()
run_btn = st.sidebar.button("🔍 Buscar", type="primary", use_container_width=True)

# Credenciales Stealth
env_x = env("TWITTERAPI_IO_KEY")
api_x = env_x if env_x else st.sidebar.text_input("API Key twitterapi.io", type="password")
env_apify = env("APIFY_TOKEN")
api_apify = env_apify if env_apify else st.sidebar.text_input("Token Apify", type="password")

# ============================================================================
# EJECUCIÓN
# ============================================================================

if run_btn:
    st.session_state["logs"] = []
    st.session_state["report_figures"] = {} # Limpiar figuras previas
    prog = st.progress(0.0, text="Iniciando...")
    df = pd.DataFrame()
    tokens = [t for t in [api_apify] if t]

    try:
        # 1. FETCHING
        if platform.startswith("X"):
            if not api_x: st.error("Falta API Key X"); st.stop()
            if "usuario" in search_mode: q = compose_query_x_user(username_input, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            else: q = compose_query_x(topic, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            df = fetch_x_cached(api_x, q, limit)
        
        elif platform == "Facebook":
            if not tokens: st.error("Falta Token Apify"); st.stop()
            mode = "user" if "usuario" in search_mode else "search"
            q = username_input if mode == "user" else topic
            df = fetch_facebook_cached(tokens, q, limit, mode)
            
        elif platform == "Instagram":
            if not tokens: st.error("Falta Token Apify"); st.stop()
            mode = "hashtag" if "hashtags" in search_mode else "keyword" if "búsqueda" in search_mode else "user"
            q = hashtags_str if mode == "hashtag" else (username_input if mode == "user" else topic)
            df = fetch_instagram_cached(tokens, q, limit, mode)
            
        elif platform == "TikTok":
            if not tokens: st.error("Falta Token Apify"); st.stop()
            mode = "user" if "usuario" in search_mode else "hashtag"
            q = username_input if mode == "user" else topic
            df = fetch_tiktok_cached(tokens, q, limit, mode)

        df = enforce_date_window(df, d1, d2)
        prog.progress(0.5, text="Procesando IA...")

        if df.empty:
            st.warning("No se encontraron resultados.")
            st.stop()

        # 2. IA
        if "text" in df.columns:
            texts = df["text"].tolist()
            if sentiment:
                with st.spinner("DeepSeek Sentimiento..."): df["sentiment"] = analyze_sentiment_deepseek_optimized(texts)
            if emotions:
                with st.spinner("DeepSeek Emociones..."): df["emotion"] = analyze_emotions_deepseek_optimized(texts)

        prog.progress(1.0, text="Listo")
        st.session_state["df"] = df
        
    except Exception as e:
        st.error(f"Error: {e}")
        log_message(str(e), "error")
    
    prog.empty()

# ============================================================================
# VISUALIZACIÓN & REPORTE
# ============================================================================

df = st.session_state.get("df")

if df is not None and not df.empty:
    
    # Crisis Alert
    crisis_data = detect_crisis_signals(df)
    if crisis_data["score"] > 0:
        c_color = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}.get(crisis_data["severity"],"⚪")
        st.header(f"{c_color} Alerta de Crisis")
        col1, col2 = st.columns([1,3])
        col1.metric("Score Crisis", f"{crisis_data['score']}/100")
        with col2:
            for s in crisis_data["signals"]: st.write(f"• {s}")
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
        if "created_at_cl" in df.columns:
            df_t = df.copy()
            df_t["fecha"] = df_t["created_at_cl"].dt.date
            by_day = df_t["fecha"].value_counts().sort_index()
            if not by_day.empty:
                fig, ax = plt.subplots(figsize=(10,4))
                ax.bar(by_day.index.astype(str), by_day.values, color="#2ca02c")
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
            # Crear figura Matplotlib para el reporte
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
                    success, msg = send_email_report(
                        email_to, 
                        f"Reporte Social Listening: {platform}", 
                        f"Adjunto reporte generado el {datetime.now()}.\nResultados: {len(df)} posts.", 
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