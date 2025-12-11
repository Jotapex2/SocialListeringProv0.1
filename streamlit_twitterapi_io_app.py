# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Optimizado por "JP" Persona - V6.6
# UI: Español | Feat: Stealth Credentials (Inputs ocultos si existen en .env)

import os, re, io, time, json, pytz, requests, pandas as pd, streamlit as st
import matplotlib.pyplot as plt
import asyncio
import httpx
from wordcloud import WordCloud, STOPWORDS
from unidecode import unidecode
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from pandas.api.types import is_datetime64tz_dtype
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any, Callable, Union
from collections import Counter
import logging

# ============================================================================
# CONFIGURACIÓN INICIAL & LOGGING
# ============================================================================

st.set_page_config(page_title="SocialListening Pro", page_icon="📡", layout="wide")

BUILD_TAG = "JP Release v6.6 - Stealth UI (Credenciales Ocultas)"
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

for k, v in {"df": None, "params": {}, "query_str": None, "logs": []}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def env(name: str) -> Optional[str]:
    """Busca en st.secrets primero, luego en os.getenv (.env)"""
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
# MOTOR ASÍNCRONO (ASYNC CORE) - OPTIMIZADO V2 (CON SEMÁFORO Y LIMPIEZA)
# ============================================================================

# Limita la concurrencia para evitar el Error 429 (Too Many Requests) de DeepSeek
MAX_CONCURRENT_REQUESTS = 10 
SEM = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

async def async_fetch_deepseek(client: httpx.AsyncClient, prompt: str, max_tokens: int = 10) -> str:
    deepseek_key = env("DEEPSEEK_API_KEY")
    if not deepseek_key: 
        return "NEU"
    
    # Usamos el semáforo para esperar turno si hay muchas peticiones activas
    async with SEM:
        try:
            response = await client.post(
                "/v1/chat/completions",
                json={
                    "model": "deepseek-chat",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1, # Un pelín de temp ayuda a evitar loops, pero bajo para consistencia
                    "max_tokens": max_tokens
                },
                headers={
                    "Authorization": f"Bearer {deepseek_key}",
                    "Content-Type": "application/json"
                }, 
                timeout=45.0 # Aumentamos timeout por si hay cola
            )
            
            if response.status_code == 200:
                content = response.json()['choices'][0]['message']['content'].strip().upper()
                # Limpieza agresiva: eliminar puntos, comillas y espacios extra
                clean_content = re.sub(r'[^\w]', '', content) 
                return clean_content
            elif response.status_code == 429:
                logger.warning("DeepSeek Rate Limit 429 - Retornando NEU")
                return "NEU"
            else:
                logger.error(f"DeepSeek Error {response.status_code}: {response.text}")
                return "NEU"
        except Exception as e:
            logger.error(f"DeepSeek Async Exception: {e}")
            return "NEU"

async def process_sentiment_batch_async(texts: List[str]) -> List[str]:
    # Aumentamos los límites de conexión del cliente
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    async with httpx.AsyncClient(base_url="https://api.deepseek.com", limits=limits, timeout=60.0) as client:
        tasks = []
        for text in texts:
            # Prompt blindado para evitar palabrería
            prompt = (
                f"Clasifica el sentimiento: '{text[:300]}'. "
                "Responde EXCLUSIVAMENTE con una palabra: POS, NEG o NEU."
            )
            tasks.append(async_fetch_deepseek(client, prompt, 5))
        
        # Barra de progreso "invisible" (esperamos todos los resultados)
        results = await asyncio.gather(*tasks)
        
        # Post-procesamiento para asegurar que si falla algo raro, sea NEU
        final_results = []
        for r in results:
            if r in ["POS", "NEG", "NEU"]:
                final_results.append(r)
            elif "POS" in r: final_results.append("POS")
            elif "NEG" in r: final_results.append("NEG")
            else: final_results.append("NEU")
        return final_results

