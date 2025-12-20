# Streamlit Social Listening: X (twitterapi.io) + Instagram/Facebook/TikTok (Apify)
# Optimizado por "JP" Persona - V6.8 (MASTER FINAL)
# UI: Español | Feat: Stealth Credentials + Email Reporting + AI Analyst Summary + Full Fetchers

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
# 1. CONFIGURACIÓN INICIAL
# ============================================================================

st.set_page_config(page_title="SocialListening Pro", page_icon="📡", layout="wide")

BUILD_TAG = "JP Release v6.8 - Master Edition (AI Analyst)"
st.caption(f"Build: {BUILD_TAG}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SCL_TZ = pytz.timezone("America/Santiago")
API_URL_X = "https://api.twitterapi.io/twitter/tweet/advanced_search"
ASYNC_POLL_INTERVAL = 3

load_dotenv()

# Inicializar Session State
state_vars = {
    "df": None, "params": {}, "query_str": None, 
    "logs": [], "report_figures": {}, "ai_summary": None, "logged_in": False
}
for k, v in state_vars.items():
    if k not in st.session_state:
        st.session_state[k] = v

def env(name: str) -> Optional[str]:
    try: return st.secrets.get(name) or os.getenv(name)
    except: return os.getenv(name)

def log_message(msg: str, level: str = "info"):
    timestamp = datetime.now(SCL_TZ).strftime("%H:%M:%S")
    if level == "error": logger.error(msg)
    else: logger.info(msg)

# ============================================================================
# 2. LOGIN
# ============================================================================

ADMIN_USER = env("ADMIN_USER") or "admin"
ADMIN_PASS = env("ADMIN_PASS") or "admin123"

if not st.session_state['logged_in']:
    st.title("🔐 Acceso Seguro")
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        u = st.text_input("Usuario")
        p = st.text_input("Contraseña", type="password")
        if st.button("Entrar", use_container_width=True):
            if u == ADMIN_USER and p == ADMIN_PASS:
                st.session_state['logged_in'] = True
                st.rerun()
            else: st.error("Credenciales incorrectas")
    st.stop()

# ============================================================================
# 3. FUNCIONES DE CORREO (SMTP)
# ============================================================================

def fig_to_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches='tight')
    buf.seek(0)
    return buf.read()

def send_email_report(to_email, subject, body_text, df_xlsx, df_csv, figures_dict):
    """Envía correo con el resumen en el cuerpo y adjuntos (Data + Gráficos)"""
    smtp_server = env("SMTP_HOST") or "smtp.gmail.com"
    smtp_port = int(env("SMTP_PORT") or 587)
    smtp_user = env("SMTP_USER")
    smtp_pass = env("SMTP_PASS")

    if not smtp_user or not smtp_pass:
        return False, "Faltan credenciales SMTP (.env)"

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = to_email
    msg['Subject'] = subject
    
    # Cuerpo del mensaje (UTF-8)
    msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    # Adjuntos Data
    if df_xlsx:
        p = MIMEBase('application', "octet-stream")
        p.set_payload(df_xlsx)
        encoders.encode_base64(p)
        p.add_header('Content-Disposition', 'attachment; filename="data.xlsx"')
        msg.attach(p)

    if df_csv:
        p = MIMEBase('application', "octet-stream")
        p.set_payload(df_csv)
        encoders.encode_base64(p)
        p.add_header('Content-Disposition', 'attachment; filename="data.csv"')
        msg.attach(p)

    # Adjuntos Imágenes
    for name, b in figures_dict.items():
        img = MIMEImage(b, name=f"{name}.png")
        img.add_header('Content-Disposition', f'attachment; filename="{name}.png"')
        msg.attach(img)

    try:
        s = smtplib.SMTP(smtp_server, smtp_port)
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, to_email, msg.as_string())
        s.quit()
        return True, "Correo enviado exitosamente."
    except Exception as e:
        return False, f"Error SMTP: {str(e)}"

