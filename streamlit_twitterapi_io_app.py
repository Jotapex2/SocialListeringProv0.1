# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Optimizado por "Carmack" Persona - Async I/O, Robust Caching, Type Safety.
# UI: Español

import os
import re
import io
import time
import json
import pytz
import asyncio
import logging
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import httpx
from wordcloud import WordCloud, STOPWORDS
from unidecode import unidecode
from datetime import datetime, timedelta, date
from dotenv import load_dotenv
from pandas.api.types import is_datetime64tz_dtype
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any, Callable, Union
from collections import Counter

# ============================================================================
# CONFIGURACIÓN DEL MOTOR (ENGINE SETTINGS)
# ============================================================================

st.set_page_config(page_title="SocialListening Pro (Optimizado)", page_icon="🚀", layout="wide")

BUILD_TAG = "Carmack Release v5.1 - Async Core + FB Fix + UI Español"
SCL_TZ = pytz.timezone("America/Santiago")

# Configuración de Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SocialListeningEngine")

# Constantes de Renderizado y API
API_URL_X = "https://api.twitterapi.io/twitter/tweet/advanced_search"
MAX_RETRIES = 3
RETRY_DELAY = 2
DEFAULT_TIMEOUT = 30
ASYNC_POLL_INTERVAL = 5

load_dotenv()

# ============================================================================
# UTILS & CACHING (The "Texture Memory")
# ============================================================================

def log_message(msg: str, level: str = "info"):
    """Inyección thread-safe de logs al estado de la sesión"""
    timestamp = datetime.now(SCL_TZ).strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    if "logs" not in st.session_state:
        st.session_state["logs"] = []
    st.session_state["logs"].append(entry)
    
    if level == "error":
        logger.error(msg)
    elif level == "warning":
        logger.warning(msg)
    else:
        logger.info(msg)

def env(name: str) -> Optional[str]:
    """Recupera variables de entorno de forma segura"""
    try:
        return st.secrets.get(name) or os.getenv(name)
    except Exception:
        return os.getenv(name)

# ============================================================================
# SISTEMA DE AUTENTICACIÓN
# ============================================================================

USERNAME = "Jota"
PASSWORD = "Ñandu1314"

def check_auth():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔐 Acceso Restringido")
            user = st.text_input("Usuario")
            pwd = st.text_input("Contraseña", type="password")
            if st.button("Iniciar Sistema", use_container_width=True):
                if user == USERNAME and pwd == PASSWORD:
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("Acceso Denegado.")
        st.stop()

check_auth()

# ============================================================================
# NÚCLEO ASÍNCRONO (Async API Core)
# ============================================================================

async def async_fetch_deepseek(client: httpx.AsyncClient, prompt: str, max_tokens: int = 10) -> str:
    """Micro-tarea para llamadas concurrentes a DeepSeek"""
    deepseek_key = env("DEEPSEEK_API_KEY")
    if not deepseek_key:
        return "ERROR_NO_KEY"
        
    try:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": max_tokens
            },
            headers={"Authorization": f"Bearer {deepseek_key}"},
            timeout=20.0
        )
        if response.status_code == 200:
            result = response.json()
            return result['choices'][0]['message']['content'].strip().upper()
        return "NEU" # Fallback seguro
    except Exception as e:
        logger.error(f"DeepSeek Async Error: {e}")
        return "NEU"

async def process_sentiment_batch_async(texts: List[str]) -> List[str]:
    """Procesamiento paralelo para Análisis de Sentimiento"""
    async with httpx.AsyncClient(base_url="https://api.deepseek.com") as client:
        tasks = []
        for text in texts:
            prompt = f"Analiza el sentimiento: '{text[:200]}'. Responde SOLO: POS, NEG, o NEU."
            tasks.append(async_fetch_deepseek(client, prompt, 10))
        return await asyncio.gather(*tasks)