async def process_emotions_batch_async(texts: List[str]) -> List[str]:
    limits = httpx.Limits(max_keepalive_connections=10, max_connections=20)
    valid_emotions = ["RISA", "IRA", "MIEDO", "TRISTEZA", "DISGUSTO", "SORPRESA", "NEUTRAL"]
    
    async with httpx.AsyncClient(base_url="https://api.deepseek.com", limits=limits, timeout=60.0) as client:
        tasks = []
        for text in texts:
            prompt = (
                f"Detecta la emoción en: '{text[:300]}'. "
                "Opciones: RISA, IRA, MIEDO, TRISTEZA, DISGUSTO, SORPRESA, NEUTRAL. "
                "Responde SOLO con la palabra."
            )
            tasks.append(async_fetch_deepseek(client, prompt, 10))
        
        results = await asyncio.gather(*tasks)
        
        # Mapeo de limpieza por si el modelo responde "TRISTEZA." o "LA EMOCION ES IRA"
        clean_results = []
        for r in results:
            found = False
            for emo in valid_emotions:
                if emo in r:
                    clean_results.append(emo)
                    found = True
                    break
            if not found:
                clean_results.append("NEUTRAL") # Fallback seguro
        
        return clean_results

def analyze_sentiment_deepseek_optimized(texts: List[str]) -> List[str]:
    if not texts: return []
    return asyncio.run(process_sentiment_batch_async(texts))

def analyze_emotions_deepseek_optimized(texts: List[str]) -> List[str]:
    if not texts: return []
    return asyncio.run(process_emotions_batch_async(texts))

# ============================================================================
# APIFY CORE (FAILOVER)
# ============================================================================

def get_apify_items_sync(dataset_id: str, token: str) -> List[Dict]:
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    try:
        r = requests.get(url, params={"token": token, "clean": "1", "format": "json"}, timeout=60)
        return r.json() if r.status_code == 200 else []
    except Exception as e:
        log_message(f"Error dataset Apify: {e}", "error")
        return []

def run_apify_actor(actor_id: str, tokens: List[str], payload: Dict) -> List[Dict]:
    valid_tokens = [t for t in tokens if t and t.strip()]
    if not valid_tokens:
        log_message("No hay tokens de Apify válidos.", "error")
        return []

    for i, token in enumerate(valid_tokens):
        url_run = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/runs"
        try:
            r = requests.post(url_run, params={"token": token}, json=payload, timeout=30)
            if r.status_code in [401, 402, 403, 429]: r.raise_for_status()
            if r.status_code != 201: r.raise_for_status()

            run_data = r.json()["data"]
            run_id, dataset_id = run_data["id"], run_data["defaultDatasetId"]
            
            start_time = time.time()
            while time.time() - start_time < 300:
                time.sleep(ASYNC_POLL_INTERVAL)
                try:
                    r_poll = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}", params={"token": token}, timeout=10)
                    if r_poll.status_code == 200:
                        status = r_poll.json()["data"]["status"]
                        if status == "SUCCEEDED":
                            return get_apify_items_sync(dataset_id, token)
                        elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                            raise RuntimeError(f"Status: {status}")
                except requests.exceptions.RequestException: continue
            raise RuntimeError("Timeout polling actor")

        except Exception as e:
            log_message(f"⚠️ Token #{i+1} falló: {str(e)}", "warning")
            if i < len(valid_tokens) - 1: continue
            else: log_message("❌ Todos los tokens fallaron.", "error")

    return []

# ============================================================================
# NORMALIZACIÓN & TOOLS
# ============================================================================

def enforce_date_window(df: pd.DataFrame, d1: Optional[date], d2: Optional[date]) -> pd.DataFrame:
    if df is None or df.empty: return df
    if "created_at_cl" not in df.columns: return df

    mask = pd.Series(True, index=df.index)
    series_normalized = df["created_at_cl"].dt.normalize()
    
    if d1:
        ts1 = pd.Timestamp(d1).tz_localize(SCL_TZ)
        mask &= ((series_normalized >= ts1) | (series_normalized.isna()))
    if d2:
        ts2 = pd.Timestamp(d2).tz_localize(SCL_TZ)
        mask &= ((series_normalized <= ts2) | (series_normalized.isna()))
    
    filtered = df.loc[mask].copy()
    null_dates = filtered["created_at_cl"].isna().sum()
    log_message(f"Filtrado fechas: {len(df)} -> {len(filtered)} posts (Inc. {null_dates} sin fecha)")
    return filtered

