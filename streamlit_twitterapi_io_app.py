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
import logging
import streamlit as st
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


st.set_page_config(page_title="SocialListening Pro", page_icon="📡", layout="wide")
BUILD_TAG = "RRSS-Pro v3.0 - Optimized Apify + Enhanced Error Handling. Creado por Juan Pablo González Urriola"
st.caption(f"Build: {BUILD_TAG}")

# Configuración de logging
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
    
    # Asegurar que existe created_at_cl
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
    
    # Aplicar filtros
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
                time.sleep(delay * (attempt + 1))  # Backoff exponencial
            else:
                log_message(f"Error tras {max_retries} intentos: {e}", "error")
                raise

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
        # X/Twitter ya viene normalizado
        pass
    
    elif platform == "instagram":
        # Mapeo de campos Instagram
        df["text"] = _first_series(df, ["caption", "title", "description", "alt"], "")
        df["username"] = _first_series(df, ["ownerUsername", "authorUsername", "username"], "")
        df["likes"] = pd.to_numeric(_first_series(df, ["likesCount", "likeCount"], 0), errors="coerce").fillna(0)
        df["comments"] = pd.to_numeric(_first_series(df, ["commentsCount", "commentCount"], 0), errors="coerce").fillna(0)
        df["shares"] = pd.to_numeric(_first_series(df, ["shares", "shareCount"], 0), errors="coerce").fillna(0)
        df["views"] = pd.to_numeric(_first_series(df, ["videoPlayCount", "playCount", "views"], 0), errors="coerce").fillna(0)
        
        # Construir URLs de posts
        url_guess = _first_series(df, ["url", "link", "postUrl"], "")
        short_code = _first_series(df, ["shortCode", "shortcode", "code"], None)
        df["url"] = url_guess
        
        # Si falta URL pero hay shortcode, construir
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
        
        # Fechas: ISO o epoch
        df["created_at"] = _first_series(df, ["timestamp", "takenAt", "publishedTime", "createTime", "taken_at", "created_at"], None)
        
        # Timestamps epoch
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
        
        # Username desde authorMeta o directo
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
        
        # Fechas
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
    
    # Conversión de fechas a timezone CL
    try:
        df["created_at_utc"] = pd.to_datetime(df["created_at"], utc=True, errors="coerce")
        df["created_at_cl"] = df["created_at_utc"].dt.tz_convert(SCL_TZ)
        df["fecha_cl"] = df["created_at_cl"].dt.date
    except Exception as e:
        log_message(f"Error procesando fechas: {e}", "warning")
    
    df["platform"] = platform
    
    # Columnas finales ordenadas
    cols = ["platform", "created_at_cl", "username", "text", "likes", "shares", "comments", "views", "url", "id"]
    final_df = df[[c for c in cols if c in df.columns]]
    
    log_message(f"Normalizados {len(final_df)} registros de {platform}")
    return final_df

# ============================================================================
# X / TWITTER (twitterapi.io)
# ============================================================================

def compose_query_x(topic: str, lang: str, exclude_rt: bool, exclude_repl: bool, 
                    d1: Optional[date], d2: Optional[date]) -> str:
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
    if d1:
        q += f" since:{d1.isoformat()}_00:00:00_UTC"
    if d2:
        q += f" until:{(d2 + timedelta(days=1)).isoformat()}_00:00:00_UTC"
    
    return q