# ============================================================================
# 4. MOTOR IA (DEEPSEEK) - ASYNC & SUMMARY
# ============================================================================

async def async_fetch_deepseek(client, prompt, sem, max_tokens=10):
    key = env("DEEPSEEK_API_KEY")
    if not key: return "NEU"
    async with sem:
        try:
            resp = await client.post(
                "/v1/chat/completions",
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.1, "max_tokens": max_tokens},
                headers={"Authorization": f"Bearer {key}"}, timeout=45.0
            )
            if resp.status_code == 200:
                return resp.json()['choices'][0]['message']['content'].strip()
            return "NEU"
        except: return "NEU"

async def process_batch(texts, mode="sentiment"):
    sem = asyncio.Semaphore(10)
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(base_url="https://api.deepseek.com", limits=limits, timeout=60) as client:
        tasks = []
        for t in texts:
            safe_t = t[:300].replace("\n", " ")
            if mode == "sentiment":
                p = f"Clasifica sentimiento: '{safe_t}'. Responde SOLO: POS, NEG, NEU."
                tasks.append(async_fetch_deepseek(client, p, sem, 5))
            else:
                p = f"Detecta emoción: '{safe_t}'. Opciones: RISA, IRA, MIEDO, TRISTEZA, DISGUSTO, SORPRESA, NEUTRAL. Responde SOLO la palabra."
                tasks.append(async_fetch_deepseek(client, p, sem, 10))
        
        raw_results = await asyncio.gather(*tasks)
        
        clean = []
        for r in raw_results:
            r = r.upper().replace(".","")
            if mode == "sentiment":
                clean.append(r if r in ["POS","NEG","NEU"] else "NEU")
            else:
                valid = ["RISA", "IRA", "MIEDO", "TRISTEZA", "DISGUSTO", "SORPRESA", "NEUTRAL"]
                found = next((v for v in valid if v in r), "NEUTRAL")
                clean.append(found)
        return clean

def analyze_sentiment(texts): 
    if not texts: return []
    return asyncio.run(process_batch(texts, "sentiment"))

def analyze_emotions(texts): 
    if not texts: return []
    return asyncio.run(process_batch(texts, "emotions"))

def generate_executive_summary(df: pd.DataFrame, query: str) -> str:
    """Genera resumen narrativo con DeepSeek (Sync)"""
    key = env("DEEPSEEK_API_KEY")
    if not key or df.empty: return "Resumen no disponible (Falta Key o Datos)."
    
    total = len(df)
    sent_counts = df["sentiment"].value_counts(normalize=True).to_dict() if "sentiment" in df else {}
    emo_counts = df["emotion"].value_counts().head(3).to_dict() if "emotion" in df else {}
    
    # Top 3 posts por likes
    top_posts = df.sort_values("likes", ascending=False).head(3)
    top_texts = [f"- '{row['text'][:80]}...' ({int(row['likes'])} likes)" for _, row in top_posts.iterrows()]
    
    context = (
        f"Análisis para: '{query}'. Total Posts: {total}.\n"
        f"Sentimiento: {sent_counts.get('POS',0):.1%} Positivo, {sent_counts.get('NEG',0):.1%} Negativo.\n"
        f"Emociones clave: {emo_counts}.\n"
        f"Posts virales:\n" + "\n".join(top_texts)
    )

    prompt = (
        f"Actúa como analista senior de redes sociales. "
        f"Escribe un 'Resumen Ejecutivo' de un párrafo (máx 80 palabras) en español basado en:\n{context}\n"
        f"Indica la tendencia general, si hay crisis y qué emoción predomina. Sé directo."
    )

    try:
        r = requests.post(
            "https://api.deepseek.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 200}, 
            timeout=20
        )
        if r.status_code == 200:
            return r.json()['choices'][0]['message']['content'].strip()
        return "Error en API DeepSeek (Summary)."
    except Exception as e:
        return f"Error generando resumen: {e}"