def normalize_common_optimized(rows: List[Dict], platform: str) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty: return df

    col_map = {
        "text": ["caption", "description", "title", "text", "message", "postText"],
        "likes": ["likeCount", "likesCount", "diggCount", "likes", "reactionCount"],
        "comments": ["commentCount", "commentsCount", "comments"],
        "shares": ["shareCount", "retweetCount", "shares"],
        "views": ["playCount", "viewCount", "videoPlayCount", "views"],
        "created_at": ["timestamp", "takenAt", "createTimeISO", "createdAt", "date", "time"]
    }

    for target, candidates in col_map.items():
        if target not in df.columns:
            for c in candidates:
                if c in df.columns: df[target] = df[c]; break
            if target not in df.columns: df[target] = 0 if target in ["likes", "comments", "shares", "views"] else None

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
        
    for col in ["likes", "comments", "shares", "views"]:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    df["platform"] = platform
    return df

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    bio = io.BytesIO()
    # Copia segura para eliminar TZs antes de Excel
    df_exp = df.copy()
    for c in df_exp.columns:
        if is_datetime64tz_dtype(df_exp[c]):
            df_exp[c] = df_exp[c].dt.tz_localize(None)
    
    with pd.ExcelWriter(bio, engine="xlsxwriter") as xw:
        df_exp.to_excel(xw, sheet_name="posts", index=False)
    bio.seek(0)
    return bio.read()

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8-sig")

# ============================================================================
# FETCHERS (CACHEADOS + DUAL TOKEN)
# ============================================================================

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
                "id": i.get("postId"),
                "text": i.get("text") or i.get("postText") or i.get("message"),
                "username": i.get("user", {}).get("name"),
                "likes": i.get("likes", 0), "comments": i.get("comments", 0),
                "shares": i.get("shares", 0), "url": i.get("url") or i.get("postUrl"),
                "created_at": i.get("time") or i.get("timestamp")
            })
        return normalize_common_optimized(normalized, "facebook")
    except Exception: return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_instagram_cached(tokens: List[str], query: str, limit: int, mode: str) -> pd.DataFrame:
    actor = ""
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
    if mode == "user":
        payload["usernames"] = [u.strip() for u in query.split(",")]
    else:
        payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
    items = run_apify_actor("clockworks/tiktok-scraper", tokens, payload)
    return normalize_common_optimized(items, "tiktok")

# ============================================================================
# FUNCIONES VISUALES
# ============================================================================

def plot_pie_chart(series, title):
    if series.empty: return None
    counts = series.value_counts()
    fig, ax = plt.subplots(figsize=(6, 6))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    wedges, texts, autotexts = ax.pie(counts, labels=counts.index, autopct='%1.1f%%', startangle=90)
    ax.set_title(title, fontsize=12, fontweight='bold')
    return fig

def plot_bar_chart(series, title, color_hex="#3498db"):
    if series.empty: return None
    counts = series.value_counts()
    fig, ax = plt.subplots(figsize=(6, 5))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    bars = ax.bar(counts.index, counts.values, color=color_hex)
    ax.set_title(title, fontsize=12, fontweight='bold')
    ax.set_ylabel("Cantidad")
    ax.grid(axis='y', linestyle='--', alpha=0.3)
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height}', xy=(bar.get_x() + bar.get_width()/2, height),
                    xytext=(0, 3), textcoords="offset points", ha='center', va='bottom')
    plt.tight_layout()
    return fig

# ============================================================================
# HELPERS ORIGINALES
# ============================================================================

EXTRA_STOP = {"rt","https","http","t","co","amp","si","no","asi","aqui","ahi","ser","estar","haber","hacer","de","la","que","el","en","y","a","los","del","se","las","por","un","para","con","una","su","al","lo","como","mas","pero","sus","le","ya","o","fue","ha","porque","cuando","muy","sin","sobre","tambien","me"}
STOP = STOPWORDS.union(EXTRA_STOP)

def clean_texts(texts: pd.Series) -> str:
    blob = []
    url_re = re.compile(r"http\S+|www\.\S+", re.I)
    for s in texts.fillna("").astype(str):
        s = s.lower()
        s = url_re.sub(" ", s)
        s = re.sub(r"@\w+|#", " ", s)
        s = unidecode(s)
        s = re.sub(r"[^a-z\s]", " ", s)
        words = [w for w in s.split() if w not in STOP and len(w) > 2]
        blob.extend(words)
    return " ".join(blob)