def compose_query_x_user(username: str, lang: str, exclude_rt: bool, exclude_repl: bool,
                         d1: Optional[date], d2: Optional[date]) -> str:
    """Compone query de usuario para X"""
    u = username.strip().lstrip("@")
    q = f"from:{u}"
    
    if lang:
        q += f" lang:{lang}"
    if exclude_rt:
        q += " -is:retweet"
    if exclude_repl:
        q += " -is:reply"
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
    
    # JSON
    if "application/json" in ctype or text.startswith("[") or text.startswith("{"):
        try:
            data = r.json()
            if isinstance(data, dict) and "items" in data:
                return data["items"]
            if isinstance(data, list):
                return data
        except Exception:
            pass
    
    # NDJSON
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
    
    # CSV fallback
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
    
    # Añadir proxy de Apify
    payload_with_proxy = dict(payload)
    payload_with_proxy.setdefault("proxyConfiguration", {"useApifyProxy": True})
    
    params = {"token": token, "limit": str(limit), "clean": "1", "format": "json"}
    
    log_message(f"Ejecutando {actor_id} (sync, timeout={timeout_s}s)")
    
    try:
        r = requests.post(url, params=params, json=payload_with_proxy, timeout=timeout_s)
        
        # Timeout o error de gateway → fallback async
        if r.status_code in (408, 504, 524):
            log_message(f"Timeout {r.status_code}, fallback a modo async", "warning")
            return _apify_run_async_and_get_items(actor_id, token, payload_with_proxy, limit=limit)
        
        if r.status_code not in (200, 201):
            raise RuntimeError(f"Apify {actor_id} {r.status_code}: {r.text[:300]}")
        
        ctype = (r.headers.get("Content-Type") or "").lower().strip()
        text = (r.text or "").strip()
        
        # JSON
        if "application/json" in ctype or text.startswith("{") or text.startswith("["):
            try:
                data = r.json()
                if isinstance(data, dict) and "items" in data:
                    return data["items"]
                if isinstance(data, list):
                    return data
            except Exception:
                pass
        
        # NDJSON
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
        
        # CSV
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
    
    # Deduplicate
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
    
    # Indicadores de post
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
    
    # Nodos anidados
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
        # Si es un post, agregar
        if _ig_is_post(obj):
            if "node" in obj and isinstance(obj["node"], dict):
                out_list.append(_ig_to_post_from_node(obj["node"], username_hint))
            else:
                if not obj.get("ownerUsername"):
                    obj["ownerUsername"] = obj.get("username") or username_hint
                if "code" in obj and "shortCode" not in obj:
                    obj["shortCode"] = obj.get("code")
                out_list.append(obj)
        
        # Seguir recorriendo claves relevantes
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
    
    # Deduplicación
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
        
        # Estrategia 1: post-scraper (3 variantes)
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
        
        # Estrategia 2: profile-scraper (fallback)
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
        
        # Asegurar username en todos los posts
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
        # URL directa
        if piece.startswith("http://") or piece.startswith("https://"):
            start_urls.append({"url": piece})
            continue
        
        # Username simple
        if " " not in piece:
            start_urls.append({"url": f"https://www.facebook.com/{piece}"})
            continue
        
        # Búsqueda de página
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
    """Obtiene posts de páginas/perfiles de Facebook"""
    raw = ", ".join(usernames)
    start_urls = resolve_facebook_start_urls(apify_token, raw)
    
    if not start_urls:
        raise RuntimeError("No se pudo resolver el/los usuarios de Facebook a URL de página/perfil.")
    
    payload = {"startUrls": start_urls, "maxPosts": int(limit)}
    items = retry_on_failure(
        apify_run_sync_items,
        actor_id="apify/facebook-posts-scraper",
        token=apify_token,
        payload=payload,
        limit=limit
    )
    return normalize_common(items, "facebook")

# ============================================================================
# INTERFAZ STREAMLIT
# ============================================================================

st.title("📡 Social Listening Pro — X + Instagram + Facebook + TikTok")
st.markdown("**Análisis avanzado de redes sociales con gestión robusta de errores**")