# ============================================================================
# 5. APIFY CORE & NORMALIZACIÓN
# ============================================================================

def get_apify_items_sync(dataset_id, token):
    try:
        r = requests.get(f"https://api.apify.com/v2/datasets/{dataset_id}/items", params={"token": token, "clean": "1", "format": "json"}, timeout=60)
        return r.json() if r.status_code == 200 else []
    except: return []

def run_apify_actor(actor_id, tokens, payload):
    valid_tokens = [t for t in tokens if t and t.strip()]
    if not valid_tokens: return []

    for i, token in enumerate(valid_tokens):
        url_run = f"https://api.apify.com/v2/acts/{actor_id.replace('/', '~')}/runs"
        try:
            r = requests.post(url_run, params={"token": token}, json=payload, timeout=30)
            if r.status_code not in [200, 201]: continue
            run_id = r.json()["data"]["id"]
            dataset_id = r.json()["data"]["defaultDatasetId"]
            
            start = time.time()
            while time.time() - start < 300:
                time.sleep(3)
                rp = requests.get(f"https://api.apify.com/v2/actor-runs/{run_id}", params={"token": token})
                status = rp.json()["data"]["status"]
                if status == "SUCCEEDED": return get_apify_items_sync(dataset_id, token)
                if status in ["FAILED", "ABORTED", "TIMED-OUT"]: break
        except: continue
    return []

def normalize_common_optimized(rows, platform):
    df = pd.DataFrame(rows)
    if df.empty: return df

    col_map = {
        "text": ["caption", "description", "message", "postText", "text"],
        "likes": ["likeCount", "likesCount", "reactionCount", "diggCount"],
        "comments": ["commentCount", "commentsCount"],
        "shares": ["shareCount", "retweetCount"],
        "views": ["playCount", "viewCount", "videoPlayCount"],
        "followers": ["followers", "followersCount", "fans"],
        "created_at": ["timestamp", "takenAt", "createTimeISO", "createdAt", "date"]
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
        for c in ["ownerUsername", "authorUsername", "username", "author"]:
            if c in df.columns:
                df["username"] = df[c].apply(lambda x: x.get('name') if isinstance(x, dict) else x)
                break
    
    if "text" in df.columns: df["text"] = df["text"].fillna("").astype(str)
    for col in ["likes", "comments", "shares", "views"]:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    
    df["platform"] = platform
    return df

# ============================================================================
# 6. FETCHERS REALES (RESTORED)
# ============================================================================

@st.cache_data(ttl=3600)
def fetch_x_cached(api_key, query, limit):
    headers = {"x-api-key": api_key}
    all_rows, cursor = [], None
    max_loops = (limit // 20) + 5
    for _ in range(max_loops):
        try:
            params = {"query": query, "queryType": "Latest"}
            if cursor: params["cursor"] = cursor
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
                    "followers": u.get("followers") or u.get("followersCount") or 0, "url": t.get("url")
                })
            if len(all_rows) >= limit: break
            cursor = data.get("next_cursor") if data.get("has_next_page") else None
            if not cursor: break
        except: break
    return normalize_common_optimized(all_rows, "x")

@st.cache_data(ttl=3600)
def fetch_facebook_cached(tokens, query, limit, mode):
    payload = {"resultsLimit": limit, "maxPosts": limit}
    actor = "apify/facebook-posts-scraper"
    if mode == "user":
        urls = [{"url": u.strip() if "facebook.com" in u else f"https://www.facebook.com/{u.strip()}"} for u in query.split(",")]
        payload["startUrls"] = urls
    else:
        payload["startUrls"] = [{"url": f"https://www.facebook.com/search/posts?q={query}&filters=eyJzb3J0X2tleSI6InRECENT_POSTS_V2In0%3D"}]
    return normalize_common_optimized(run_apify_actor(actor, tokens, payload), "facebook")

