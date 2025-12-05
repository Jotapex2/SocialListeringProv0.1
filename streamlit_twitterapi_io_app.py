# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Versión optimizada con mejor manejo de errores y procesamiento robusto
# Mejoras: retry logic, logging, validaciones, performance

import os, re, io, time, json, pytz, requests, pandas as pd, streamlit as st
import matplotlib.pyplot as plt
from wordcloud import WordCloud, STOPWORDS
from unidecode import unidecode
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from pandas.api.types import is_datetime64tz_dtype
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any, Callable
from collections import Counter
import logging
import streamlit as st
import httpx


# ============================================================================
# CONFIGURACIÓN INICIAL
# ============================================================================



# Definir usuario y contraseña (puedes cambiar a lo que quieras)
USERNAME = "Jota"
PASSWORD = "Ñandu1314"

def login():
    st.title("Login de administrador")
    user = st.text_input("Usuario")
    pwd = st.text_input("Contraseña", type="password")
    if st.button("Entrar"):
        if user == USERNAME and pwd == PASSWORD:
            st.session_state['logged_in'] = True
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrecta.")

if "logged_in" not in st.session_state or not st.session_state['logged_in']:
    login()
    st.stop()
# Desde aquí comienza el código de tu app normalmente

# ============================================================================
# CONFIGURACIÓN INICIAL
# ============================================================================

st.set_page_config(page_title="SocialListening Pro", page_icon="📡", layout="wide")

BUILD_TAG = "RRSS-Pro v4.0 - Sentiment + Emotions + Crisis Detection + Topics"
st.caption(f"Build: {BUILD_TAG}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constantes
SCL_TZ = pytz.timezone("America/Santiago")
API_URL_X = "https://api.twitterapi.io/twitter/tweet/advanced_search"
MAX_RETRIES = 3
RETRY_DELAY = 2
DEFAULT_TIMEOUT = 120
ASYNC_MAX_WAIT = 360
ASYNC_POLL_INTERVAL = 8

load_dotenv()

# ============================================================================
# SESSION STATE
# ============================================================================

for k, v in {"df": None, "params": {}, "query_str": None, "logs": []}.items():
    if k not in st.session_state:
        st.session_state[k] = v

def env(name: str) -> Optional[str]:
    """Obtiene variable de entorno desde secrets o .env"""
    try:
        v = st.secrets.get(name)
    except Exception:
        v = None
    return v or os.getenv(name)

def log_message(msg: str, level: str = "info"):
    """Registra mensaje en logs de sesión"""
    timestamp = datetime.now(SCL_TZ).strftime("%H:%M:%S")
    st.session_state["logs"].append(f"[{timestamp}] {msg}")
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)

# ============================================================================
# EXPORT HELPERS
# ============================================================================

def _drop_tz_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    """Elimina timezone de columnas datetime para compatibilidad Excel"""
    df2 = df.copy()
    for c in df2.columns:
        if is_datetime64tz_dtype(df2[c]):
            df2[c] = df2[c].dt.tz_localize(None)
    return df2

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Convierte DataFrame a bytes CSV con UTF-8 BOM"""
    return df.to_csv(index=False).encode("utf-8-sig")

def df_to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Convierte DataFrame a bytes Excel"""
    bio = io.BytesIO()
    with pd.ExcelWriter(bio, engine="xlsxwriter") as xw:
        _drop_tz_for_excel(df).to_excel(xw, sheet_name="posts", index=False)
    bio.seek(0)
    return bio.read()

# ============================================================================
# WORDCLOUD
# ============================================================================

EXTRA_STOP = {
    "rt","https","http","t","co","amp","…","si","no","asi","aqui","ahi","ser","estar","haber","hacer",
    "de","la","que","el","en","y","a","los","del","se","las","por","un","para","con","una","su","al","lo","como",
    "mas","pero","sus","le","ya","o","fue","ha","porque","cuando","muy","sin","sobre","tambien","me",
    "hasta","hay","donde","quien","desde","todo","nos","durante","todos","uno","les","ni","contra","otros",
    "ese","eso","ante","ellos","e","esto","mi","antes","algunos","que","unos","yo","otro","otras","otra","el",
    "tanto","esa","estos","mucho","quienes","nada","muchos","cual","poco","ella","estas","algunas",
    "algo","nosotros","mis","tu","tus","ellas","nosotras","vosotros","vosotras","os"
}

STOP = STOPWORDS.union(EXTRA_STOP)

def clean_texts(texts: pd.Series) -> str:
    """Limpia y normaliza textos para wordcloud"""
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
    """Genera y muestra nube de palabras"""
    if not blob.strip():
        st.info("No hay texto suficiente para la nube de palabras.")
        return
    
    wc = WordCloud(
        width=1200,
        height=500,
        background_color="white",
        collocations=False,
        stopwords=STOP,
        max_words=max_words,
        colormap="viridis"
    ).generate(blob)
    
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.imshow(wc, interpolation='bilinear')
    ax.axis("off")
    st.pyplot(fig)
    plt.close()

# ============================================================================
# CRISIS DETECTION
# ============================================================================

CRISIS_KEYWORDS = {
    "es": ["crisis", "emergencia", "caída", "fallo", "problema", "error", "incidente", 
           "demanda", "denuncia", "escándalo", "fraude", "robo", "ataque", "acusación",
           "desastre", "catástrofe", "peligro", "advertencia", "alerta", "defecto"],
    "en": ["crisis", "emergency", "outage", "failure", "problem", "error", "incident",
           "lawsuit", "complaint", "scandal", "fraud", "theft", "attack", "accusation",
           "disaster", "catastrophe", "danger", "warning", "alert", "defect"]
}

def detect_crisis_signals(df: pd.DataFrame, sentiment_col: str = "sentiment", 
                          text_col: str = "text", lang: str = "es") -> Dict[str, Any]:
    """
    Detecta señales de crisis en los datos
    Retorna: {score, severity, signals, crisis_posts}
    """
    if df.empty:
        return {"score": 0, "severity": "none", "signals": [], "crisis_posts": pd.DataFrame()}
    
    signals = []
    crisis_score = 0
    
    # Señal 1: Alto sentimiento negativo
    if sentiment_col in df.columns:
        neg_ratio = (df[sentiment_col] == "NEG").sum() / max(1, len(df))
        if neg_ratio > 0.3:
            signals.append(f"Sentimiento negativo alto: {neg_ratio*100:.1f}%")
            crisis_score += 25
    
    # Señal 2: Palabras clave de crisis
    keywords = CRISIS_KEYWORDS.get(lang, CRISIS_KEYWORDS["es"])
    if text_col in df.columns:
        crisis_texts = df[df[text_col].astype(str).str.lower().str.contains(
            "|".join(keywords), regex=True, na=False
        )]
        if len(crisis_texts) > 0:
            signals.append(f"Posts con palabras clave de crisis: {len(crisis_texts)}")
            crisis_score += min(30, len(crisis_texts) * 5)
    
    # Señal 3: Spike de volumen
    if "created_at_cl" in df.columns:
        try:
            by_hour = df.groupby(df["created_at_cl"].dt.hour).size()
            mean_vol = by_hour.mean()
            max_vol = by_hour.max()
            if max_vol > mean_vol * 3:
                signals.append(f"Spike de volumen: {int(max_vol)} posts en pico (normal: {mean_vol:.0f})")
                crisis_score += 20
        except Exception:
            pass
    
    # Señal 4: Engagement inusual
    if "likes" in df.columns and "comments" in df.columns:
        df_valid = df[(df["likes"] > 0) | (df["comments"] > 0)].copy()
        if not df_valid.empty:
            likes_q75 = df_valid["likes"].quantile(0.75)
            comments_q75 = df_valid["comments"].quantile(0.75)
            high_engagement = df_valid[(df_valid["likes"] > likes_q75 * 2) | 
                                       (df_valid["comments"] > comments_q75 * 2)]
            if len(high_engagement) > len(df) * 0.05:
                signals.append(f"Engagement inusual: {len(high_engagement)} posts con métricas elevadas")
                crisis_score += 15
    
    # Clasificar severidad
    if crisis_score >= 60:
        severity = "critical"
    elif crisis_score >= 40:
        severity = "high"
    elif crisis_score >= 20:
        severity = "medium"
    else:
        severity = "low"
    
    crisis_posts = df[df[text_col].astype(str).str.lower().str.contains(
        "|".join(keywords), regex=True, na=False
    )] if text_col in df.columns else df.head(0)
    
    return {
        "score": min(100, crisis_score),
        "severity": severity,
        "signals": signals,
        "crisis_posts": crisis_posts
    }