def wordcloud_from_blob(blob: str, max_words: int = 200):
    if not blob.strip():
        st.info("No hay texto suficiente.")
        return
    wc = WordCloud(width=1200, height=500, background_color="white", stopwords=STOP, max_words=max_words, colormap="viridis").generate(blob)
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.imshow(wc, interpolation='bilinear')
    ax.axis("off")
    st.pyplot(fig)
    plt.close()

def extract_topics(texts: List[str], top_n: int = 10) -> Dict[str, int]:
    tokens = []
    url_re = re.compile(r"http\S+|www\.\S+", re.I)
    for text in texts:
        text = text.lower() if text else ""
        text = url_re.sub(" ", text)
        text = re.sub(r"@\w+|#", " ", text)
        text = unidecode(text)
        text = re.sub(r"[^a-z\s]", " ", text)
        words = [w for w in text.split() if w not in STOP and len(w) > 3]
        tokens.extend(words)
    counter = Counter(tokens)
    return dict(counter.most_common(top_n))

CRISIS_KEYWORDS = {
    "es": ["crisis", "emergencia", "caída", "fallo", "problema", "error", "incidente", "demanda", "denuncia", "escándalo", "fraude", "robo", "ataque", "acusación", "desastre"],
    "en": ["crisis", "emergency", "outage", "failure", "problem", "error", "incident", "scandal", "fraud"]
}

def detect_crisis_signals(df: pd.DataFrame, lang: str = "es") -> Dict[str, Any]:
    if df.empty: return {"score": 0, "severity": "none", "signals": [], "crisis_posts": pd.DataFrame()}
    signals = []
    crisis_score = 0
    if "sentiment" in df.columns:
        neg_ratio = (df["sentiment"] == "NEG").sum() / max(1, len(df))
        if neg_ratio > 0.3:
            signals.append(f"Sentimiento negativo alto: {neg_ratio*100:.1f}%")
            crisis_score += 25
    keywords = CRISIS_KEYWORDS.get(lang, CRISIS_KEYWORDS["es"])
    if "text" in df.columns:
        crisis_posts = df[df["text"].str.lower().str.contains("|".join(keywords), regex=True, na=False)]
        if len(crisis_posts) > 0:
            signals.append(f"Posts con palabras de crisis: {len(crisis_posts)}")
            crisis_score += min(30, len(crisis_posts) * 5)
    else:
        crisis_posts = pd.DataFrame()
    severity = "critical" if crisis_score >= 60 else "high" if crisis_score >= 40 else "medium" if crisis_score >= 20 else "low"
    return {"score": min(100, crisis_score), "severity": severity, "signals": signals, "crisis_posts": crisis_posts}

# ============================================================================
# QUERY BUILDERS X
# ============================================================================

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
st.markdown("**Análisis avanzado con detección de crisis, sentimiento, emociones y temas**")

st.sidebar.header("⚙️ Configuración de búsqueda")

platform = st.sidebar.selectbox("Plataforma", ["X (Twitter)", "Instagram", "Facebook", "TikTok"], index=0)

if platform == "Instagram":
    search_mode = st.sidebar.radio("Modo de búsqueda", ["Por temática (hashtags)", "Por temática (búsqueda IG)", "Por usuario/perfil"])
elif platform == "Facebook":
    search_mode = st.sidebar.radio("Modo de búsqueda", ["Por temática", "Por usuario/perfil"])
else:
    search_mode = st.sidebar.radio("Modo de búsqueda", ["Por temática", "Por usuario"])

topic = ""
username_input = ""
hashtags_str = ""

if search_mode.startswith("Por temática"):
    if platform == "Instagram" and "hashtags" in search_mode:
        hashtags_str = st.sidebar.text_input("Hashtag(s)", help="Sin #, separados por coma")
    else:
        topic = st.sidebar.text_input("Tema / consulta")
else:
    username_input = st.sidebar.text_input("Usuario(s) / URL(s)", help="Separar por coma")

lang = st.sidebar.selectbox("Idioma (solo X)", ["", "es", "en", "pt"], index=1)
col1, col2 = st.sidebar.columns(2)
exclude_rt = col1.checkbox("Excluir RTs [X]", value=True)
exclude_repl = col2.checkbox("Excluir respuestas [X]", value=True)
filter_chile = st.sidebar.checkbox("🇨🇱 Filtrar solo posts de Chile (X)")