@st.cache_data(ttl=3600)
def fetch_instagram_cached(tokens, query, limit, mode):
    payload = {"resultsLimit": limit, "resultsType": "posts"}
    if mode == "hashtag":
        actor = "apify/instagram-hashtag-scraper"
        payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
    elif mode == "keyword":
        actor = "apify/instagram-scraper"
        payload["search"] = query; payload["searchType"] = "hashtag"
    else:
        actor = "apify/instagram-post-scraper"
        payload["usernames"] = [u.strip() for u in query.split(",")]
    return normalize_common_optimized(run_apify_actor(actor, tokens, payload), "instagram")

@st.cache_data(ttl=3600)
def fetch_tiktok_cached(tokens, query, limit, mode):
    payload = {"resultsPerPage": 100, "limit": limit}
    if mode == "user": payload["usernames"] = [u.strip() for u in query.split(",")]
    else: payload["hashtags"] = [h.strip().replace("#","") for h in query.split(",")]
    return normalize_common_optimized(run_apify_actor("clockworks/tiktok-scraper", tokens, payload), "tiktok")

# ============================================================================
# 7. UTILS Y QUERY BUILDERS
# ============================================================================

def enforce_date_window(df, d1, d2):
    if df is None or df.empty or "created_at_cl" not in df.columns: return df
    mask = pd.Series(True, index=df.index)
    series = df["created_at_cl"].dt.normalize()
    if d1: mask &= ((series >= pd.Timestamp(d1).tz_localize(SCL_TZ, nonexistent="shift_forward")) | (series.isna()))
    if d2: mask &= ((series <= pd.Timestamp(d2).tz_localize(SCL_TZ, nonexistent="shift_forward")) | (series.isna()))
    return df.loc[mask].copy()

def df_to_excel_bytes(df):
    bio = io.BytesIO()
    df_exp = df.copy()
    for c in df_exp.columns:
        if is_datetime64tz_dtype(df_exp[c]): df_exp[c] = df_exp[c].dt.tz_localize(None)
    with pd.ExcelWriter(bio, engine="xlsxwriter") as xw: df_exp.to_excel(xw, index=False)
    bio.seek(0); return bio.read()

def detect_crisis(df):
    if df.empty: return {"score": 0, "signals": [], "severity": "low"}
    signals, score = [], 0
    keys = ["crisis", "estafa", "robo", "caída", "error", "denuncia", "escándalo"]
    
    if "sentiment" in df:
        neg = (df["sentiment"] == "NEG").mean()
        if neg > 0.3: score += 30; signals.append(f"Sentimiento Negativo Alto: {neg:.1%}")
    
    if "text" in df:
        crit = df[df["text"].str.lower().str.contains("|".join(keys), na=False)]
        if len(crit) > 0: score += min(40, len(crit)*5); signals.append(f"{len(crit)} posts con palabras de riesgo")
    
    score = min(100, score)
    sev = "critical" if score>=80 else "high" if score>=60 else "medium" if score>=30 else "low"
    return {"score": score, "signals": signals, "severity": sev}

# ============================================================================
# 8. INTERFAZ PRINCIPAL
# ============================================================================

st.sidebar.header("⚙️ Configuración")
platform = st.sidebar.selectbox("Plataforma", ["X (Twitter)", "Instagram", "Facebook", "TikTok"])

# Modo de búsqueda
if platform == "Instagram": mode = st.sidebar.radio("Modo", ["Hashtag", "Búsqueda (Keyword)", "Usuario"])
elif platform == "Facebook": mode = st.sidebar.radio("Modo", ["Temática (Búsqueda)", "Usuario"])
elif platform == "TikTok": mode = st.sidebar.radio("Modo", ["Hashtag", "Usuario"])
else: mode = st.sidebar.radio("Modo", ["Temática", "Usuario"])

