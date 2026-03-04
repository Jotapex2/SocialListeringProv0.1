# SocialListeningPro — X + Instagram + Facebook + TikTok
- X (Twitter) via twitterapi.io (free-tier pacing)
- IG/FB/TikTok via Apify Store actors (usa APIFY_TOKEN)
- Visualizaciones, sentimiento en español, export CSV/Excel con fix de timezone
- Modo dev con live-reload (docker-compose.dev.yml)

## Pasos local
```powershell
Copy-Item .env.example .env
notepad .env   # completa TWITTERAPI_IO_KEY, APIFY_TOKEN, ADMIN_USER, ADMIN_PASS
docker compose up --build -d
# modo dev:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
Abre: http://localhost:8501

## Streamlit Cloud (produccion)
Configura estos secrets en la app:
- `TWITTERAPI_IO_KEY`
- `APIFY_TOKEN`
- `DEEPSEEK_API_KEY`
- `ADMIN_USER`
- `ADMIN_PASS`
- `REQUIRE_LOGIN=true`
- `ENABLE_DEBUG_TOOLS=false`
- `AI_FAST_MODE=true`
- `AI_MAX_TEXTS=300`

Nota:
- Si `ENABLE_DEBUG_TOOLS=true`, aparece un switch de Debug/Admin para alternar en UI entre:
  - `⚡ IA modo rápido` (muestra priorizada por engagement)
  - modo precisión (analiza todos los posts)