# SIDEBAR
with st.sidebar:
    st.header("⚙️ Configuración")
    
    platform = st.selectbox(
        "Plataforma",
        ["X (Twitter)", "Instagram", "Facebook", "TikTok"],
        index=0
    )
    
    api_x = st.text_input(
        "API Key twitterapi.io (X)",
        value=(env("TWITTERAPI_IO_KEY") or ""),
        type="password"
    )
    
    api_apify = st.text_input(
        "APIFY_TOKEN (Apify)",
        value=(env("APIFY_TOKEN") or ""),
        type="password"
    )
    
    st.divider()
    
    search_mode = st.radio(
        "Modo de búsqueda",
        ["Por temática", "Por usuario"],
        horizontal=True,
        index=0
    )
    
    if search_mode == "Por temática":
        topic = st.text_area(
            "Tema / consulta (X/FB)",
            value=st.session_state["params"].get("topic", "inteligencia artificial Chile"),
            height=80,
            help="Para X: usa operadores booleanos (AND, OR, -)"
        )
        hashtags_str = st.text_input(
            "Hashtags (IG/TikTok) sin #, separados por espacio/coma",
            value=st.session_state["params"].get("hashtags_str", "machinelearning datascience"),
            help="Ejemplo: machinelearning, datascience, chile"
        )
    else:
        username_input = st.text_input(
            "Usuario(s) / URL(s) (coma o espacio)",
            value=st.session_state["params"].get("username", ""),
            help="Ejemplo: @usuario, url_completa, o múltiples separados por coma"
        )
    
    st.divider()
    
    lang = st.selectbox(
        "Idioma (solo X)",
        ["", "es", "en", "pt"],
        index={"": 0, "es": 1, "en": 2, "pt": 3}.get(st.session_state["params"].get("lang", "es"), 1)
    )
    
    col1, col2 = st.columns(2)
    with col1:
        exclude_rt = st.checkbox(
            "Excluir RTs [X]",
            value=st.session_state["params"].get("exclude_rt", True)
        )
    with col2:
        exclude_repl = st.checkbox(
            "Excluir respuestas [X]",
            value=st.session_state["params"].get("exclude_repl", True)
        )
    
    st.divider()
    
    today = datetime.now(SCL_TZ).date()
    d1_default = st.session_state["params"].get("d1", today - timedelta(days=14))
    d2_default = st.session_state["params"].get("d2", today)
    
    date_range = st.date_input(
        "Rango de fechas (CL)",
        value=(d1_default, d2_default),
        help="Fechas en zona horaria de Chile"
    )
    
    if isinstance(date_range, tuple) and len(date_range) == 2:
        d1, d2 = date_range
    else:
        d1, d2 = date_range, date_range
    
    query_type = st.selectbox(
        "Orden (X)",
        ["Latest", "Top"],
        index=0 if st.session_state["params"].get("query_type", "Latest") == "Latest" else 1
    )
    
    limit = st.slider("Límite de posts", 50, 5000, st.session_state["params"].get("limit", 300), 50)
    max_words = st.slider("Máx. palabras nube", 50, 500, st.session_state["params"].get("max_words", 200), 25)
    
    sentiment = st.checkbox(
        "Analizar sentimiento (español)",
        value=st.session_state["params"].get("sentiment", True),
        help="Usa pysentimiento para análisis de sentimiento"
    )
    
    debug = st.checkbox("🔧 Modo debug", value=False)
    
    st.divider()
    
    col_run, col_clear = st.columns(2)
    with col_run:
        run_btn = st.button("🔍 Buscar", type="primary", use_container_width=True)
    with col_clear:
        clear_btn = st.button("🧹 Limpiar", use_container_width=True)

# PREVIEW
with st.expander("🔎 Vista previa de consulta"):
    if platform.startswith("X"):
        if search_mode == "Por usuario":
            u = username_input if 'username_input' in locals() else st.session_state["params"].get("username", "")
            preview_query = compose_query_x_user(u, lang, exclude_rt, exclude_repl, d1, d2)
        else:
            t = topic if 'topic' in locals() else st.session_state["params"].get("topic", "")
            preview_query = compose_query_x(t, lang, exclude_rt, exclude_repl, d1, d2)
        st.code(preview_query, language="text")
    elif platform == "Instagram":
        st.info(f"IG → {'Perfiles: ' + username_input if search_mode == 'Por usuario' else 'Hashtags: ' + hashtags_str}")
    elif platform == "TikTok":
        st.info(f"TikTok → {'Perfiles: ' + username_input if search_mode == 'Por usuario' else 'Hashtags: ' + hashtags_str}")
    elif platform == "Facebook":
        st.info(f"FB → {'Páginas/perfiles: ' + username_input if search_mode == 'Por usuario' else 'Búsqueda: ' + topic}")

# CLEAR
if clear_btn:
    st.session_state["df"] = None
    st.session_state["params"] = {}
    st.session_state["query_str"] = None
    st.session_state["logs"] = []
    st.rerun()

# ============================================================================
# EJECUCIÓN DE BÚSQUEDA
# ============================================================================