query_input = st.sidebar.text_input("Consulta / Usuario / Hashtags")
lang = st.sidebar.selectbox("Idioma (X)", ["es", "en", "pt"])
limit = st.sidebar.slider("Límite", 50, 2000, 100)
d1 = st.sidebar.date_input("Inicio", datetime.now()-timedelta(days=7))
d2 = st.sidebar.date_input("Fin", datetime.now())
sentiment = st.sidebar.checkbox("Analizar Sentimiento", True)
emotions = st.sidebar.checkbox("Analizar Emociones", False)

# Credenciales Stealth
api_x = env("TWITTERAPI_IO_KEY") or st.sidebar.text_input("X API Key", type="password")
api_apify = env("APIFY_TOKEN") or st.sidebar.text_input("Apify Token", type="password")

if st.sidebar.button("🔍 Buscar", type="primary"):
    st.session_state["report_figures"] = {}
    st.session_state["ai_summary"] = None
    st.session_state["df"] = pd.DataFrame()

    with st.status("Ejecutando proceso...", expanded=True) as status:
        try:
            df = pd.DataFrame()
            
            # 1. FETCHING
            status.write("📡 Conectando a APIs...")
            if platform.startswith("X"):
                if not api_x: st.error("Falta API Key X"); st.stop()
                q = f"from:{query_input}" if mode == "Usuario" else f"{query_input} lang:{lang} -is:retweet"
                df = fetch_x_cached(api_x, q, limit)
            else:
                if not api_apify: st.error("Falta Token Apify"); st.stop()
                tokens = [api_apify]
                if platform == "Facebook":
                    m_api = "user" if "Usuario" in mode else "search"
                    df = fetch_facebook_cached(tokens, query_input, limit, m_api)
                elif platform == "Instagram":
                    m_api = "hashtag" if "Hashtag" in mode else "keyword" if "Búsqueda" in mode else "user"
                    df = fetch_instagram_cached(tokens, query_input, limit, m_api)
                elif platform == "TikTok":
                    m_api = "user" if "Usuario" in mode else "hashtag"
                    df = fetch_tiktok_cached(tokens, query_input, limit, m_api)

            df = enforce_date_window(df, d1, d2)
            
            if df.empty:
                status.update(label="No se encontraron datos", state="error")
                st.stop()

            # 2. IA ANALYTICS
            status.write("🧠 Procesando con DeepSeek...")
            if "text" in df.columns:
                texts = df["text"].tolist()
                if sentiment: df["sentiment"] = analyze_sentiment(texts)
                if emotions: df["emotion"] = analyze_emotions(texts)
                
                # 3. RESUMEN EJECUTIVO
                status.write("📝 Redactando resumen analista...")
                summary = generate_executive_summary(df, query_input)
                st.session_state["ai_summary"] = summary

            st.session_state["df"] = df
            status.update(label="¡Proceso completado!", state="complete")
            
        except Exception as e:
            st.error(f"Error crítico: {e}")
            status.update(label="Error", state="error")

# ============================================================================
# 9. RESULTADOS Y DASHBOARD
# ============================================================================

df = st.session_state.get("df")
summary = st.session_state.get("ai_summary")

