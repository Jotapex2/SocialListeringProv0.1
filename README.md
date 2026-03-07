# SocialListeningPro - X + Instagram + Facebook + TikTok
- X (Twitter) via twitterapi.io (free-tier pacing)
- IG/FB/TikTok via Apify Store actors (usa APIFY_TOKEN)
- Visualizaciones, sentimiento en espanol, export CSV/Excel con fix de timezone
- Modo dev con live-reload (docker-compose.dev.yml)
- Apify con retry/backoff y metricas de runs (Debug Tools)
- Facebook por tematica: limite efectivo 100 por ejecucion (con aviso en UI)
- Filtro temporal configurable: opcion `Incluir posts sin fecha`

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
  - `IA modo rapido` (muestra priorizada por engagement)
  - modo precision (analiza todos los posts)
- En Facebook `Por tematica`, si el slider supera 100, la app ajusta automaticamente a 100 (restriccion del actor).