st.sidebar.divider()

today = datetime.now(SCL_TZ).date()
d1_default = st.session_state["params"].get("d1", today - timedelta(days=14))
d2_default = st.session_state["params"].get("d2", today)

date_range = st.sidebar.date_input("Rango de fechas (CL)", value=(d1_default, d2_default))
if isinstance(date_range, tuple) and len(date_range) == 2:
    d1, d2 = date_range
else:
    d1, d2 = date_range, date_range

limit = st.sidebar.slider("Límite de posts", 50, 5000, 300)
max_words = st.sidebar.slider("Máx. palabras nube", 50, 500, 200)

sentiment = st.sidebar.checkbox("🧠 Analizar sentimiento (POS/NEG/NEU)", value=True)
emotions = st.sidebar.checkbox("😊 Analizar emociones (Ekman 6)", value=False)

st.sidebar.divider()
run_btn = st.sidebar.button("🔍 Buscar", type="primary", use_container_width=True)

# --- GESTIÓN DE CREDENCIALES (STEALTH MODE) ---
st.sidebar.subheader("🔐 Credenciales")

# X (Twitter)
env_x = env("TWITTERAPI_IO_KEY")
api_x = env_x if env_x else st.sidebar.text_input("API Key twitterapi.io (X)", type="password")
if env_x: st.sidebar.caption("✅ TwitterAPI Key cargada desde entorno")

# Apify (Dual Token Logic)
env_apify_1 = env("APIFY_TOKEN")
env_apify_2 = env("APIFY_TOKEN_2")
api_apify_1 = env_apify_1 if env_apify_1 else st.sidebar.text_input("Token Apify (Primario)", type="password")
api_apify_2 = env_apify_2 if env_apify_2 else st.sidebar.text_input("Token Apify (Respaldo)", type="password", help="Opcional")

if env_apify_1: st.sidebar.caption("✅ Apify Token cargado desde entorno")

# ============================================================================
# EJECUCIÓN
# ============================================================================