if df is not None and not df.empty:
    
    # BLOQUE RESUMEN IA
    if summary:
        st.info(f"🤖 **Resumen Ejecutivo (IA):**\n\n{summary}")

    # CRISIS CHECK
    crisis = detect_crisis(df)
    if crisis["score"] > 0:
        c_col = {"critical":"🔴","high":"🟠","medium":"🟡","low":"🟢"}[crisis["severity"]]
        st.warning(f"{c_col} **Alerta de Crisis (Score: {crisis['score']})**: {', '.join(crisis['signals'])}")

    # KPIS
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Posts", len(df))
    k2.metric("Likes", int(df["likes"].sum()))
    k3.metric("Comentarios", int(df["comments"].sum()))
    k4.metric("Sentimiento Positivo", f"{(df['sentiment']=='POS').mean():.1%}" if "sentiment" in df else "-")

    # GRÁFICOS
    st.subheader("Visualizaciones")
    tabs = st.tabs(["Tendencia", "Sentimiento", "Nube"])
    figs_to_save = {}

    with tabs[0]: # Temporal
        if "created_at_cl" in df:
            fig, ax = plt.subplots(figsize=(10,3))
            df["created_at_cl"].dt.date.value_counts().sort_index().plot(kind='bar', ax=ax, color='#1f77b4')
            ax.set_title("Volumen por Día")
            st.pyplot(fig)
            figs_to_save["tendencia_temporal"] = fig_to_bytes(fig)
            plt.close(fig)

    with tabs[1]: # Sentimiento
        if "sentiment" in df:
            c1, c2 = st.columns(2)
            with c1:
                fig, ax = plt.subplots()
                df["sentiment"].value_counts().plot.pie(autopct='%1.1f%%', ax=ax, colors=['#2ca02c','#d62728','#7f7f7f'])
                st.pyplot(fig)
                figs_to_save["sentiment_pie"] = fig_to_bytes(fig)
                plt.close(fig)
            with c2:
                fig2, ax2 = plt.subplots()
                df["sentiment"].value_counts().plot.bar(ax=ax2, color=['#2ca02c','#d62728','#7f7f7f'])
                st.pyplot(fig2)
                figs_to_save["sentiment_bar"] = fig_to_bytes(fig2)
                plt.close(fig2)

    with tabs[2]: # Nube
        if "text" in df:
            txt = " ".join(df["text"].astype(str))
            wc = WordCloud(width=800, height=400, background_color="white", stopwords=STOPWORDS).generate(txt)
            fig, ax = plt.subplots()
            ax.imshow(wc); ax.axis("off")
            st.pyplot(fig)
            figs_to_save["wordcloud"] = fig_to_bytes(fig)
            plt.close(fig)

    st.session_state["report_figures"] = figs_to_save

    st.divider()

    # ============================================================================
    # 10. ENVÍO DE EMAIL
    # ============================================================================
    st.subheader("📧 Enviar Reporte Ejecutivo")
    with st.expander("✉️ Configuración de Envío", expanded=True):
        email_to = st.text_input("Destinatario", placeholder="jp@cliente.com")
        
        if st.button("Enviar Reporte", type="primary", use_container_width=True):
            if not email_to: st.error("Ingresa un correo.")
            else:
                with st.spinner("Empaquetando y enviando..."):
                    # Cuerpo del correo enriquecido
                    body = (
                        f"REPORTE EJECUTIVO - SOCIAL LISTENING\n"
                        f"====================================\n"
                        f"Búsqueda: {query_input} | Plataforma: {platform}\n"
                        f"Rango: {d1} a {d2}\n\n"
                        f"RESUMEN DEL ANALISTA (IA):\n"
                        f"{summary if summary else 'No disponible'}\n\n"
                        f"METRICAS:\n"
                        f"- Total Posts: {len(df)}\n"
                        f"- Interacciones: {int(df['likes'].sum() + df['comments'].sum())}\n"
                        f"- Riesgo Crisis: {crisis['severity'].upper()}\n\n"
                        f"Adjunto encontrarás el Excel con la data cruda y los gráficos del dashboard.\n\n"
                        f"Generado automáticamente por SocialListening Pro."
                    )
                    
                    ok, msg = send_email_report(
                        email_to,
                        f"Reporte: {query_input} [{datetime.now().strftime('%d/%m')}]",
                        body,
                        df_to_excel_bytes(df),
                        df.to_csv(index=False).encode('utf-8-sig'),
                        st.session_state["report_figures"]
                    )
                    
                    if ok: st.success(f"✅ {msg}")
                    else: st.error(f"❌ {msg}")