if run_btn:
    # Limpiar logs previos
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
                qx = compose_query_x_user(username_input, lang, exclude_rt, exclude_repl, d1, d2)
            else:
                if not (topic and topic.strip()):
                    st.error("❌ Ingresa un tema de búsqueda")
                    st.stop()
                qx = compose_query_x(topic, lang, exclude_rt, exclude_repl, d1, d2)
            
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
            
            if search_mode == "Por usuario":
                users = parse_instagram_usernames(username_input)
                if not users:
                    st.error("❌ Ingresa usuario(s) o URL(s) de Instagram")
                    st.stop()
                prog.progress(0.1, text=f"Procesando {len(users)} usuario(s)...")
                df = fetch_instagram_user_posts(api_apify, users, limit)
            else:
                tags = [t.strip().lstrip("#") for t in re.split(r"[ ,]+", hashtags_str or "") if t.strip()]
                if not tags:
                    st.error("❌ Ingresa al menos un hashtag")
                    st.stop()
                prog.progress(0.1, text=f"Buscando {len(tags)} hashtag(s)...")
                df = fetch_instagram_hashtags(api_apify, tags, limit)
            
            df = enforce_date_window(df, d1, d2)
            st.session_state["query_str"] = f"IG {'users' if search_mode=='Por usuario' else 'hashtags'}"
        
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
            
            if search_mode == "Por usuario":
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
                "d1": d1,
                "d2": d2,
                "query_type": query_type,
                "limit": limit,
                "hashtags_str": (hashtags_str if 'hashtags_str' in locals() else st.session_state["params"].get("hashtags_str")),
                "sentiment": sentiment,
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

if df is not None and not df.empty:
    # Análisis de sentimiento
