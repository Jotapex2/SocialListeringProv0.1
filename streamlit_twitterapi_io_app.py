# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Optimizado por "Carmack" Persona - V5.4 (Definitive Edition)
# UI: Español | Features: Async Core, Excel Export, Matplotlib Charts (Downloadable)

import os
import io
import time
import asyncio
import logging
import requests
import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
import httpx
from wordcloud import WordCloud, STOPWORDS
from datetime import datetime
from dotenv import load_dotenv
import pytz

# ============================================================================
# 1. CONFIGURACIÓN
# ============================================================================

st.set_page_config(page_title="SocialListening Pro", page_icon="📡", layout="wide")

BUILD_TAG = "JP Release v5.4 - Definitive Edition"
SCL_TZ = pytz.timezone("America/Santiago")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SocialListeningEngine")

API_URL_X = "https://api.twitterapi.io/twitter/tweet/advanced_search"
ASYNC_POLL_INTERVAL = 3

load_dotenv()

# ============================================================================
# 2. UTILS & LOGGING
# ============================================================================

def log_message(msg: str, level: str = "info"):
    timestamp = datetime.now(SCL_TZ).strftime("%H:%M:%S")
    entry = f"[{timestamp}] {msg}"
    if "logs" not in st.session_state: st.session_state["logs"] = []
    st.session_state["logs"].append(entry)
    if level == "error": logger.error(msg)
    else: logger.info(msg)

def env(name: str):
    try: return st.secrets.get(name) or os.getenv(name)
    except: return os.getenv(name)

def to_excel(df):
    """Convierte DataFrame a Bytes Excel compatible con descarga"""
    output = io.BytesIO()
    # Eliminar timezone para compatibilidad con Excel
    df_export = df.copy()
    for col in df_export.select_dtypes(include=['datetime64[ns, America/Santiago]', 'datetimetz']).columns:
        df_export[col] = df_export[col].dt.tz_localize(None)
    
    # Fallback por si quedan columnas tz-aware genéricas
    for col in df_export.columns:
        if pd.api.types.is_datetime64_any_dtype(df_export[col]):
            try:
                df_export[col] = df_export[col].dt.tz_localize(None)
            except: pass

    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_export.to_excel(writer, index=False, sheet_name='SocialData')
    return output.getvalue()

# ============================================================================
# 3. AUTENTICACIÓN
# ============================================================================

USERNAME = "Jota"
PASSWORD = "Ñandu1314"

def check_auth():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            st.title("🔐 Acceso")
            user = st.text_input("Usuario", key="login_user")
            pwd = st.text_input("Contraseña", type="password", key="login_pwd")
            if st.button("Entrar", key="login_btn", use_container_width=True):
                if user == USERNAME and pwd == PASSWORD:
                    st.session_state['logged_in'] = True
                    st.rerun()
                else:
                    st.error("Credenciales incorrectas.")
        st.stop()

# ============================================================================
# 4. MOTOR ASÍNCRONO & APIFY
# ============================================================================

async def async_fetch_deepseek(client: httpx.AsyncClient, prompt: str, max_tokens: int = 10) -> str:
    deepseek_key = env("DEEPSEEK_API_KEY")
    if not deepseek_key: return "NEU"
    try:
        response = await client.post(
            "/v1/chat/completions",
            json={
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0, "max_tokens": max_tokens
            },
            headers={"Authorization": f"Bearer {deepseek_key}"}, timeout=20.0
        )
        if response.status_code == 200:
            return response.json()['choices'][0]['message']['content'].strip().upper()
        return "NEU"
    except: return "NEU"

async def process_sentiment_batch_async(texts):
    async with httpx.AsyncClient(base_url="https://api.deepseek.com") as client:
        tasks = [async_fetch_deepseek(client, f"Sentimiento de: '{t[:200]}'. Responde POS, NEG o NEU.", 10) for t in texts]
        return await asyncio.gather(*tasks)

async def process_emotions_batch_async(texts):
    async with httpx.AsyncClient(base_url="https://api.deepseek.com") as client:
        tasks = [async_fetch_deepseek(client, f"Emoción de: '{t[:200]}'. Responde RISA, IRA, MIEDO, TRISTEZA, DISGUSTO, SORPRESA, NEUTRAL.", 15) for t in texts]
        return await asyncio.gather(*tasks)

def get_apify_items_sync(dataset_id, token):
    url = f"https://api.apify.com/v2/datasets/{dataset_id}/items"
    try:
        r = requests.get(url, params={"token": token, "clean": "1", "format": "json"}, timeout=60)
        return r.json() if r.status_code == 200 else []
    except: return []