async def process_emotions_batch_async(texts: List[str]) -> List[str]:
    """Procesamiento paralelo para Análisis de Emociones"""
    async with httpx.AsyncClient(base_url="https://api.deepseek.com") as client:
        tasks = []
        for text in texts:
            prompt = f"Analiza emoción predominante: '{text[:200]}'. Responde SOLO: RISA, IRA, MIEDO, TRISTEZA, DISGUSTO, SORPRESA, NEUTRAL."
            tasks.append(async_fetch_deepseek(client, prompt, 15))
        return await asyncio.gather(*tasks)

# ============================================================================
# NÚCLEO APIFY (Polling Robusto & Async)
# ============================================================================

def get_apify_items_sync(dataset_id: str, token: str) -> List[Dict]:
    """Obtiene items del dataset de forma eficiente"""
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    params = {"token": token, "clean": "1", "format": "json"}
    try:
        r = requests.get(url, params=params, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        log_message(f"Error obteniendo dataset {dataset_id}: {e}", "error")
        return []

def run_apify_actor(actor_id: str, token: str, payload: Dict, memory_mbytes: int = None) -> List[Dict]:
    """
    Wrapper unificado para ejecución de Actores.
    Maneja el ciclo Ejecutar -> Esperar -> Obtener (Run -> Poll -> Fetch).
    """
    url_run = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/runs"
    params = {"token": token}
    if memory_mbytes:
        params["memory"] = str(memory_mbytes)
        
    # 1. Iniciar Run
    log_message(f"Iniciando actor: {actor_id}")
    try:
        r = requests.post(url_run, params=params, json=payload, timeout=30)
        r.raise_for_status()
        run_data = r.json()["data"]
        run_id = run_data["id"]
        dataset_id = run_data["defaultDatasetId"]
    except Exception as e:
        log_message(f"Error al iniciar {actor_id}: {e}", "error")
        raise e

    # 2. Polling de Estado (Bucle eficiente)
    url_status = f"https://api.apify.com/v2/actor-runs/{run_id}"
    start_time = time.time()
    
    while True:
        if time.time() - start_time > 300: # Timeout absoluto de 5 min
            raise TimeoutError(f"Actor {actor_id} excedió el tiempo límite.")
            
        time.sleep(ASYNC_POLL_INTERVAL)
        try:
            r = requests.get(url_status, params={"token": token}, timeout=10)
            status_data = r.json()["data"]
            status = status_data["status"]
            
            if status == "SUCCEEDED":
                log_message(f"Actor {actor_id} finalizado con éxito.")
                return get_apify_items_sync(dataset_id, token)
            elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                raise RuntimeError(f"El actor falló con estado: {status}")
                
        except Exception as e:
            log_message(f"Error en polling: {e}", "warning")
            continue

# ============================================================================
# FETCHERS DE DATOS (CON CACHÉ)
# ============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_x_data(api_key: str, query: str, limit: int = 100) -> pd.DataFrame:
    """Obtiene datos de X eficientemente via twitterapi.io"""
    headers = {"x-api-key": api_key}
    all_data = []
    cursor = None
    
    # Prevención de bucles infinitos
    max_pages = (limit // 20) + 2
    
    for _ in range(max_pages):
        params = {"query": query, "queryType": "Latest"}
        if cursor:
            params["cursor"] = cursor
            
        try:
            r = requests.get(API_URL_X, headers=headers, params=params, timeout=20)
            if r.status_code == 429:
                time.sleep(5)
                continue
            if r.status_code != 200:
                break
                
            data = r.json()
            tweets = data.get("tweets", [])
            if not tweets:
                break
                
            for t in tweets:
                u = t.get("author", {})
                all_data.append({
                    "platform": "x",
                    "id": t.get("id"),
                    "created_at": t.get("createdAt"),
                    "username": u.get("userName"),
                    "text": t.get("text"),
                    "likes": t.get("likeCount", 0),
                    "comments": t.get("replyCount", 0),
                    "shares": t.get("retweetCount", 0),
                    "views": t.get("viewCount", 0),
                    "url": t.get("url")
                })
                
            if len(all_data) >= limit:
                break
                
            cursor = data.get("next_cursor") if data.get("has_next_page") else None
            if not cursor:
                break
                
        except Exception as e:
            log_message(f"Error Fetch X: {e}", "error")
            break
            
    df = pd.DataFrame(all_data)
    return normalize_and_clean(df, "x")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_facebook_data(token: str, query: str, mode: str, limit: int) -> pd.DataFrame:
    """
    LÓGICA FACEBOOK CORREGIDA.
    Prioriza 'apify/facebook-posts-scraper' para robustez.
    """
    actor = "apify/facebook-posts-scraper"
    payload = {}

    if mode == "user":
        # Manejo de lista de usuarios/páginas
        urls = []
        users = [u.strip() for u in query.split(",")]
        for u in users:
            if "facebook.com" in u:
                urls.append({"url": u})
            else:
                urls.append({"url": f"https://www.facebook.com/{u}"})
        
        payload = {
            "startUrls": urls,
            "resultsLimit": limit,
            "viewPortWidth": 1366, # Anti-detección
            "maxPosts": limit
        }
    else:
        # Modo Búsqueda
        # Fallback: 'danek' suele fallar. Usamos el scraper oficial con URL de búsqueda.
        search_url = f"https://www.facebook.com/search/posts?q={query}"
        payload = {
            "startUrls": [{"url": search_url}],
            "resultsLimit": limit,
            "maxPosts": limit
        }
        log_message("⚠️ Búsqueda FB: Usando navegación directa. La fiabilidad depende de Facebook.", "warning")

    try:
        items = run_apify_actor(actor, token, payload)
        # Normalizar campos complicados de Facebook
        normalized = []
        for i in items:
            normalized.append({
                "platform": "facebook",
                "id": i.get("postId") or i.get("id"),
                "text": i.get("text") or i.get("postText") or i.get("message"),
                "username": i.get("user", {}).get("name") or i.get("facebookUrl"),
                "likes": i.get("likes", 0),
                "comments": i.get("comments", 0),
                "shares": i.get("shares", 0),
                "url": i.get("url") or i.get("postUrl"),
                "created_at": i.get("time") or i.get("timestamp")
            })
        return normalize_and_clean(pd.DataFrame(normalized), "facebook")
    except Exception as e:
        log_message(f"Facebook Scraper falló: {e}", "error")
        return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_instagram_data(token: str, query: str, mode: str, limit: int) -> pd.DataFrame:
    """Fetcher Optimizado Instagram"""
    payload = {"resultsLimit": limit, "resultsType": "posts"}
    actor = ""
    
    if mode == "hashtag":
        actor = "apify/instagram-hashtag-scraper"
        payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
    elif mode == "keyword":
        actor = "apify/instagram-scraper"
        payload = {
            "search": query,
            "searchType": "hashtag",
            "resultsLimit": limit
        }
    else:
        actor = "apify/instagram-post-scraper"
        payload["usernames"] = [u.strip() for u in query.split(",")]
        
    try:
        items = run_apify_actor(actor, token, payload)
        return normalize_and_clean(pd.DataFrame(items), "instagram")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tiktok_data(token: str, query: str, mode: str, limit: int) -> pd.DataFrame:
    actor = "clockworks/tiktok-scraper"
    payload = {"resultsPerPage": 100, "shouldDownloadVideos": False, "limit": limit}
    
    if mode == "user":
        payload["usernames"] = [u.strip() for u in query.split(",")]
    else:
        payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
        
    try:
        items = run_apify_actor(actor, token, payload)
        return normalize_and_clean(pd.DataFrame(items), "tiktok")
    except Exception:
        return pd.DataFrame()

# ============================================================================
# NORMALIZACIÓN DE DATOS (El Pipeline)
# ============================================================================

def normalize_and_clean(df: pd.DataFrame, platform: str) -> pd.DataFrame:
    if df.empty:
        return df

    # Estandarizar columnas
    cols_map = {
        "text": ["caption", "description", "title", "text", "message"],
        "likes": ["likeCount", "likesCount", "diggCount", "likes"],
        "comments": ["commentCount", "commentsCount", "comments"],
        "shares": ["shareCount", "retweetCount", "shares"],
        "views": ["playCount", "viewCount", "videoPlayCount", "views"],
        "created_at": ["timestamp", "takenAt", "createTimeISO", "createdAt", "date"]
    }
    
    for standard, candidates in cols_map.items():
        if standard not in df.columns:
            found = False
            for c in candidates:
                if c in df.columns:
                    df[standard] = df[c]
                    found = True
                    break
            if not found:
                df[standard] = 0 if standard in ["likes", "comments", "shares", "views"] else None

    # Manejo seguro de fechas y zonas horarias
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
        # Asegurar UTC primero
        if df["created_at"].dt.tz is None:
            df["created_at"] = df["created_at"].dt.tz_localize("UTC")
        else:
             df["created_at"] = df["created_at"].dt.tz_convert("UTC")
             
        df["created_at_cl"] = df["created_at"].dt.tz_convert(SCL_TZ)

    # Limpiar texto
    if "text" in df.columns:
        df["text"] = df["text"].fillna("").astype(str)

    # Asegurar numéricos
    metrics = ["likes", "comments", "shares", "views"]
    for m in metrics:
        df[m] = pd.to_numeric(df[m], errors="coerce").fillna(0).astype(int)

    final_cols = ["platform", "created_at_cl", "username", "text", "likes", "comments", "shares", "views", "url", "id"]
    return df[[c for c in final_cols if c in df.columns]]

# ============================================================================
# MOTORES DE ANÁLISIS (Caché & Optimizado)
# ============================================================================

def perform_ai_analysis(df: pd.DataFrame, run_sentiment: bool, run_emotions: bool):
    """
    Orquesta el análisis de IA usando un loop Asyncio dentro de Streamlit síncrono.
    """
    if df.empty or "text" not in df.columns:
        return df

    # Crear nuevo loop para tareas asíncronas en este hilo
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        if run_sentiment and "sentiment" not in df.columns:
            st.info("🧠 Ejecutando Análisis de Sentimiento Async (DeepSeek)...")
            texts = df["text"].tolist()
            # Correr el loop async
            results = loop.run_until_complete(process_sentiment_batch_async(texts))
            df["sentiment"] = results

        if run_emotions and "emotion" not in df.columns:
            st.info("🎭 Ejecutando Análisis de Emociones Async (DeepSeek)...")
            texts = df["text"].tolist()
            results = loop.run_until_complete(process_emotions_batch_async(texts))
            df["emotion"] = results
            
    finally:
        loop.close()
        
    return df

# ============================================================================
# LÓGICA DE INTERFAZ DE USUARIO (UI)
# ============================================================================

def main():
    st.title("🛰️ SocialListening Pro (Núcleo Optimizado)")
    st.markdown("Estado: **Online** | Motor: **Async** | Caché: **Activa**")

    # BARRA LATERAL (SIDEBAR)
    with st.sidebar:
        st.header("Panel de Control")
        platform = st.selectbox("Plataforma", ["X (Twitter)", "Instagram", "Facebook", "TikTok"])
        
        mode = "search"
        query_input = ""
        
        if platform == "X (Twitter)":
            mode_sel = st.radio("Modo", ["Palabra Clave", "Usuario (from:user)"])
            mode = "user" if "Usuario" in mode_sel else "keyword"
            query_input = st.text_input("Consulta / Usuario")
            
        elif platform == "Instagram":
            mode_sel = st.radio("Modo", ["Hashtag", "Búsqueda por Palabra", "Perfil de Usuario"])
            mode = "hashtag" if "Hashtag" in mode_sel else ("keyword" if "Búsqueda" in mode_sel else "user")
            query_input = st.text_input("Entrada (separar por comas si son varios)")

        elif platform == "Facebook":
            mode_sel = st.radio("Modo", ["URL de Página/Usuario", "Búsqueda por Palabra"])
            mode = "user" if "Página" in mode_sel else "search"
            query_input = st.text_input("URL de Página o Palabra Clave")
            if mode == "search":
                st.caption("⚠️ Nota: La búsqueda por palabra en FB está limitada por anti-scraping.")

        elif platform == "TikTok":
            mode_sel = st.radio("Modo", ["Hashtag", "Usuario"])
            mode = "hashtag" if "Hashtag" in mode_sel else "user"
            query_input = st.text_input("Entrada")

        limit = st.slider("Máx. Posts", 50, 2000, 200)
        
        st.divider()
        st.subheader("Procesamiento IA")
        use_sentiment = st.checkbox("Análisis de Sentimiento", value=True)
        use_emotions = st.checkbox("Análisis de Emociones", value=False)
        
        st.divider()
        api_x_key = st.text_input("Clave TwitterAPI.io", value=env("TWITTERAPI_IO_KEY"), type="password")
        api_apify_token = st.text_input("Token Apify", value=env("APIFY_TOKEN"), type="password")
        
        run_btn = st.button("🚀 EJECUTAR", type="primary")

    # EJECUCIÓN PRINCIPAL
    if run_btn:
        if not query_input:
            st.error("Se requiere una entrada de datos.")
            st.stop()

        st.session_state["logs"] = []
        df_result = pd.DataFrame()
        
        with st.status("Procesando Pipeline de Datos...", expanded=True) as status:
            
            # 1. OBTENCIÓN (FETCH)
            status.write(f"Obteniendo datos de {platform}...")
            if platform.startswith("X"):
                q = f"from:{query_input}" if mode == "user" else query_input
                df_result = fetch_x_data(api_x_key, q, limit)
            elif platform == "Facebook":
                df_result = fetch_facebook_data(api_apify_token, query_input, mode, limit)
            elif platform == "Instagram":
                df_result = fetch_instagram_data(api_apify_token, query_input, mode, limit)
            elif platform == "TikTok":
                df_result = fetch_tiktok_data(api_apify_token, query_input, mode, limit)

            if df_result.empty:
                status.update(label="No se encontraron datos", state="error")
                st.warning("No se devolvieron registros. Revisa los inputs y los logs.")
                st.stop()
            
            # 2. ANÁLISIS IA
            status.write("Ejecutando Modelos de Inferencia IA...")
            df_result = perform_ai_analysis(df_result, use_sentiment, use_emotions)
            
            # 3. COMPLETADO
            status.update(label="Pipeline Completado", state="complete")
            st.session_state["df_current"] = df_result

    # VISUALIZACIÓN DE RESULTADOS
    if "df_current" in st.session_state:
        df = st.session_state["df_current"]
        
        # Fila de KPIs
        kpi1, kpi2, kpi3, kpi4 = st.columns(4)
        kpi1.metric("Total Posts", len(df))
        kpi2.metric("Total Me Gusta", f"{df['likes'].sum():,}")
        kpi3.metric("Sentimiento Prom.", df['sentiment'].mode()[0] if 'sentiment' in df else "N/A")
        kpi4.metric("Plataforma", df['platform'].unique()[0].upper())
        
        # Pestañas
        tab1, tab2, tab3 = st.tabs(["📄 Vista de Datos", "📊 Analítica", "📥 Exportar"])
        
        with tab1:
            st.dataframe(df, use_container_width=True)
            
        with tab2:
            col1, col2 = st.columns(2)
            with col1:
                if "sentiment" in df.columns:
                    st.subheader("Distribución de Sentimiento")
                    st.bar_chart(df["sentiment"].value_counts())
            with col2:
                if "created_at_cl" in df.columns:
                    st.subheader("Línea de Tiempo")
                    time_df = df.set_index("created_at_cl").resample("D").size()
                    st.line_chart(time_df)
                    
            if "text" in df.columns:
                st.subheader("Nube de Palabras")
                text_blob = " ".join(df["text"].astype(str).tolist())
                if text_blob.strip():
                    wc = WordCloud(width=800, height=300, background_color="white").generate(text_blob)
                    plt.figure(figsize=(10, 5))
                    plt.imshow(wc, interpolation="bilinear")
                    plt.axis("off")
                    st.pyplot(plt)
                else:
                    st.info("No hay suficiente texto para generar la nube.")

        with tab3:
            csv = df.to_csv(index=False).encode('utf-8')
            st.download_button("Descargar CSV", csv, "social_data.csv", "text/csv")
            
            # Logs de depuración
            with st.expander("Logs del Sistema"):
                for l in st.session_state.get("logs", []):
                    st.text(l)

if __name__ == "__main__":
    main()