# ============================================================================
# TOPIC EXTRACTION
# ============================================================================

def extract_topics(texts: List[str], top_n: int = 10) -> Dict[str, int]:
    """
    Extrae temas/palabras clave frecuentes
    """
    tokens = []
    url_re = re.compile(r"http\S+|www\.\S+", re.I)
    
    for text in texts:
        text = text.lower() if text else ""
        text = url_re.sub(" ", text)
        text = re.sub(r"@\w+|#", " ", text)
        text = unidecode(text)
        text = re.sub(r"[^a-z\s]", " ", text)
        words = [w for w in text.split() if w not in EXTRA_STOP and len(w) > 3]
        tokens.extend(words)
    
    counter = Counter(tokens)
    return dict(counter.most_common(top_n))

# ============================================================================
# HELPERS
# ============================================================================

def _first_series(df: pd.DataFrame, candidates: List[str], default=None) -> pd.Series:
    """Retorna la primera columna que existe en el DataFrame"""
    for c in candidates:
        if c in df.columns and df[c].notna().any():
            return df[c]
    return pd.Series([default] * len(df), index=df.index)

def enforce_date_window(df: pd.DataFrame, d1: Optional[date], d2: Optional[date]) -> pd.DataFrame:
    """Filtra DataFrame por ventana de fechas"""
    if df is None or df.empty:
        return df
    
    if "created_at_cl" not in df.columns or df["created_at_cl"].isna().all():
        if "created_at" in df.columns:
            try:
                df["created_at_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
                df["created_at_cl"] = df["created_at_utc"].dt.tz_convert(SCL_TZ)
            except Exception as e:
                log_message(f"Error convirtiendo fechas: {e}", "warning")
                return df
    
    if "created_at_cl" not in df.columns or df["created_at_cl"].isna().all():
        return df
    
    mask = pd.Series(True, index=df.index)
    if d1:
        mask &= df["created_at_cl"].dt.date >= d1
    if d2:
        mask &= df["created_at_cl"].dt.date <= d2
    
    filtered = df.loc[mask].copy()
    log_message(f"Filtrado de fechas: {len(df)} → {len(filtered)} registros")
    return filtered

def floor_day_local_safe(s: pd.Series) -> pd.Series:
    """Normaliza fechas a día completo evitando errores de DST"""
    try:
        return s.dt.tz_localize(None).dt.normalize()
    except Exception:
        return pd.to_datetime(s.dt.strftime("%Y-%m-%d"))

def retry_on_failure(func: Callable, max_retries: int = MAX_RETRIES, delay: int = RETRY_DELAY, *args, **kwargs):
    """Ejecuta función con reintentos en caso de fallo"""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            if attempt < max_retries - 1:
                log_message(f"Intento {attempt + 1} falló: {e}. Reintentando en {delay}s...", "warning")
                time.sleep(delay * (attempt + 1))
            else:
                log_message(f"Error tras {max_retries} intentos: {e}", "error")
                raise

# ============================================================================
# DEEPSEEK API - SENTIMENT ANALYSIS (POS/NEG/NEU)
# ============================================================================

def analyze_sentiment_deepseek(texts: List[str], batch_size: int = 10, progress_cb: Optional[Callable] = None) -> List[str]:
    """
    Analiza sentimiento usando DeepSeek API
    Retorna lista con valores: POS, NEG, NEU
    """
    deepseek_key = env("DEEPSEEK_API_KEY")
    if not deepseek_key:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en variables de entorno")
    
    sentiments = []
    client = httpx.Client(
        base_url="https://api.deepseek.com",
        headers={"Authorization": f"Bearer {deepseek_key}"}
    )
    
    total_texts = len(texts)
    
    try:
        for batch_idx in range(0, total_texts, batch_size):
            batch = texts[batch_idx:batch_idx + batch_size]
            
            for text_idx, text in enumerate(batch):
                try:
                    prompt = f"""Analiza el sentimiento del siguiente texto y responde SOLO con UNA de estas tres opciones: POS, NEG o NEU

Texto: {text}

Respuesta:"""
                    
                    response = client.post(
                        "/v1/chat/completions",
                        json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0,
                            "max_tokens": 10
                        },
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        sentiment = result['choices'][0]['message']['content'].strip().upper()
                        
                        if sentiment in ["POS", "NEG", "NEU"]:
                            sentiments.append(sentiment)
                        else:
                            log_message(f"Respuesta inválida: {sentiment}, asignando NEU", "warning")
                            sentiments.append("NEU")
                    else:
                        log_message(f"DeepSeek error {response.status_code}", "warning")
                        sentiments.append("NEU")
                
                except Exception as e:
                    log_message(f"Error procesando texto {batch_idx + text_idx}: {e}", "warning")
                    sentiments.append("NEU")
            
            if progress_cb:
                progress = min((batch_idx + batch_size) / total_texts, 1.0)
                progress_cb(progress)
    
    finally:
        client.close()
    
    return sentiments

# ============================================================================
# DEEPSEEK API - EMOTION ANALYSIS (6 categorías Ekman)
# ============================================================================

def analyze_emotions_deepseek(texts: List[str], batch_size: int = 10, progress_cb: Optional[Callable] = None) -> List[str]:
    """
    Analiza emociones usando DeepSeek API
    Retorna lista con valores: RISA, IRA, MIEDO, TRISTEZA, DISGUSTO, SORPRESA, NEUTRAL
    """
    deepseek_key = env("DEEPSEEK_API_KEY")
    if not deepseek_key:
        raise RuntimeError("Falta DEEPSEEK_API_KEY en variables de entorno")
    
    emotions = []
    client = httpx.Client(
        base_url="https://api.deepseek.com",
        headers={"Authorization": f"Bearer {deepseek_key}"}
    )
    
    total_texts = len(texts)
    
    try:
        for batch_idx in range(0, total_texts, batch_size):
            batch = texts[batch_idx:batch_idx + batch_size]
            
            for text_idx, text in enumerate(batch):
                try:
                    prompt = f"""Analiza la emoción predominante del siguiente texto y responde SOLO con UNA de estas opciones: RISA, IRA, MIEDO, TRISTEZA, DISGUSTO, SORPRESA, NEUTRAL

Texto: {text}

Respuesta:"""
                    
                    response = client.post(
                        "/v1/chat/completions",
                        json={
                            "model": "deepseek-chat",
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0,
                            "max_tokens": 15
                        },
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        result = response.json()
                        emotion = result['choices'][0]['message']['content'].strip().upper()
                        
                        if emotion in ["RISA", "IRA", "MIEDO", "TRISTEZA", "DISGUSTO", "SORPRESA", "NEUTRAL"]:
                            emotions.append(emotion)
                        else:
                            log_message(f"Respuesta inválida: {emotion}, asignando NEUTRAL", "warning")
                            emotions.append("NEUTRAL")
                    else:
                        log_message(f"DeepSeek error {response.status_code}", "warning")
                        emotions.append("NEUTRAL")
                
                except Exception as e:
                    log_message(f"Error procesando texto {batch_idx + text_idx}: {e}", "warning")
                    emotions.append("NEUTRAL")
            
            if progress_cb:
                progress = min((batch_idx + batch_size) / total_texts, 1.0)
                progress_cb(progress)
    
    finally:
        client.close()
    
    return emotions


# ============================================================================
# NORMALIZE DATA
# ============================================================================

def normalize_common(rows: List[Dict], platform: str) -> pd.DataFrame:
    """Normaliza datos de diferentes plataformas a esquema común"""
    df = pd.DataFrame(rows) if isinstance(rows, list) else pd.DataFrame()
    if df.empty:
        return df
    
    log_message(f"Normalizando {len(df)} registros de {platform}")
    
    if platform == "x":
        pass
    
    elif platform == "instagram":
        df["text"] = _first_series(df, ["caption", "title", "description", "alt"], "")
        df["username"] = _first_series(df, ["ownerUsername", "authorUsername", "username"], "")
        df["likes"] = pd.to_numeric(_first_series(df, ["likesCount", "likeCount"], 0), errors="coerce").fillna(0)
        df["comments"] = pd.to_numeric(_first_series(df, ["commentsCount", "commentCount"], 0), errors="coerce").fillna(0)
        df["shares"] = pd.to_numeric(_first_series(df, ["shares", "shareCount"], 0), errors="coerce").fillna(0)
        df["views"] = pd.to_numeric(_first_series(df, ["videoPlayCount", "playCount", "views"], 0), errors="coerce").fillna(0)
        
        url_guess = _first_series(df, ["url", "link", "postUrl"], "")
        short_code = _first_series(df, ["shortCode", "shortcode", "code"], None)
        df["url"] = url_guess
        
        try:
            mask_missing_url = url_guess.isna() | (url_guess.astype(str).str.strip() == "")
        except Exception:
            mask_missing_url = pd.Series(False, index=df.index)
        
        if short_code is not None:
            sc_series = short_code.astype(str)
            sc_valid = sc_series.str.len() > 0
            if sc_valid.any():
                df.loc[sc_valid & mask_missing_url, "url"] = "https://www.instagram.com/p/" + sc_series
        
        df["id"] = _first_series(df, ["id", "shortCode", "shortcode", "code", "postId"], "")
        df["created_at"] = _first_series(df, ["timestamp", "takenAt", "publishedTime", "createTime", "taken_at", "created_at"], None)
        
        created_epoch = pd.to_numeric(
            _first_series(df, ["takenAtTimestamp", "taken_at_timestamp", "created_timestamp", "date"], None),
            errors="coerce"
        )
        if created_epoch.notna().any():
            mask = df["created_at"].isna() if "created_at" in df.columns else pd.Series(True, index=df.index)
            if mask.any():
                df.loc[mask, "created_at"] = pd.to_datetime(created_epoch[mask], unit="s", utc=True, errors="coerce")
    
    elif platform == "tiktok":
        df["text"] = _first_series(df, ["text", "title", "desc", "caption"], "")
        
        if "authorMeta" in df.columns:
            try:
                df["username"] = df["authorMeta"].apply(
                    lambda x: (x or {}).get("name") or (x or {}).get("uniqueId") if isinstance(x, dict) else None
                )
            except Exception:
                pass
        
        if "username" not in df.columns or df["username"].isna().all():
            df["username"] = _first_series(df, ["username", "author", "authorUsername", "authorName", "authorUniqueId"], "")
        
        df["likes"] = pd.to_numeric(_first_series(df, ["diggCount", "likeCount"], 0), errors="coerce").fillna(0)
        df["comments"] = pd.to_numeric(_first_series(df, ["commentCount"], 0), errors="coerce").fillna(0)
        df["shares"] = pd.to_numeric(_first_series(df, ["shareCount"], 0), errors="coerce").fillna(0)
        df["views"] = pd.to_numeric(_first_series(df, ["playCount", "viewCount"], 0), errors="coerce").fillna(0)
        df["url"] = _first_series(df, ["webVideoUrl", "url", "shareUrl"], "")
        df["id"] = _first_series(df, ["id", "videoId"], "")
        
        created_iso = _first_series(df, ["createTimeISO", "datetime", "publishedTime"], None)
        created_unix = pd.to_numeric(_first_series(df, ["createTime"], None), errors="coerce")
        df["created_at"] = created_iso
        mask_fill = df["created_at"].isna() & created_unix.notna()
        if mask_fill.any():
            df.loc[mask_fill, "created_at"] = pd.to_datetime(created_unix[mask_fill], unit="s", utc=True, errors="coerce")
    
    elif platform == "facebook":
        df["text"] = _first_series(df, ["text", "content", "message"], "")
        df["username"] = _first_series(df, ["author", "pageName", "username", "from"], "")
        df["likes"] = pd.to_numeric(_first_series(df, ["likes", "reactions"], 0), errors="coerce").fillna(0)
        df["comments"] = pd.to_numeric(_first_series(df, ["comments"], 0), errors="coerce").fillna(0)
        df["shares"] = pd.to_numeric(_first_series(df, ["shares"], 0), errors="coerce").fillna(0)
        df["views"] = pd.to_numeric(_first_series(df, ["views"], 0), errors="coerce").fillna(0)
        df["url"] = _first_series(df, ["url", "postUrl", "link"], "")
        df["id"] = _first_series(df, ["id", "postId"], "")
        df["created_at"] = _first_series(df, ["date", "publishedTime", "time", "createdAt", "timestamp"], None)
    
    try:
        df["created_at_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        df["created_at_cl"] = df["created_at_utc"].dt.tz_convert(SCL_TZ)
        df["fecha_cl"] = df["created_at_cl"].dt.date
    except Exception as e:
        log_message(f"Error procesando fechas: {e}", "warning")
    
    df["platform"] = platform
    
    cols = ["platform", "created_at_cl", "username", "text", "likes", "shares", "comments", "views", "url", "id"]
    final_df = df[[c for c in cols if c in df.columns]]
    
    log_message(f"Normalizados {len(final_df)} registros de {platform}")
    return final_df

# ============================================================================
# X / TWITTER (twitterapi.io)
# ============================================================================

def compose_query_x(topic: str, lang: str, exclude_rt: bool, exclude_repl: bool,
                    d1: Optional[date], d2: Optional[date], filter_chile: bool = False) -> str:
    """Compone query de búsqueda para X"""
    q = topic.strip()
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
    return q

def compose_query_x_user(username: str, lang: str, exclude_rt: bool, exclude_repl: bool,
                         d1: Optional[date], d2: Optional[date], filter_chile: bool = False) -> str:
    """Compone query de usuario para X"""
    u = username.strip().lstrip("@")
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
    return q

def normalize_rows_x(data: Dict) -> List[Dict]:
    """Normaliza respuesta de API de X"""
    rows = []
    for t in data.get("tweets", []) or []:
        a = t.get("author") or {}
        rows.append({
            "id": t.get("id"),
            "created_at": t.get("createdAt"),
            "username": a.get("userName"),
            "text": t.get("text"),
            "likes": t.get("likeCount", 0),
            "comments": t.get("replyCount", 0),
            "shares": t.get("retweetCount", 0),
            "views": t.get("viewCount", 0),
            "url": t.get("url"),
            "platform": "x",
        })
    return rows

def fetch_x(api_key: str, query: str, query_type: str = "Latest", limit: int = 300,
            sleep_s: float = 5.2, progress_cb: Optional[Callable] = None) -> pd.DataFrame:
    """Obtiene tweets de X usando twitterapi.io"""
    headers = {"x-api-key": api_key}
    cursor = None
    seen = 0
    acc = []
    
    log_message(f"Buscando en X: '{query}' (límite: {limit})")
    
    while seen < limit:
        params = {"query": query, "queryType": query_type}
        if cursor:
            params["cursor"] = cursor
        
        try:
            r = requests.get(API_URL_X, headers=headers, params=params, timeout=30)
            
            if r.status_code == 429:
                log_message("Rate limit alcanzado, esperando...", "warning")
                time.sleep(max(sleep_s, 5.2))
                continue
            
            if r.status_code != 200:
                raise RuntimeError(f"X API {r.status_code}: {r.text[:300]}")
            
            data = r.json()
            rows = normalize_rows_x(data)
            
            if not rows:
                break
            
            for row in rows:
                acc.append(row)
                seen += 1
            
            if progress_cb:
                progress_cb(min(seen / max(1, limit), 1.0))
            
            if seen >= limit:
                break
            
            cursor = data.get("next_cursor") if data.get("has_next_page") else None
            if not cursor:
                break
            
            time.sleep(sleep_s)
        
        except Exception as e:
            log_message(f"Error en fetch_x: {e}", "error")
            raise
    
    df = normalize_common(acc, "x")
    
    if not df.empty and "id" in df.columns:
        original_len = len(df)
        df.drop_duplicates(subset=["id"], inplace=True)
        log_message(f"Eliminados {original_len - len(df)} duplicados")
    
    return df

# ============================================================================
# APIFY - Funciones robustas
# ============================================================================

def _apify_fetch_dataset_items(dataset_id: str, token: str, limit: int = 200) -> List[Dict]:
    """Obtiene items de un dataset de Apify"""
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    params = {"token": token, "clean": "1", "limit": str(limit), "format": "json"}
    
    log_message(f"Obteniendo dataset {dataset_id[:8]}...")
    
    r = requests.get(url, params=params, timeout=60)
    
    if r.status_code != 200:
        raise RuntimeError(f"Apify dataset {dataset_id} {r.status_code}: {r.text[:300]}")
    
    ctype = (r.headers.get("Content-Type") or "").lower().strip()
    text = (r.text or "").strip()
    
    if "application/json" in ctype or text.startswith("[") or text.startswith("{"):
        try:
            data = r.json()
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            if isinstance(data, list):
                return data
        except Exception:
            pass
    
    if "ndjson" in ctype or "\n{" in text:
        out = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                pass
        return out
    
    try:
        df_tmp = pd.read_csv(io.StringIO(text))
        return df_tmp.to_dict(orient="records")
    except Exception:
        return []

def _apify_run_async_and_get_items(actor_id: str, token: str, payload: Dict,
                                   limit: int = 200, max_wait_s: int = ASYNC_MAX_WAIT,
                                   poll_every_s: int = ASYNC_POLL_INTERVAL) -> List[Dict]:
    """Ejecuta actor de Apify de forma asíncrona con polling"""
    url_run = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/runs"
    
    log_message(f"Iniciando run asíncrono de {actor_id}")
    
    r = requests.post(url_run, params={"token": token}, json=payload, timeout=30)
    
    if r.status_code not in (200, 201):
        raise RuntimeError(f"Apify {actor_id} start {r.status_code}: {r.text[:300]}")
    
    data = r.json().get("data") or {}
    run_id = data.get("id")
    
    if not run_id:
        raise RuntimeError(f"Apify {actor_id}: no run id en respuesta")
    
    log_message(f"Run ID: {run_id}, esperando finalización...")
    
    url_status = f"https://api.apify.com/v2/actor-runs/{run_id}"
    waited = 0
    status = data.get("status", "RUNNING")
    
    while waited <= max_wait_s:
        time.sleep(poll_every_s)
        waited += poll_every_s
        
        try:
            rr = requests.get(url_status, params={"token": token}, timeout=20)
            
            if rr.status_code == 200:
                d = rr.json().get("data") or {}
                status = d.get("status", status)
                log_message(f"Status: {status} ({waited}s/{max_wait_s}s)")
                
                if status == "SUCCEEDED":
                    dataset_id = d.get("defaultDatasetId") or d.get("datasetId")
                    if not dataset_id:
                        raise RuntimeError(f"Apify {actor_id}: run sin datasetId")
                    return _apify_fetch_dataset_items(dataset_id, token, limit=limit)
                
                if status in ("FAILED", "TIMED-OUT", "ABORTED"):
                    raise RuntimeError(f"Apify {actor_id}: run {status}")
        
        except requests.exceptions.RequestException as e:
            log_message(f"Error en polling: {e}", "warning")
    
    raise RuntimeError(f"Apify {actor_id}: timeout tras {max_wait_s}s (run {run_id})")

def apify_run_sync_items(actor_id: str, token: str, payload: Dict,
                         limit: int = 200, timeout_s: int = DEFAULT_TIMEOUT) -> List[Dict]:
    """Ejecuta actor de Apify con fallback a modo asíncrono"""
    url = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/run-sync-get-dataset-items"
    
    payload_with_proxy = dict(payload)
    payload_with_proxy.setdefault("proxyConfiguration", {"useApifyProxy": True})
    
    params = {"token": token, "limit": str(limit), "clean": "1", "format": "json"}
    
    log_message(f"Ejecutando {actor_id} (sync, timeout={timeout_s}s)")
    
    try:
        r = requests.post(url, params=params, json=payload_with_proxy, timeout=timeout_s)
        
        if r.status_code in (408, 504, 524):
            log_message(f"Timeout {r.status_code}, fallback a modo async", "warning")
            return _apify_run_async_and_get_items(actor_id, token, payload_with_proxy, limit=limit)
        
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Apify {actor_id} {r.status_code}: {r.text[:300]}")
        
        ctype = (r.headers.get("Content-Type") or "").lower().strip()
        text = (r.text or "").strip()
        
        if "application/json" in ctype or text.startswith("{") or text.startswith("["):
            try:
                data = r.json()
                if isinstance(data, dict) and "items" in data:
                    return data["items"]
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        
        if "ndjson" in ctype or "\n{" in text:
            items = []
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    items.append(json.loads(line))
                except Exception:
                    pass
            return items
        
        try:
            df_tmp = pd.read_csv(io.StringIO(text))
            return df_tmp.to_dict(orient="records")
        except Exception:
            return []
    
    except requests.exceptions.ReadTimeout:
        log_message("ReadTimeout, fallback a modo async", "warning")
        return _apify_run_async_and_get_items(
            actor_id, token, payload_with_proxy,
            limit=limit, max_wait_s=max(timeout_s * 2, 300)
        )
    
    except requests.exceptions.RequestException as e:
        log_message(f"RequestException: {e}, fallback a async", "warning")
        return _apify_run_async_and_get_items(actor_id, token, payload_with_proxy, limit=limit)

# ============================================================================
# INSTAGRAM
# ============================================================================

def parse_instagram_usernames(raw: str) -> List[str]:
    """Parse usernames/URLs de Instagram"""
    users = []
    for piece in [p.strip() for p in re.split(r"[ ,]+", raw or "") if p.strip()]:
        if piece.startswith("http://") or piece.startswith("https://"):
            try:
                path = urlparse(piece).path.strip("/")
                user = path.split("/")[0]
                if user:
                    users.append(user)
            except Exception:
                continue
        else:
            users.append(piece.lstrip("@"))
    
    seen = set()
    out = []
    for u in users:
        if u and u not in seen:
            seen.add(u)
            out.append(u)
    return out

def _ig_is_post(item: Dict) -> bool:
    """Detecta si un item es un post de Instagram"""
    if not isinstance(item, dict):
        return False
    
    k = {str(x).lower() for x in item.keys()}
    
    if any(x in k for x in ("shortcode", "short_code", "code")):
        return True
    
    if any(x in k for x in ("caption", "takenat", "takenattimestamp", "timestamp",
                            "publishedtime", "createtime", "created_timestamp", "date")):
        return True
    
    url = str(item.get("url") or item.get("link") or "")
    if "/p/" in url:
        return True
    
    t = str(item.get("type") or "")
    if t in ("post", "Post", "GraphImage", "GraphVideo", "Sidecar"):
        return True
    
    node = item.get("node") or {}
    if isinstance(node, dict):
        if any(k in node for k in ("shortcode", "taken_at_timestamp", "edge_media_to_caption")):
            return True
    
    return False

def _ig_to_post_from_node(node: Dict, username_hint: Optional[str]) -> Dict:
    """Convierte nodo de GraphQL a formato post"""
    caption_edges = (node.get("edge_media_to_caption") or {}).get("edges") or []
    caption_text = caption_edges[0].get("node", {}).get("text") if caption_edges else None
    
    return {
        "shortCode": node.get("shortcode") or node.get("code"),
        "caption": caption_text,
        "takenAtTimestamp": node.get("taken_at_timestamp") or node.get("takenAtTimestamp") or node.get("date"),
        "likesCount": (node.get("edge_liked_by") or {}).get("count") or node.get("like_count"),
        "commentsCount": (node.get("edge_media_to_comment") or {}).get("count") or node.get("comment_count"),
        "videoPlayCount": node.get("video_view_count") or node.get("view_count"),
        "ownerUsername": username_hint,
    }

def _ig_extract_posts_recursive(obj: Any, username_hint: Optional[str], out_list: List):
    """Extrae posts recursivamente de estructuras anidadas"""
    if obj is None:
        return
    
    if isinstance(obj, list):
        for it in obj:
            _ig_extract_posts_recursive(it, username_hint, out_list)
        return
    
    if isinstance(obj, dict):
        if _ig_is_post(obj):
            if "node" in obj and isinstance(obj["node"], dict):
                out_list.append(_ig_to_post_from_node(obj["node"], username_hint))
            else:
                if not obj.get("ownerUsername"):
                    obj["ownerUsername"] = obj.get("username") or username_hint
                if "code" in obj and "shortCode" not in obj:
                    obj["shortCode"] = obj.get("code")
                out_list.append(obj)
        
        for key in (
            "posts", "lastPosts", "recentPosts", "items", "edges", "nodes", "media",
            "feed", "timeline", "timelineMedia", "edge_owner_to_timeline_media",
            "graphql", "user", "edge_felix_video_timeline", "edge_web_feed_timeline"
        ):
            v = obj.get(key)
            if key == "graphql" and isinstance(v, dict):
                v = v.get("user")
            if key in ("edge_owner_to_timeline_media", "edge_felix_video_timeline", "edge_web_feed_timeline"):
                if isinstance(v, dict):
                    v = v.get("edges")
            _ig_extract_posts_recursive(v, username_hint, out_list)

def _ig_extract_posts_from_profile_items(items: List[Dict], username_hint: Optional[str] = None) -> List[Dict]:
    """Extrae posts de perfiles/estructuras anidadas con deduplicación"""
    out: List[Dict] = []
    _ig_extract_posts_recursive(items, username_hint, out)
    
    seen = set()
    uniq = []
    for it in out:
        key = it.get("shortCode") or it.get("id") or it.get("url")
        if key and key not in seen:
            seen.add(key)
            uniq.append(it)
    return uniq

def fetch_instagram_hashtags(apify_token: str, hashtags: List[str], limit: int) -> pd.DataFrame:
    """Obtiene posts de Instagram por hashtags"""
    payload = {"hashtags": hashtags, "resultsType": "posts", "resultsLimit": limit}
    items = retry_on_failure(
        apify_run_sync_items,
        actor_id="apify/instagram-hashtag-scraper",
        token=apify_token,
        payload=payload,
        limit=limit
    )
    items = _ig_extract_posts_from_profile_items(items, username_hint=None)
    return normalize_common(items, "instagram")

#Búsqueda x keyword
def fetch_instagram_keyword_search(apify_token: str, query: str, limit: int) -> pd.DataFrame:
    """
    Busca posts de Instagram por keyword usando apify/instagram-scraper.
    """
    if not query or not query.strip():
        return pd.DataFrame()

    payload = {
        "search": query.strip(),
        "searchType": "hashtag",   # también puede ser 'place' o 'profile'
        "resultsType": "posts",
        "searchLimit": 10,
        "resultsLimit": int(limit),
    }

    items = retry_on_failure(
        apify_run_sync_items,
        actor_id="apify/instagram-scraper",
        token=apify_token,
        payload=payload,
        limit=limit,
    )
    return normalize_common(items, "instagram")

def fetch_instagram_user_posts(apify_token: str, usernames: List[str], limit: int) -> pd.DataFrame:
    """Obtiene posts de usuarios de Instagram con múltiples estrategias"""
    users = [u for u in (usernames or []) if u]
    if not users:
        return pd.DataFrame()
    
    per_user = max(1, int(limit / max(1, len(users))))
    acc: List[Dict] = []
    
    for u in users:
        log_message(f"Procesando usuario IG: @{u}")
        posts: List[Dict] = []
        
        variants = [
            {"username": u, "resultsType": "posts", "resultsLimit": per_user, "maxItems": per_user},
            {"usernames": [u], "resultsType": "posts", "resultsLimit": per_user, "maxItems": per_user},
            {"directUrls": [f"https://www.instagram.com/{u}/"], "resultsType": "posts",
             "resultsLimit": per_user, "maxItems": per_user},
        ]
        
        for i, payload in enumerate(variants, 1):
            try:
                log_message(f"Intentando post-scraper variante {i}/3 para @{u}")
                items = apify_run_sync_items("apify/instagram-post-scraper", apify_token, payload, limit=per_user)
                posts = _ig_extract_posts_from_profile_items(items, username_hint=u)
                if posts:
                    log_message(f"✓ Obtenidos {len(posts)} posts con variante {i}")
                    break
            except Exception as e:
                log_message(f"Variante {i} falló: {e}", "warning")
        
        if not posts:
            try:
                log_message(f"Fallback a profile-scraper para @{u}")
                payload_profile = {"usernames": [u], "resultsType": "posts", "resultsLimit": per_user}
                items = apify_run_sync_items("apify/instagram-profile-scraper", apify_token, payload_profile, limit=per_user)
                posts = _ig_extract_posts_from_profile_items(items, username_hint=u)
                if posts:
                    log_message(f"✓ Obtenidos {len(posts)} posts con profile-scraper")
            except Exception as e:
                log_message(f"Profile-scraper falló: {e}", "error")
        
        for p in posts:
            p["ownerUsername"] = p.get("ownerUsername") or u
        
        acc.extend(posts)
    
    return normalize_common(acc, "instagram")

# ============================================================================
# TIKTOK
# ============================================================================

def fetch_tiktok_hashtags(apify_token: str, hashtags: List[str], limit: int) -> pd.DataFrame:
    """Obtiene videos de TikTok por hashtags"""
    payload = {
        "hashtags": hashtags,
        "resultsPerPage": 100,
        "shouldDownloadVideos": False
    }
    items = retry_on_failure(
        apify_run_sync_items,
        actor_id="clockworks/tiktok-scraper",
        token=apify_token,
        payload=payload,
        limit=limit
    )
    return normalize_common(items, "tiktok")

def fetch_tiktok_user_posts(apify_token: str, usernames: List[str], limit: int) -> pd.DataFrame:
    """Obtiene videos de usuarios de TikTok"""
    payload = {
        "usernames": usernames,
        "resultsPerPage": 100,
        "shouldDownloadVideos": False
    }
    items = retry_on_failure(
        apify_run_sync_items,
        actor_id="clockworks/tiktok-scraper",
        token=apify_token,
        payload=payload,
        limit=limit
    )
    return normalize_common(items, "tiktok")

# ============================================================================
# FACEBOOK
# ============================================================================

def resolve_facebook_start_urls(apify_token: str, raw_input: str) -> List[Dict]:
    """Resuelve usernames/búsquedas a URLs de Facebook"""
    start_urls = []
    for piece in [p.strip() for p in re.split(r"[ ,]+", raw_input or "") if p.strip()]:
        if piece.startswith("http://") or piece.startswith("https://"):
            start_urls.append({"url": piece})
            continue
        
        if " " not in piece:
            start_urls.append({"url": f"https://www.facebook.com/{piece}"})
            continue
        
        try:
            log_message(f"Buscando página de Facebook: '{piece}'")
            search_payload = {
                "query": piece,
                "search_type": "pages",
                "max_pages": 1,
                "recent_posts": True
            }
            items = apify_run_sync_items("danek/facebook-search-ppr", apify_token, search_payload, limit=1)
            if isinstance(items, list) and items:
                cand = items[0]
                for key in ("url", "pageUrl", "pageURL", "pageLink"):
                    if key in cand and str(cand[key]).startswith("http"):
                        start_urls.append({"url": str(cand[key])})
                        log_message(f"✓ Encontrada: {cand[key]}")
                        break
        except Exception as e:
            log_message(f"No se pudo resolver '{piece}': {e}", "warning")
    
    return start_urls

def fetch_facebook_search(apify_token: str, query: str, d1: Optional[date],
                          d2: Optional[date], limit: int) -> pd.DataFrame:
    """Busca posts de Facebook por query"""
    payload = {
        "query": query,
        "search_type": "posts",
        "max_posts": int(limit),
        "recent_posts": True
    }
    items = retry_on_failure(
        apify_run_sync_items,
        actor_id="danek/facebook-search-ppr",
        token=apify_token,
        payload=payload,
        limit=limit
    )
    df = normalize_common(items, "facebook")
    return enforce_date_window(df, d1, d2)

def fetch_facebook_user_posts(apify_token: str, usernames: List[str], limit: int) -> pd.DataFrame:
    """Obtiene posts de páginas/perfiles de Facebook con múltiples fallbacks"""
    raw = ", ".join(usernames)
    start_urls = resolve_facebook_start_urls(apify_token, raw)
    
    if not start_urls:
        log_message("No se pudo resolver URLs de Facebook, usando fallback con búsqueda directa", "warning")
        payload = {
            "query": raw,
            "search_type": "posts",
            "max_posts": int(limit),
            "recent_posts": True
        }
        try:
            items = apify_run_sync_items("danek/facebook-search-ppr", apify_token, payload, limit=limit)
            return normalize_common(items, "facebook")
        except Exception as e:
            log_message(f"Fallback de búsqueda también falló: {e}", "error")
            return pd.DataFrame()
    
    payload = {"startUrls": start_urls, "maxPosts": int(limit)}
    try:
        items = retry_on_failure(
            apify_run_sync_items,
            actor_id="apify/facebook-posts-scraper",
            token=apify_token,
            payload=payload,
            limit=limit
        )
        return normalize_common(items, "facebook")
    except Exception as e:
        log_message(f"posts-scraper falló: {e}, intentando buscar por query", "warning")
        try:
            payload_search = {
                "query": raw,
                "search_type": "posts",
                "max_posts": int(limit),
                "recent_posts": True
            }
            items = apify_run_sync_items("danek/facebook-search-ppr", apify_token, payload_search, limit=limit)
            return normalize_common(items, "facebook")
        except Exception as e2:
            log_message(f"Todos los intentos fallaron: {e2}", "error")
            return pd.DataFrame()

# ============================================================================
# INTERFAZ STREAMLIT
# ============================================================================

st.title("📡 Social Listening Pro — X + Instagram + Facebook + TikTok")
st.markdown("**Análisis avanzado con detección de crisis, sentimiento, emociones y temas**")

st.sidebar.header("⚙️ Configuración de búsqueda")

# Plataforma
platform = st.sidebar.selectbox(
    "Plataforma",
    ["X (Twitter)", "Instagram", "Facebook", "TikTok"],
    index=0,
)

# Modo de búsqueda según plataforma
if platform == "Instagram":
    search_mode = st.sidebar.radio(
        "Modo de búsqueda",
        ["Por temática (hashtags)", "Por temática (búsqueda IG)", "Por usuario/perfil"],
        index=0,
        horizontal=False,
    )
elif platform == "Facebook":
    search_mode = st.sidebar.radio(
        "Modo de búsqueda",
        ["Por temática", "Por usuario/perfil"],
        index=0,
        horizontal=False,
    )
else:
    # X y TikTok
    search_mode = st.sidebar.radio(
        "Modo de búsqueda",
        ["Por temática", "Por usuario"],
        index=0,
        horizontal=False,
    )

# Campos de entrada según modo
topic = ""
username_input = ""

if search_mode.startswith("Por temática"):
    if platform == "Instagram":
        topic = st.sidebar.text_input("Tema / consulta para Instagram", value="")
    else:
        topic = st.sidebar.text_input("Tema / consulta", value="")
else:
    username_input = st.sidebar.text_input(
        "Usuario(s) / URL(s)",
        value="",
        help="Separar por coma si son varios",
    )

# (si usas hashtags_str para IG/TikTok, defínelo aquí)
hashtags_str = st.sidebar.text_input("Hashtag(s)", value="", help="Para Instagram/TikTok por hashtag")

# Parámetros X y generales (SIEMPRE, fuera del if/else anterior)
lang = st.sidebar.selectbox(
    "Idioma (solo X)",
    ["", "es", "en", "pt"],
    index={"": 0, "es": 1, "en": 2, "pt": 3}.get(st.session_state["params"].get("lang", "es"), 1),
)

col1, col2 = st.sidebar.columns(2)
with col1:
    exclude_rt = st.sidebar.checkbox(
        "Excluir RTs [X]",
        value=st.session_state["params"].get("exclude_rt", True),
    )
with col2:
    exclude_repl = st.sidebar.checkbox(
        "Excluir respuestas [X]",
        value=st.session_state["params"].get("exclude_repl", True),
    )

filter_chile = st.sidebar.checkbox(
    "🇨🇱 Filtrar solo posts de Chile (X)",
    value=st.session_state["params"].get("filter_chile", False),
    help="Aplica 'place_country:CL' solo en X/Twitter",
)

st.sidebar.divider()

today = datetime.now(SCL_TZ).date()
d1_default = st.session_state["params"].get("d1", today - timedelta(days=14))
d2_default = st.session_state["params"].get("d2", today)

date_range = st.sidebar.date_input(
    "Rango de fechas (CL)",
    value=(d1_default, d2_default),
    help="Fechas en zona horaria de Chile",
)

col_run, col_clear = st.sidebar.columns(2)
with col_run:
    run_btn = st.button("🔍 Buscar", type="primary", use_container_width=True)
with col_clear:
    clear_btn = st.button("🧹 Limpiar", use_container_width=True)
# ============================================================================
# EJECUCIÓN DE BÚSQUEDA
# ============================================================================

if run_btn:
    st.session_state["logs"] = []
    
    prog = st.progress(0.0, text="Iniciando búsqueda...")
    
    try:
        # X / TWITTER
        if platform.startswith("X"):
            if not api_x:
                st.error("❌ Falta API Key de twitterapi.io")
                st.stop()
            
            if search_mode == "Por usuario":
                if not username_input.strip():
                    st.error("❌ Ingresa al menos un usuario")
                    st.stop()
                qx = compose_query_x_user(username_input, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            else:
                if not (topic and topic.strip()):
                    st.error("❌ Ingresa un tema de búsqueda")
                    st.stop()
                qx = compose_query_x(topic, lang, exclude_rt, exclude_repl, d1, d2, filter_chile)
            
            df = fetch_x(
                api_x, qx,
                query_type=query_type,
                limit=limit,
                sleep_s=5.2,
                progress_cb=lambda x: prog.progress(x, text=f"Obteniendo tweets... {int(x*100)}%")
            )
            
            df = enforce_date_window(df, d1, d2)
            st.session_state["query_str"] = qx
        
        # INSTAGRAM
        elif platform == "Instagram":
            if not api_apify:
                st.error("❌ Falta APIFY_TOKEN")
                st.stop()
            
            if search_mode == "Por usuario/perfil":
                users = parse_instagram_usernames(username_input)
                if not users:
                    st.error("❌ Ingresa usuario(s) o URL(s) de Instagram")
                    st.stop()
                
                prog.progress(0.1, text=f"Procesando {len(users)} usuario(s)...")
                df = fetch_instagram_user_posts(api_apify, users, limit)

            elif search_mode == "Por temática (búsqueda IG)":
                if not (topic and topic.strip()):
                    st.error("❌ Ingresa un tema de búsqueda")
                    st.stop()
                prog.progress(0.1, text="Buscando en Instagram por keyword...")
                df = fetch_instagram_keyword_search(api_apify, topic, limit)

            else:  # "Por temática (hashtags)"
                tags = [t.strip().lstrip("#") for t in re.split(r"[ ,]+", (hashtags_str or topic or "")) if t.strip()]
                if not tags:
                    st.error("❌ Ingresa al menos un hashtag")
                    st.stop()
                
                prog.progress(0.1, text=f"Buscando {len(tags)} hashtag(s)...")
                df = fetch_instagram_hashtags(api_apify, tags, limit)
            
            df = enforce_date_window(df, d1, d2)
            if search_mode.startswith("Por temática"):
                st.session_state["query_str"] = f"IG temática='{topic}'"
            else:
                st.session_state["query_str"] = f"IG users={username_input}"
        
        # TIKTOK
        elif platform == "TikTok":
            if not api_apify:
                st.error("❌ Falta APIFY_TOKEN")
                st.stop()
            
            if search_mode == "Por usuario":
                users = [u.strip().lstrip("@") for u in re.split(r"[ ,]+", username_input or "") if u.strip()]
                if not users:
                    st.error("❌ Ingresa al menos un usuario")
                    st.stop()
                
                prog.progress(0.1, text=f"Procesando {len(users)} usuario(s)...")
                df = fetch_tiktok_user_posts(api_apify, users, limit)
            else:
                tags = [t.strip().lstrip("#") for t in re.split(r"[ ,]+", hashtags_str or "") if t.strip()]
                if not tags:
                    st.error("❌ Ingresa al menos un hashtag")
                    st.stop()
                
                prog.progress(0.1, text=f"Buscando {len(tags)} hashtag(s)...")
                df = fetch_tiktok_hashtags(api_apify, tags, limit)
            
            df = enforce_date_window(df, d1, d2)
            st.session_state["query_str"] = f"TikTok {'users' if search_mode=='Por usuario' else 'hashtags'}"
        
        # FACEBOOK
        elif platform == "Facebook":
            if not api_apify:
                st.error("❌ Falta APIFY_TOKEN")
                st.stop()
            
            if search_mode == "Por usuario/perfil":
                users = [u.strip() for u in re.split(r"[ ,]+", username_input or "") if u.strip()]
                if not users:
                    st.error("❌ Ingresa al menos un usuario o URL")
                    st.stop()
                
                prog.progress(0.1, text="Resolviendo páginas de Facebook...")
                df = fetch_facebook_user_posts(api_apify, users, limit)
                df = enforce_date_window(df, d1, d2)
                st.session_state["query_str"] = f"FB user posts {users}"
            else:
                if not (topic and topic.strip()):
                    st.error("❌ Ingresa un tema de búsqueda")
                    st.stop()
                
                prog.progress(0.1, text="Buscando en Facebook...")
                df = fetch_facebook_search(api_apify, topic, d1, d2, limit)
                st.session_state["query_str"] = f"FB search='{topic}'"
        
        else:
            st.error("❌ Plataforma no soportada")
            st.stop()
        
        prog.empty()

        
        # Resultados
        if df is None or df.empty:
            st.warning("⚠️ No se encontraron resultados con los parámetros especificados")
            st.stop()
        
        else:
            st.session_state["df"] = df
            st.session_state["params"] = {
                "platform": platform,
                "search_mode": search_mode,
                "topic": (topic if 'topic' in locals() else st.session_state["params"].get("topic")),
                "username": (username_input if 'username_input' in locals() else st.session_state["params"].get("username")),
                "lang": lang,
                "exclude_rt": exclude_rt,
                "exclude_repl": exclude_repl,
                "filter_chile": filter_chile,
                "d1": d1,
                "d2": d2,
                "query_type": query_type,
                "limit": limit,
                "hashtags_str": (hashtags_str if 'hashtags_str' in locals() else st.session_state["params"].get("hashtags_str")),
                "sentiment": sentiment,
                "emotions": emotions,
                "max_words": max_words,
            }
            
            st.success(f"✅ Se obtuvieron {len(df)} registros")
            
            if debug:
                st.write("🔧 Debug - Primeros 3 registros:")
                st.dataframe(df.head(3))
    
    except Exception as e:
        prog.empty()
        st.error(f"❌ Error durante la búsqueda: {str(e)}")
        log_message(f"Error crítico: {e}", "error")
        if debug:
            import traceback
            st.code(traceback.format_exc())
        st.stop()

# ============================================================================
# RENDERIZADO DE RESULTADOS
# ============================================================================

df = st.session_state.get("df")

if df is not None and isinstance(df, pd.DataFrame) and not df.empty:
    
    # Análisis de sentimiento
    sentiment_flag = st.session_state["params"].get("sentiment", True)
    
    if sentiment_flag and "sentiment" not in df.columns and "text" in df.columns:
        with st.spinner("🧠 Analizando sentimiento (POS/NEG/NEU)..."):
            try:
                texts_to_analyze = df["text"].astype(str).tolist()
                sentiments = analyze_sentiment_deepseek(texts_to_analyze, batch_size=10)
                df["sentiment"] = sentiments
                st.session_state["df"] = df
                log_message(f"Sentimiento analizado en {len(df)} posts")
            except Exception as e:
                st.info(f"ℹ️ No se pudo aplicar análisis de sentimiento: {e}")
                log_message(f"Error en sentimiento: {e}", "warning")
    
    # Análisis de emociones
    emotions_flag = st.session_state["params"].get("emotions", False)
    
    if emotions_flag and "emotion" not in df.columns and "text" in df.columns:
        with st.spinner("😊 Analizando emociones (Ekman 6)..."):
            try:
                texts_to_analyze = df["text"].astype(str).tolist()
                emotions_result = analyze_emotions_deepseek(texts_to_analyze, batch_size=10)
                df["emotion"] = emotions_result
                st.session_state["df"] = df
                log_message(f"Emociones analizadas en {len(df)} posts")
            except Exception as e:
                st.info(f"ℹ️ No se pudo aplicar análisis de emociones: {e}")
                log_message(f"Error en emociones: {e}", "warning")
    
    # DETECCIÓN DE CRISIS (siempre activa)
    crisis_data = detect_crisis_signals(df, lang=st.session_state["params"].get("lang", "es"))
    
    if crisis_data["score"] > 0:
        severity_colors = {
            "critical": "🔴",
            "high": "🟠",
            "medium": "🟡",
            "low": "🟢"
        }
        severity_emoji = severity_colors.get(crisis_data["severity"], "⚪")
        
        st.header(f"{severity_emoji} Alerta de Crisis Detectada")
        
        col_crisis1, col_crisis2 = st.columns([1, 3])
        
        with col_crisis1:
            st.metric("Score de Crisis", f"{crisis_data['score']}/100")
            st.metric("Severidad", crisis_data["severity"].upper())
        
        with col_crisis2:
            if crisis_data["signals"]:
                st.write("**Señales detectadas:**")
                for signal in crisis_data["signals"]:
                    st.write(f"• {signal}")
        
        if not crisis_data["crisis_posts"].empty:
            with st.expander(f"🚨 Ver {len(crisis_data['crisis_posts'])} posts relacionados con crisis"):
                st.dataframe(crisis_data["crisis_posts"][["created_at_cl", "username", "text", "likes", "comments"]].head(20))
        
        st.divider()
    
    # MÉTRICAS RESUMEN
    total = len(df)
    likes = int(df.get("likes", pd.Series(dtype="float")).fillna(0).sum())
    shares = int(df.get("shares", pd.Series(dtype="float")).fillna(0).sum())
    comments = int(df.get("comments", pd.Series(dtype="float")).fillna(0).sum())
    views = int(df.get("views", pd.Series(dtype="float")).fillna(0).sum()) if "views" in df.columns else 0
    users = df["username"].nunique() if "username" in df.columns else 0
    
    st.header("📈 Resumen de métricas")
    col1, col2, col3, col4, col5, col6 = st.columns(6)
    col1.metric("📊 Posts", f"{total:,}")
    col2.metric("👥 Usuarios", f"{users:,}")
    col3.metric("❤️ Likes", f"{likes:,}")
    col4.metric("🔄 Shares", f"{shares:,}")
    col5.metric("💬 Comentarios", f"{comments:,}")
    col6.metric("👁️ Vistas", f"{views:,}" if views > 0 else "N/A")
    
    # VISUALIZACIONES
    st.header("📊 Visualizaciones")
    
    tabs_list = ["📅 Temporal", "😊 Sentimiento"]
    if "emotion" in df.columns:
        tabs_list.append("🎭 Emociones")
    tabs_list.extend(["🏷️ Temas", "☁️ Nube de palabras"])
    
    viz_tabs = st.tabs(tabs_list)
    tab_idx = 0
    
    # Tab: Temporal
    with viz_tabs[tab_idx]:
        if "created_at_cl" in df.columns and df["created_at_cl"].notna().any():
            col_hour, col_day = st.columns(2)
            
            with col_hour:
                st.subheader("Posts por hora del día")
                by_hour = df["created_at_cl"].dt.hour.value_counts().sort_index().rename("posts")
                fig1, ax1 = plt.subplots(figsize=(8, 4))
                ax1.plot(by_hour.index, by_hour.values, marker="o", linewidth=2, color="#1f77b4")
                ax1.set_xlabel("Hora (Chile)", fontsize=11)
                ax1.set_ylabel("Cantidad de posts", fontsize=11)
                ax1.set_title("Distribución horaria de posts", fontsize=12, fontweight="bold")
                ax1.grid(True, alpha=0.3, linestyle="--")
                ax1.set_xticks(range(0, 24, 2))
                plt.tight_layout()
                st.pyplot(fig1)
                plt.close()
            
            with col_day:
                st.subheader("Posts por día")
                df_valid = df[df["created_at_cl"].notna()].copy()
                if not df_valid.empty:
                    df_valid["fecha_cl"] = floor_day_local_safe(df_valid["created_at_cl"])
                    by_day = df_valid.groupby("fecha_cl").size().rename("posts").sort_index()
                    
                    if not by_day.empty:
                        if len(by_day) > 90:
                            by_day = by_day.iloc[-90:]
                        
                        idx = pd.date_range(start=by_day.index.min(), end=by_day.index.max(), freq="D")
                        by_day = by_day.reindex(idx, fill_value=0)
                        
                        fig2, ax2 = plt.subplots(figsize=(8, 4))
                        ax2.bar(range(len(by_day)), by_day.values, color="#2ca02c", alpha=0.7)
                        ax2.set_xlabel("Fecha (Chile)", fontsize=11)
                        ax2.set_ylabel("Cantidad de posts", fontsize=11)
                        ax2.set_title("Evolución diaria de posts", fontsize=12, fontweight="bold")
                        
                        step = max(1, len(by_day) // 10)
                        xticks_pos = range(0, len(by_day), step)
                        xticks_labels = [by_day.index[i].strftime("%d/%m") for i in xticks_pos]
                        ax2.set_xticks(xticks_pos)
                        ax2.set_xticklabels(xticks_labels, rotation=45, ha="right")
                        ax2.grid(True, alpha=0.3, axis="y", linestyle="--")
                        
                        plt.tight_layout()
                        st.pyplot(fig2)
                        plt.close()
        else:
            st.info("ℹ️ No hay suficientes datos temporales para visualizar")
    
    tab_idx += 1
    
    # Tab: Sentimiento
    with viz_tabs[tab_idx]:
        if "sentiment" in df.columns and df["sentiment"].notna().any():
            col_pie, col_bar = st.columns([1, 1])
            
            with col_pie:
                st.subheader("Distribución de sentimiento (POS/NEG/NEU)")
                dist = df["sentiment"].dropna().value_counts()
                fig3, ax3 = plt.subplots(figsize=(6, 6))
                colors = {"POS": "#2ecc71", "NEG": "#e74c3c", "NEU": "#95a5a6"}
                pie_colors = [colors.get(label, "#3498db") for label in dist.index]
                ax3.pie(
                    dist.values,
                    labels=dist.index,
                    autopct="%1.1f%%",
                    startangle=90,
                    colors=pie_colors,
                    textprops={"fontsize": 11}
                )
                ax3.set_title("Sentimiento de posts", fontsize=12, fontweight="bold")
                ax3.axis("equal")
                plt.tight_layout()
                st.pyplot(fig3)
                plt.close()
            
            with col_bar:
                st.subheader("Conteo por sentimiento")
                fig4, ax4 = plt.subplots(figsize=(6, 6))
                colors_bar = [colors.get(label, "#3498db") for label in dist.index]
                ax4.barh(dist.index, dist.values, color=colors_bar, alpha=0.8)
                ax4.set_xlabel("Cantidad de posts", fontsize=11)
                ax4.set_title("Posts por categoría de sentimiento", fontsize=12, fontweight="bold")
                ax4.grid(True, alpha=0.3, axis="x", linestyle="--")
                for i, (label, value) in enumerate(zip(dist.index, dist.values)):
                    ax4.text(value + max(dist.values)*0.01, i, f"{value:,}", va="center", fontsize=10)
                plt.tight_layout()
                st.pyplot(fig4)
                plt.close()
        else:
            st.info("ℹ️ No hay datos de sentimiento disponibles. Activa el análisis en la configuración.")
    
    tab_idx += 1
    
    # Tab: Emociones (solo si existe)
    if "emotion" in df.columns:
        with viz_tabs[tab_idx]:
            if df["emotion"].notna().any():
                col_pie_emo, col_bar_emo = st.columns([1, 1])

                colors_emo = {
                    "RISA": "#f1c40f",
                    "IRA": "#e74c3c",
                    "MIEDO": "#9b59b6",
                    "TRISTEZA": "#3498db",
                    "DISGUSTO": "#1abc9c",
                    "SORPRESA": "#e67e22",
                    "NEUTRAL": "#95a5a6",
                }

                dist_emo = df["emotion"].dropna().value_counts()
                labels = dist_emo.index.tolist()
                values = dist_emo.values
                pie_colors_emo = [colors_emo.get(label, "#34495e") for label in labels]

                with col_pie_emo:
                    st.subheader("Distribución de emociones")
                    fig5, ax5 = plt.subplots(figsize=(6, 6))
                    ax5.pie(
                        values,
                        labels=labels,
                        autopct="%1.1f%%",
                        startangle=90,
                        colors=pie_colors_emo,
                        textprops={"fontsize": 10},
                    )
                    ax5.set_title("Emociones detectadas", fontsize=12, fontweight="bold")
                    ax5.axis("equal")
                    plt.tight_layout()
                    st.pyplot(fig5)
                    plt.close()

                with col_bar_emo:
                    st.subheader("Conteo por emoción")
                    fig6, ax6 = plt.subplots(figsize=(6, 6))
                    ax6.barh(labels, values, color=pie_colors_emo, alpha=0.8)
                    ax6.set_xlabel("Cantidad de posts", fontsize=11)
                    ax6.set_title("Posts por emoción", fontsize=12, fontweight="bold")
                    ax6.grid(True, alpha=0.3, axis="x", linestyle="--")
                    for i, (label, value) in enumerate(zip(labels, values)):
                        ax6.text(value + max(values) * 0.01, i, f"{value:,}", va="center", fontsize=10)
                    plt.tight_layout()
                    st.pyplot(fig6)
                    plt.close()
            else:
                st.info("ℹ️ No hay datos de emociones disponibles.")
        tab_idx += 1
    
    # Tab: Temas
    with viz_tabs[tab_idx]:
        if "text" in df.columns:
            st.subheader("Temas y palabras clave principales")
            with st.spinner("Extrayendo temas..."):
                texts_for_topics = df["text"].astype(str).tolist()
                topics = extract_topics(texts_for_topics, top_n=15)
                
                if topics:
                    topics_df = pd.DataFrame(list(topics.items()), columns=["Tema", "Frecuencia"])
                    topics_df = topics_df.sort_values("Frecuencia", ascending=False)
                    
                    fig7, ax7 = plt.subplots(figsize=(10, 6))
                    ax7.barh(topics_df["Tema"], topics_df["Frecuencia"], color="#3498db", alpha=0.8)
                    ax7.set_xlabel("Frecuencia", fontsize=11)
                    ax7.set_ylabel("Tema", fontsize=11)
                    ax7.set_title("Top 15 temas/palabras clave", fontsize=12, fontweight="bold")
                    ax7.invert_yaxis()
                    ax7.grid(True, alpha=0.3, axis="x", linestyle="--")
                    plt.tight_layout()
                    st.pyplot(fig7)
                    plt.close()
                    
                    st.dataframe(topics_df, use_container_width=True)
                else:
                    st.info("No se pudieron extraer temas suficientes")
        else:
            st.info("ℹ️ No hay texto disponible para extracción de temas")
    
    tab_idx += 1
    
    # Tab: Nube de palabras
    with viz_tabs[tab_idx]:
        if "text" in df.columns:
            st.subheader("Nube de palabras más frecuentes")
            with st.spinner("Generando nube de palabras..."):
                blob = clean_texts(df["text"])
                wordcloud_from_blob(blob, max_words=st.session_state["params"].get("max_words", 200))
        else:
            st.info("ℹ️ No hay texto disponible para generar nube de palabras")
    
    # TABLA DE RESULTADOS
    st.header("📋 Tabla de resultados")
    
    col_filter1, col_filter2 = st.columns(2)
    
    with col_filter1:
        default_cols = ["platform", "created_at_cl", "username", "text", "likes", "shares", "comments"]
        if "sentiment" in df.columns:
            default_cols.append("sentiment")
        if "emotion" in df.columns:
            default_cols.append("emotion")
        
        show_cols = st.multiselect(
            "Columnas a mostrar",
            options=df.columns.tolist(),
            default=[c for c in default_cols if c in df.columns]
        )
    
    with col_filter2:
        sort_by = st.selectbox(
            "Ordenar por",
            options=[c for c in ["created_at_cl", "likes", "shares", "comments", "views"] if c in df.columns],
            index=0
        )
    
    if show_cols:
        df_display = df[show_cols].sort_values(by=sort_by, ascending=False)
        st.dataframe(df_display, use_container_width=True, height=400)
    else:
        st.dataframe(df, use_container_width=True, height=400)
    
    # EXPORTACIÓN
    st.header("⬇️ Exportar resultados")
    
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        csv_bytes = df_to_csv_bytes(df)
        st.download_button(
            label="📄 Descargar CSV",
            data=csv_bytes,
            file_name=f"social_listening_{platform.lower().replace(' ', '_')}_{datetime.now(SCL_TZ).strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
            use_container_width=True
        )
    
    with col_exp2:
        excel_bytes = df_to_excel_bytes(df)
        st.download_button(
            label="📊 Descargar Excel",
            data=excel_bytes,
            file_name=f"social_listening_{platform.lower().replace(' ', '_')}_{datetime.now(SCL_TZ).strftime('%Y%m%d_%H%M')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True
        )
    
    # LOGS
    if debug and st.session_state.get("logs"):
        with st.expander("🔧 Logs de ejecución"):
            for log in st.session_state["logs"]:
                st.text(log)

else:
    st.info("👋 Configura los parámetros en el panel lateral y pulsa **Buscar** para comenzar")
    
    st.markdown("""
    ### Características principales:
    
    - **Múltiples plataformas**: X (Twitter), Instagram, Facebook, TikTok
    - **Búsqueda flexible**: Por temática o por usuario/perfil
    - **Análisis avanzado**: 
      - 🧠 **Sentimiento** (POS/NEG/NEU)
      - 😊 **Emociones** (RISA, IRA, MIEDO, TRISTEZA, DISGUSTO, SORPRESA)
      - 🚨 **Detección de crisis** automática
      - 🏷️ **Extracción de temas** principales
    - **Exportación**: Descarga resultados en CSV o Excel
    - **Manejo robusto de errores**: Reintentos automáticos y fallbacks
    
    ### Consejos de uso:
    
    1. **X/Twitter**: Usa operadores booleanos para búsquedas complejas (AND, OR, -)
    2. **Instagram**: Puedes ingresar usernames o URLs completas
    3. **Facebook**: Las búsquedas temáticas pueden tardar más tiempo
    4. **Límites**: Ajusta según necesidad (más posts = más tiempo de procesamiento)
    
    ### 🧠 Análisis con DeepSeek API:
    
    - **Sentimiento**: Polaridad general (Positivo/Negativo/Neutral)
    - **Emociones**: Estados afectivos específicos según modelo de Ekman
    - **Requisito**: Debes configurar `DEEPSEEK_API_KEY` en tu `.env`
    - **Costo**: Por tokens consumidos en la API
    """)
    
    st.divider()
    
    st.caption(f"Social Listening Pro • {BUILD_TAG} • Desarrollado para análisis profesional de redes sociales")