def run_apify_actor(actor_id, token, payload):
    url_run = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/runs"
    try:
        r = requests.post(url_run, params={"token": token}, json=payload, timeout=30)
        r.raise_for_status()
        run_data = r.json()["data"]
        run_id, dataset_id = run_data["id"], run_data["defaultDatasetId"]
    except Exception as e:
        log_message(f"Error inicio actor: {e}", "error"); return []

    start = time.time()
    while time.time() - start < 300:
        time.sleep(ASYNC_POLL_INTERVAL)
        try:
            r = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}", params={"token": token}, timeout=10)
            status = r.json()["data"]["status"]
            if status == "SUCCEEDED": return get_apify_items_sync(dataset_id, token)
            if status in ["FAILED", "ABORTED", "TIMED-OUT"]: raise RuntimeError(status)
        except: continue
    return []

# ============================================================================
# 5. NORMALIZACIÓN
# ============================================================================

def normalize_and_clean(df, platform):
    if df.empty: return df
    cols_map = {
        "text": ["caption", "description", "title", "text", "message", "postText"],
        "likes": ["likeCount", "likesCount", "diggCount", "likes", "reactionCount"],
        "comments": ["commentCount", "commentsCount", "comments"],
        "shares": ["shareCount", "retweetCount", "shares"],
        "created_at": ["timestamp", "takenAt", "createTimeISO", "createdAt", "date", "time"]
    }
    for standard, candidates in cols_map.items():
        if standard not in df.columns:
            for c in candidates:
                if c in df.columns:
                    df[standard] = df[c]; break
            if standard not in df.columns: df[standard] = 0 if standard != "created_at" else None

    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
        if df["created_at"].dt.tz is None: df["created_at"] = df["created_at"].dt.tz_localize("UTC")
        else: df["created_at"] = df["created_at"].dt.tz_convert("UTC")
        df["created_at_cl"] = df["created_at"].dt.tz_convert(SCL_TZ)
    
    if "text" in df.columns: df["text"] = df["text"].fillna("").astype(str)
    return df