if sentimentflag and sentiment not in df.columns and text in df.columns:
    with st.spinner("Analizando sentimiento con DeepSeek API..."):
        try:
            deepseek_key = env("DEEPSEEK_API_KEY")
            if not deepseek_key:
                st.error("Falta DEEPSEEK_API_KEY en variables de entorno")
                st.stop()
            
            @st.cache_resource(show_spinner=False)
            def get_deepseek_analyzer():
                import httpx
                return httpx.Client(
                    base_url="https://api.deepseek.com",
                    headers={"Authorization": f"Bearer {deepseek_key}"}
                )
            
            client = get_deepseek_analyzer()
            sentiments = []
            
            # Procesamiento en lotes para mejor performance
            batch_size = 10
            for i in range(0, len(df), batch_size):
                batch = df['text'].astype(str).iloc[i:i+batch_size].tolist()
                
                for text in batch:
                    try:
                        # Prompt en español para análisis de sentimiento
                        prompt = f"""Analiza el sentimiento del siguiente texto y responde SOLO con una de estas tres opciones: POS, NEG o NEU

Texto: {text}

Respuesta:"""
                        
                        response = client.post(
                            "/v1/chat/completions",
                            json={
                                "model": "deepseek-chat",
                                "messages": [
                                    {"role": "user", "content": prompt}
                                ],
                                "temperature": 0,
                                "max_tokens": 10
                            },
                            timeout=30
                        )
                        
                        if response.status_code == 200:
                            result = response.json()
                            sentiment = result['choices'][0]['message']['content'].strip().upper()
                            
                            # Validar que sea uno de los 3 valores
                            if sentiment in ["POS", "NEG", "NEU"]:
                                sentiments.append(sentiment)
                            else:
                                sentiments.append("NEU")
                        else:
                            log_message(f"DeepSeek error {response.status_code}", "warning")
                            sentiments.append(None)
                    
                    except Exception as e:
                        log_message(f"Error procesando texto: {e}", "warning")
                        sentiments.append(None)
                
                # Mostrar progreso
                progress = min((i + batch_size) / len(df), 1.0)
                prog.progress(progress, text=f"Procesado {min(i+batch_size, len(df))}/{len(df)}...")
            
            df['sentiment'] = sentiments
            st.session_state.df = df
            log_message(f"Sentimiento analizado en {len(df)} posts")
        
        except Exception as e:
            st.info(f"No se pudo aplicar análisis de sentimiento: {e}")
            log_message(f"Error en sentimiento: {e}", "warning")

    
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
    
    viz_tabs = st.tabs(["📅 Temporal", "😊 Sentimiento", "☁️ Nube de palabras"])
    
    # Tab 1: Temporal
    with viz_tabs[0]:
        if "created_at_cl" in df.columns and df["created_at_cl"].notna().any():
            col_hour, col_day = st.columns(2)
            
            # Posts por hora
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
            
            # Posts por día
            with col_day:
                st.subheader("Posts por día")
                df_valid = df[df["created_at_cl"].notna()].copy()
                
                if not df_valid.empty:
                    df_valid["fecha_cl"] = floor_day_local_safe(df_valid["created_at_cl"])
                    by_day = df_valid.groupby("fecha_cl").size().rename("posts").sort_index()
                    
                    if not by_day.empty:
                        # Limitar a últimos 90 días si hay más
                        if len(by_day) > 90:
                            by_day = by_day.iloc[-90:]
                        
                        # Rellenar días faltantes
                        idx = pd.date_range(start=by_day.index.min(), end=by_day.index.max(), freq="D")
                        by_day = by_day.reindex(idx, fill_value=0)
                        
                        fig2, ax2 = plt.subplots(figsize=(8, 4))
                        ax2.bar(range(len(by_day)), by_day.values, color="#2ca02c", alpha=0.7)
                        ax2.set_xlabel("Fecha (Chile)", fontsize=11)
                        ax2.set_ylabel("Cantidad de posts", fontsize=11)
                        ax2.set_title("Evolución diaria de posts", fontsize=12, fontweight="bold")
                        
                        # Etiquetas de fecha cada N días
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
    
    # Tab 2: Sentimiento
    with viz_tabs[1]:
        if "sentiment" in df.columns and df["sentiment"].notna().any():
            col_pie, col_bar = st.columns([1, 1])
            
            with col_pie:
                st.subheader("Distribución de sentimiento")
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
    
    # Tab 3: Nube de palabras
    with viz_tabs[2]:
        if "text" in df.columns:
            st.subheader("Nube de palabras más frecuentes")
            with st.spinner("Generando nube de palabras..."):
                blob = clean_texts(df["text"])
                wordcloud_from_blob(blob, max_words=st.session_state["params"].get("max_words", 200))
        else:
            st.info("ℹ️ No hay texto disponible para generar nube de palabras")
    
    # TABLA DE RESULTADOS
    st.header("📋 Tabla de resultados")
    
    # Opciones de visualización
    col_filter1, col_filter2 = st.columns(2)
    
    with col_filter1:
        show_cols = st.multiselect(
            "Columnas a mostrar",
            options=df.columns.tolist(),
            default=[c for c in ["platform", "created_at_cl", "username", "text", "likes", "shares", "comments"] if c in df.columns]
        )
    
    with col_filter2:
        sort_by = st.selectbox(
            "Ordenar por",
            options=[c for c in ["created_at_cl", "likes", "shares", "comments", "views"] if c in df.columns],
            index=0
        )
    
    # Mostrar tabla
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
    
    # LOGS (si debug está activo)
    if debug and st.session_state.get("logs"):
        with st.expander("🔧 Logs de ejecución"):
            for log in st.session_state["logs"]:
                st.text(log)

else:
    # Estado inicial
    st.info("👋 Configura los parámetros en el panel lateral y pulsa **Buscar** para comenzar")
    
    st.markdown("""
    ### Características principales:
    
    - **Múltiples plataformas**: X (Twitter), Instagram, Facebook, TikTok
    - **Búsqueda flexible**: Por temática o por usuario/perfil
    - **Análisis avanzado**: Sentimiento, tendencias temporales, nube de palabras
    - **Exportación**: Descarga resultados en CSV o Excel
    - **Manejo robusto de errores**: Reintentos automáticos y fallbacks
    
    ### Consejos de uso:
    
    1. **X/Twitter**: Usa operadores booleanos para búsquedas complejas (AND, OR, -)
    2. **Instagram**: Puedes ingresar usernames o URLs completas
    3. **Facebook**: Las búsquedas temáticas pueden tardar más tiempo
    4. **Límites**: Ajusta según necesidad (más posts = más tiempo de procesamiento)
    """)

st.divider()
st.caption(f"Social Listening Pro • {BUILD_TAG} • Desarrollado para análisis profesional de redes sociales")