if run_btn:
    st.session_state["logs"] = []
    prog = st.progress(0.0, text="Iniciando búsqueda...")
    df = pd.DataFrame()
    
    # Preparar tokens Apify
    apify_tokens = [t for t in [api_apify_1, api_apify_2] if t and t.strip()]
    
    try:
        # 1. FETCHING
        if platform.startswith("X"):
            if not api_x: st.error("Falta API Key X"); st.stop()
            if search_mode == "Por usuario":
                qx = compose_query_x_user(username_input, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            else:
                qx = compose_query_x(topic, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            df = fetch_x_cached(api_x, qx, limit)
            
        elif platform == "Facebook":
            if not apify_tokens: st.error("Falta Token Apify"); st.stop()
            fb_mode = "user" if "usuario" in search_mode else "search"
            q_fb = username_input if fb_mode == "user" else topic
            df = fetch_facebook_cached(apify_tokens, q_fb, limit, fb_mode)
            
        elif platform == "Instagram":
            if not apify_tokens: st.error("Falta Token Apify"); st.stop()
            ig_mode = "hashtag" if "hashtags" in search_mode else "keyword" if "búsqueda" in search_mode else "user"
            q_ig = hashtags_str if ig_mode == "hashtag" else (username_input if ig_mode == "user" else topic)
            df = fetch_instagram_cached(apify_tokens, q_ig, limit, ig_mode)
            
        elif platform == "TikTok":
            if not apify_tokens: st.error("Falta Token Apify"); st.stop()
            tt_mode = "user" if "usuario" in search_mode else "hashtag"
            q_tt = username_input if tt_mode == "user" else topic
            df = fetch_tiktok_cached(apify_tokens, q_tt, limit, tt_mode)

        # 2. FILTRADO FECHAS (PERMISIVO)
        df = enforce_date_window(df, d1, d2)

        prog.progress(0.5, text="Datos obtenidos. Procesando IA...")

        if df.empty:
            prog.empty()
            st.warning("⚠️ No se encontraron resultados en este rango.")
            st.stop()

        # 3. IA ASYNC
        if "text" in df.columns:
            texts = df["text"].tolist()
            if sentiment:
                with st.spinner("Ejecutando DeepSeek Async (Sentimiento)..."):
                    df["sentiment"] = analyze_sentiment_deepseek_optimized(texts)
            if emotions:
                with st.spinner("Ejecutando DeepSeek Async (Emociones)..."):
                    df["emotion"] = analyze_emotions_deepseek_optimized(texts)

        prog.progress(1.0, text="¡Listo!")
        time.sleep(0.5)
        prog.empty()
        st.session_state["df"] = df
        st.session_state["params"]["d1"] = d1
        st.session_state["params"]["d2"] = d2
        
    except Exception as e:
        prog.empty()
        st.error(f"Error: {e}")
        log_message(f"Crash: {e}", "error")

# ============================================================================
# RESULTADOS
# ============================================================================

df = st.session_state.get("df")

if df is not None and not df.empty:
    
    # Crisis
    crisis_data = detect_crisis_signals(df)
    if crisis_data["score"] > 0:
        sev = crisis_data["severity"]
        color = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}.get(sev,"⚪")
        st.header(f"{color} Alerta de Crisis Detectada")
        c1, c2 = st.columns([1,3])
        c1.metric("Score", f"{crisis_data['score']}/100")
        c1.metric("Severidad", sev.upper())
        with c2:
            for s in crisis_data["signals"]: st.write(f"• {s}")
        if not crisis_data["crisis_posts"].empty:
            with st.expander("Ver posts de crisis"):
                st.dataframe(crisis_data["crisis_posts"])
        st.divider()

    # Métricas
    st.header("📈 Resumen de métricas")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Posts", len(df))
    m2.metric("Usuarios", df["username"].nunique() if "username" in df else 0)
    m3.metric("Likes", int(df["likes"].sum()))
    m4.metric("Comentarios", int(df["comments"].sum()))
    m5.metric("Shares", int(df["shares"].sum()))

    # Visualizaciones
    st.header("📊 Visualizaciones")
    tabs = st.tabs(["📅 Temporal", "🧠 Sentimiento", "🎭 Emociones", "🏷️ Temas", "☁️ Nube"])
    
    with tabs[0]: # Temporal
        if "created_at_cl" in df.columns:
            df_t = df.copy()
            df_t["fecha"] = df_t["created_at_cl"].dt.date
            by_day = df_t["fecha"].value_counts().sort_index()
            if not by_day.empty:
                fig, ax = plt.subplots(figsize=(10,4))
                fig.patch.set_facecolor('white')
                ax.bar(by_day.index.astype(str), by_day.values, color="#2ca02c")
                ax.set_title("Evolución diaria")
                plt.xticks(rotation=45)
                st.pyplot(fig)
    
    with tabs[1]: # Sentimiento
        if "sentiment" in df.columns:
            c1, c2 = st.columns(2)
            dist = df["sentiment"].value_counts()
            with c1:
                st.pyplot(plot_pie_chart(df["sentiment"], "Distribución"))
            with c2:
                st.pyplot(plot_bar_chart(df["sentiment"], "Conteo", "#2ecc71"))

    with tabs[2]: # Emociones
        if "emotion" in df.columns:
            c1, c2 = st.columns(2)
            with c1:
                st.pyplot(plot_pie_chart(df["emotion"], "Distribución"))
            with c2:
                st.pyplot(plot_bar_chart(df["emotion"], "Conteo por Emoción", "#9b59b6"))

    with tabs[3]: # Temas
        if "text" in df.columns:
            topics = extract_topics(df["text"].tolist())
            st.bar_chart(pd.Series(topics))

    with tabs[4]: # Nube
        if "text" in df.columns:
            blob = clean_texts(df["text"])
            wordcloud_from_blob(blob, max_words)

    # Export
    st.header("📋 Datos Detallados")
    st.dataframe(df, use_container_width=True)
    
    c_exp1, c_exp2 = st.columns(2)
    with c_exp1:
        st.download_button("📄 Descargar CSV", df_to_csv_bytes(df), "data.csv", "text/csv")
    with c_exp2:
        st.download_button("📊 Descargar Excel", df_to_excel_bytes(df), "data.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

else:
    st.info("Configura los parámetros y pulsa Buscar.")