# ============================================================================
# 6. FETCHERS
# ============================================================================

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_x_data(api_key, query, limit):
    headers = {"x-api-key": api_key}
    all_data, cursor = [], None
    for _ in range((limit // 20) + 2):
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
                all_data.append({
                    "platform": "x", "id": t.get("id"), "created_at": t.get("createdAt"),
                    "username": u.get("userName"), "text": t.get("text"),
                    "likes": t.get("likeCount", 0), "comments": t.get("replyCount", 0),
                    "shares": t.get("retweetCount", 0), "url": t.get("url")
                })
            if len(all_data) >= limit: break
            cursor = data.get("next_cursor") if data.get("has_next_page") else None
        except: break
    return normalize_and_clean(pd.DataFrame(all_data), "x")

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_facebook_data(token, query, mode, limit):
    payload = {"resultsLimit": limit, "maxPosts": limit}
    if mode == "user":
        users = [u.strip() for u in query.split(",")]
        payload["startUrls"] = [{"url": u if "http" in u else f"https://www.facebook.com/{u}"} for u in users]
    else:
        payload["startUrls"] = [{"url": f"https://www.facebook.com/search/posts?q={query}"}]
    try:
        items = run_apify_actor("apify/facebook-posts-scraper", token, payload)
        cleaned = []
        for i in items:
            cleaned.append({
                "platform": "facebook", "text": i.get("text") or i.get("postText"),
                "username": i.get("user", {}).get("name"), "likes": i.get("likes", 0),
                "comments": i.get("comments", 0), "shares": i.get("shares", 0),
                "url": i.get("url") or i.get("postUrl"), "created_at": i.get("time")
            })
        return normalize_and_clean(pd.DataFrame(cleaned), "facebook")
    except: return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_instagram_data(token, query, mode, limit):
    payload = {"resultsLimit": limit, "resultsType": "posts"}
    actor = ""
    if mode == "hashtag":
        actor = "apify/instagram-hashtag-scraper"
        payload["hashtags"] = [query.replace("#","")]
    elif mode == "keyword":
        actor = "apify/instagram-scraper"
        payload["search"] = query
        payload["searchType"] = "hashtag"
    else: # user
        actor = "apify/instagram-post-scraper"
        payload["usernames"] = [query]
    
    try:
        items = run_apify_actor(actor, token, payload)
        return normalize_and_clean(pd.DataFrame(items), "instagram")
    except: return pd.DataFrame()

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_tiktok_data(token, query, mode, limit):
    payload = {"resultsPerPage": 100, "shouldDownloadVideos": False, "limit": limit}
    if mode == "user": payload["usernames"] = [query]
    else: payload["hashtags"] = [query.replace("#","")]
    try:
        items = run_apify_actor("clockworks/tiktok-scraper", token, payload)
        return normalize_and_clean(pd.DataFrame(items), "tiktok")
    except: return pd.DataFrame()

# ============================================================================
# 7. VISUALIZACIÓN (MATPLOTLIB)
# ============================================================================

def plot_pie_chart(series, title):
    if series.empty: return None
    counts = series.value_counts()
    if counts.empty: return None
    
    fig, ax = plt.subplots(figsize=(6, 6))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    
    wedges, texts, autotexts = ax.pie(
        counts, labels=counts.index, autopct='%1.1f%%', startangle=90,
        textprops=dict(color="black")
    )
    ax.set_title(title, fontsize=12, fontweight='bold', color='black')
    return fig

def plot_timeline_bar(df):
    """Gráfico de barras por día usando Matplotlib para ser descargable"""
    if df.empty or "created_at_cl" not in df.columns: return None
    
    # Agrupar por fecha (día)
    df_plot = df.copy()
    df_plot['date_only'] = df_plot['created_at_cl'].dt.date
    daily_counts = df_plot['date_only'].value_counts().sort_index()
    
    if daily_counts.empty: return None
    
    fig, ax = plt.subplots(figsize=(10, 5))
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    
    # Plot
    bars = ax.bar(daily_counts.index.astype(str), daily_counts.values, color="#3498db")
    
    ax.set_title("Evolución de Posts por Día", fontsize=12, fontweight='bold')
    ax.set_ylabel("Cantidad de Posts")
    ax.set_xlabel("Fecha")
    plt.xticks(rotation=45, ha='right')
    ax.grid(axis='y', linestyle='--', alpha=0.5)
    
    # Etiquetas encima de barras
    for bar in bars:
        height = bar.get_height()
        ax.annotate(f'{height}',
                    xy=(bar.get_x() + bar.get_width() / 2, height),
                    xytext=(0, 3),  # 3 points vertical offset
                    textcoords="offset points",
                    ha='center', va='bottom', fontsize=9)
    
    plt.tight_layout()
    return fig

# ============================================================================
# 8. UI PRINCIPAL
# ============================================================================

def perform_ai_analysis(df, sentiment, emotions):
    if df.empty or "text" not in df.columns: return df
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        texts = df["text"].tolist()
        if sentiment:
            st.info("🧠 Analizando Sentimiento (Async)...")
            df["sentiment"] = loop.run_until_complete(process_sentiment_batch_async(texts))
        if emotions:
            st.info("🎭 Analizando Emociones (Async)...")
            df["emotion"] = loop.run_until_complete(process_emotions_batch_async(texts))
    finally: loop.close()
    return df

def main():
    check_auth()
    st.title("🛰️ SocialListening Pro")

    with st.sidebar:
        st.header("Panel de Control")
        
        platform = st.selectbox("Plataforma", 
                                ["X (Twitter)", "Instagram", "Facebook", "TikTok"],
                                key="platform_selector")
        
        query_input = ""
        mode = "search"
        
        # LOGICA DE INPUTS
        if platform == "X (Twitter)":
            mode_sel = st.radio("Modo", ["Palabra Clave", "Usuario (@user)"], key="x_mode")
            mode = "user" if "Usuario" in mode_sel else "keyword"
            query_input = st.text_input("Consulta / Usuario", key="x_query")
        
        elif platform == "Instagram":
            mode_sel = st.radio("Modo", ["Hashtag (#tag)", "Palabra Clave (Búsqueda)", "Usuario (@user)"], key="ig_mode")
            if "Hashtag" in mode_sel: mode = "hashtag"
            elif "Palabra" in mode_sel: mode = "keyword"
            else: mode = "user"
            query_input = st.text_input("Entrada", key="ig_query")

        elif platform == "Facebook":
            mode_sel = st.radio("Modo", ["Usuario/Página", "Búsqueda"], key="fb_mode")
            mode = "user" if "Usuario" in mode_sel else "search"
            query_input = st.text_input("URL Página o Texto", key="fb_query")

        elif platform == "TikTok":
            mode_sel = st.radio("Modo", ["Hashtag", "Usuario"], key="tt_mode")
            mode = "user" if "Usuario" in mode_sel else "hashtag"
            query_input = st.text_input("Tag o Usuario", key="tt_query")

        limit = st.slider("Máx. Posts", 50, 2000, 200, key="global_limit")
        max_words = st.slider("Máx. palabras nube", 50, 500, 200, key="wc_max_words")
        
        st.divider()
        st.caption("Procesamiento IA")
        use_sentiment = st.checkbox("Analizar Sentimiento", value=True, key="chk_sentiment")
        use_emotions = st.checkbox("Analizar Emociones", value=False, key="chk_emotions")
        
        st.divider()
        api_x = st.text_input("Clave TwitterAPI.io", value=env("TWITTERAPI_IO_KEY"), type="password", key="key_x")
        api_apify = st.text_input("Token Apify", value=env("APIFY_TOKEN"), type="password", key="key_apify")
        
        run_btn = st.button("🚀 EJECUTAR BÚSQUEDA", type="primary", use_container_width=True, key="btn_run")

    if run_btn:
        if not query_input:
            st.error("⚠️ Debes ingresar un texto, usuario o hashtag.")
            st.stop()
            
        st.session_state["logs"] = []
        df_result = pd.DataFrame()

        with st.status(f"Buscando en {platform}...", expanded=True) as status:
            status.write("Conectando con APIs...")
            
            if platform.startswith("X"):
                df_result = fetch_x_data(api_x, query_input, limit)
            elif platform == "Facebook":
                df_result = fetch_facebook_data(api_apify, query_input, mode, limit)
            elif platform == "Instagram":
                df_result = fetch_instagram_data(api_apify, query_input, mode, limit)
            elif platform == "TikTok":
                df_result = fetch_tiktok_data(api_apify, query_input, mode, limit)

            if df_result.empty:
                status.update(label="No se encontraron resultados", state="error")
                st.warning("Sin datos. Verifica permisos o términos.")
                st.stop()
            
            status.write("Procesando IA...")
            df_result = perform_ai_analysis(df_result, use_sentiment, use_emotions)
            
            status.update(label="¡Completado!", state="complete")
            st.session_state["df_current"] = df_result

    if "df_current" in st.session_state:
        df = st.session_state["df_current"]
        st.success(f"Se encontraron {len(df)} resultados.")

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Volumen", len(df))
        k2.metric("Interacciones", f"{df['likes'].sum():,}")
        k3.metric("Sentimiento", df['sentiment'].mode()[0] if 'sentiment' in df else "-")
        k4.metric("Fuente", platform)

        tab1, tab2, tab3 = st.tabs(["📄 Datos", "📊 Gráficos (IA)", "📥 Descargas"])
        
        with tab1:
            st.dataframe(df, use_container_width=True)
        
        with tab2:
            st.subheader("Análisis Visual")
            
            # 1. Timeline (Ahora descargable)
            if "created_at_cl" in df.columns:
                fig_time = plot_timeline_bar(df)
                if fig_time: 
                    st.pyplot(fig_time)
            
            st.divider()

            # 2. Charts de IA
            col1, col2 = st.columns(2)
            with col1:
                if "sentiment" in df.columns:
                    fig_sent = plot_pie_chart(df["sentiment"], "Distribución de Sentimiento")
                    if fig_sent: st.pyplot(fig_sent)
            
            with col2:
                if "emotion" in df.columns:
                    fig_emo = plot_pie_chart(df["emotion"], "Distribución de Emociones")
                    if fig_emo: st.pyplot(fig_emo)
            
            st.divider()
            
            # 3. Nube
            if "text" in df.columns:
                text_blob = " ".join(df["text"].astype(str))
                if len(text_blob) > 50:
                    wc = WordCloud(width=800, height=350, background_color="white", max_words=max_words, stopwords=STOPWORDS).generate(text_blob)
                    st.image(wc.to_array(), caption=f"Nube de Palabras (Top {max_words})")

        with tab3:
            st.subheader("Exportar Datos")
            
            col_d1, col_d2 = st.columns(2)
            
            with col_d1:
                # Exportar CSV
                csv = df.to_csv(index=False).encode('utf-8')
                st.download_button("📄 Descargar CSV", csv, "reporte_social.csv", "text/csv", use_container_width=True)
            
            with col_d2:
                # Exportar Excel
                try:
                    excel_data = to_excel(df)
                    st.download_button("📊 Descargar Excel", excel_data, "reporte_social.xlsx", 
                                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                                       use_container_width=True)
                except Exception as e:
                    st.error(f"Error generando Excel: {e}")

            st.divider()
            with st.expander("Logs del Sistema"):
                st.write(st.session_state.get("logs", []))

if __name__ == "__main__":
    main()