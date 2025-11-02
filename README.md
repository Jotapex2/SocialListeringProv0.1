# SocialListeningPro — X + Instagram + Facebook + TikTok
- X (Twitter) via twitterapi.io (free-tier pacing)
- IG/FB/TikTok via Apify Store actors (usa APIFY_TOKEN)
- Visualizaciones, sentimiento en español, export CSV/Excel con fix de timezone
- Modo dev con live-reload (docker-compose.dev.yml)

## Pasos
```powershell
Copy-Item .env.example .env
notepad .env   # completa TWITTERAPI_IO_KEY y APIFY_TOKEN
docker compose up --build -d
# modo dev:
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```
Abre: http://localhost:8501
