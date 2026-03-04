# Documentacion Tecnica - SocialListeningPro (Streamlit Cloud)

## 1) Resumen del proyecto
Aplicacion Streamlit para social listening multi-plataforma:
- X (Twitter): `twitterapi.io` (endpoint advanced search).
- Instagram / Facebook / TikTok: actores de Apify.
- Analitica: sentimiento, emociones, topicos, nube de palabras, alerta de crisis.
- Reporteria: descarga Excel/CSV y envio por correo con adjuntos.
- IA generativa: resumen ejecutivo con DeepSeek.

Archivo principal (monolito):
- `streamlit_twitterapi_io_app.py` (~1560 lineas)

Archivos de soporte:
- `requirements.txt`
- `README.md`
- `Dockerfile`
- `docker-compose.yml` / `docker-compose.dev.yml`
- `.streamlit/secrets.toml.example`

---

## 2) Arquitectura funcional

### 2.1 Capas
1. UI / Orquestacion (Streamlit)
- Sidebar: plataforma, modo de busqueda, filtros, fechas, limite, credenciales, toggles IA.
- Main: dashboard, alerta de crisis, visualizaciones, export, envio de reporte.

2. Ingestion de datos
- X: `fetch_x_cached(...)`.
- Facebook: `fetch_facebook_cached(...)`.
- Instagram: `fetch_instagram_cached(...)`.
- TikTok: `fetch_tiktok_cached(...)`.
- Para Meta/TikTok se usa `run_apify_actor_v2(...)` + `apify_dataset_items_paginated(...)`.

3. Normalizacion / enriquecimiento
- `normalize_common_optimized(...)` homogeniza columnas (`text`, `likes`, `comments`, `created_at`, etc.).
- `enforce_date_window(...)` filtra por rango temporal.

4. IA y analitica
- Sentimiento batch async DeepSeek: `process_sentiment_batch_async(...)`.
- Emociones batch async DeepSeek: `process_emotions_batch_async(...)`.
- Resumen ejecutivo: `generate_executive_summary(...)`.
- Crisis: `detect_crisis_signals(...)`.

5. Export y distribucion
- Excel robusto: `df_to_excel_bytes(...)` + sanitizacion.
- CSV: `df_to_csv_bytes(...)`.
- Email con adjuntos: `send_email_report(...)`.

### 2.2 Flujo end-to-end
1. Usuario configura busqueda en sidebar.
2. Boton `Buscar` ejecuta fetch segun plataforma/modo.
3. Se normalizan resultados y aplica ventana de fechas.
4. Opcional: clasifica sentimiento/emociones en paralelo.
5. Se genera resumen ejecutivo IA.
6. Se renderizan KPIs y graficos.
7. Se habilita export (Excel/CSV) y envio por correo.

---

## 3) Modulos y funciones clave

### 3.1 Configuracion, estado y logging
- `env(name)` intenta primero `st.secrets` y luego variables de entorno.
- `st.session_state` guarda `df`, logs, respuestas API, tiempos, figuras, resumen IA.
- `measure_time(...)` decorador de telemetria de funciones.
- `render_debug_panel()` expone logs, tiempos, data y respuestas API.

### 3.2 Seguridad de acceso
- `login()` protege la app con usuario/password.
- Usa `ADMIN_USER`/`ADMIN_PASS` y tiene fallback a `admin/admin123` si no estan definidos.

### 3.3 DeepSeek
- Llamadas sync (`requests`) para resumen ejecutivo.
- Llamadas async (`httpx`) para clasificacion de sentimiento/emociones por texto.
- Parsing defensivo del resultado (`POS/NEG/NEU`, emociones validas).

### 3.4 Apify
- `run_apify_actor_v2(...)` ejecuta actor, hace polling robusto, maneja estados de run.
- `apify_dataset_items_paginated(...)` pagina items por dataset hasta limite.
- Rotacion de tokens soportada por lista de tokens.

### 3.5 NLP local ligero
- Limpieza de texto (`clean_texts`) con stopwords + `unidecode`.
- Topicos por frecuencia (`extract_topics`).
- Nube de palabras (`wordcloud_from_blob`).

### 3.6 Visualizaciones
- Pie/bar para sentimiento y emociones.
- Evolucion temporal diaria.
- Topicos y nube de palabras.

### 3.7 Export/email
- Sanitiza control chars y objetos complejos para compatibilidad Excel.
- Adjunta Excel/CSV e imagenes en correo SMTP.

---

## 4) Integraciones externas

1. `twitterapi.io`
- Endpoint: `https://api.twitterapi.io/twitter/tweet/advanced_search`
- Auth: header `x-api-key`.

2. `Apify API v2`
- Actores usados:
  - IG hashtag/keyword: `apidojo/instagram-hashtag-scraper`
  - IG user posts: `apify/instagram-post-scraper`
  - FB search: `scraper_one/facebook-posts-search`
  - FB pages/user: `apify/facebook-posts-scraper`
  - TikTok: `clockworks/tiktok-scraper`
- Auth: bearer token.

3. `DeepSeek API`
- Resumen ejecutivo y clasificacion (sentimiento/emociones).

4. SMTP
- Para envio de reportes por correo.

---

## 5) Ejecucion y despliegue

### 5.1 Local con Docker
```powershell
docker compose up --build -d
```

### 5.2 Streamlit Cloud (produccion)
- Runtime principal: `streamlit_twitterapi_io_app.py`
- Variables sensibles recomendadas en `st.secrets`:
  - `TWITTERAPI_IO_KEY`
  - `APIFY_TOKEN`
  - `DEEPSEEK_API_KEY`
  - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`
  - `ADMIN_USER`, `ADMIN_PASS`

Nota: en Streamlit Cloud no necesitas `.env` para produccion.

---

## 6) Hallazgos y riesgos (priorizados)

### Criticos
1. Fallback de login inseguro
- Si faltan `ADMIN_USER`/`ADMIN_PASS`, entra con `admin/admin123`.
- Riesgo alto en entorno publico.

2. Archivo monolitico unico
- Toda la logica esta en un solo archivo grande.
- Riesgo de regresiones, baja mantenibilidad y dificil testing.

### Altos
3. Dependencia fuerte de APIs externas sin estrategia consistente de retry/backoff
- X y DeepSeek no tienen politica robusta de reintentos/circuit breaker.
- Puede degradar UX por fallos transitorios/rate limits.

4. Coste/latencia potencialmente alto en IA por volumen
- Sentimiento/emociones se llama por cada texto (aunque async), con limites altos de posts.
- Puede subir tiempo de respuesta y costos.

5. Debug panel puede exponer datos operativos sensibles
- Muestra respuestas API, logs internos y metadatos de ejecucion.
- En prod deberia estar estrictamente controlado.

### Medios
6. Encoding inconsistente (mojibake) en UI y textos
- Afecta calidad visual y mantenimiento.

7. `requirements.txt` con redundancias/ruido
- `xlsxwriter` duplicado.
- `secure-smtplib` no es necesario en Python moderno.

8. Cobertura de pruebas inexistente
- No hay suite automatizada para fetchers, normalizacion, filtros, IA, export.

---

## 7) Mejoras recomendadas para produccion (Streamlit Cloud)

### Fase 1 (inmediata)
1. Eliminar fallback inseguro de credenciales
- Requerir `ADMIN_USER` y `ADMIN_PASS` obligatoriamente.
- Si faltan, bloquear arranque con mensaje de configuracion.

2. Desactivar debug sensible en prod
- Habilitar `debug_mode` solo bajo flag explicito (`ENABLE_DEBUG_TOOLS=false` por defecto).
- Ocultar payloads de respuestas API en produccion.

3. Limpiar dependencias
- Quitar duplicados y paquetes innecesarios.
- Fijar versiones clave para reproducibilidad.

4. Normalizar codificacion UTF-8
- Corregir textos corruptos y asegurar encoding consistente.

### Fase 2 (1-2 sprints)
5. Refactor modular
- Separar en modulos: `auth.py`, `fetchers.py`, `apify.py`, `deepseek.py`, `analytics.py`, `exports.py`, `ui.py`.
- Mantener `streamlit_app.py` como orquestador del layout.

6. Politica de resiliencia HTTP
- Reintentos exponenciales con jitter para X/DeepSeek.
- Timeouts por etapa y manejo claro de errores de proveedor.

7. Optimizacion de IA
- Modo "fast": muestreo de textos para sentimiento/emociones.
- Batch por bloques/ventanas para reducir llamadas.
- Cache de clasificacion por hash de texto.

### Fase 3 (calidad operativa)
8. Testing y calidad
- Unit tests de normalizacion, filtros, query builders, export.
- Test de integracion con mocks para X/Apify/DeepSeek.

9. Observabilidad
- Logging estructurado (JSON) y niveles por entorno.
- Metricas de latencia por proveedor y porcentaje de fallas.

10. Gobierno de secretos
- En Streamlit Cloud usar solo `st.secrets`.
- Evitar depender de `.env` en runtime prod.

---

## 8) Recomendacion especifica para tu caso (solo tu acceso)
Si efectivamente solo tu accedes, el riesgo de exposicion baja, pero en un servicio cloud publico siempre conviene hardening minimo:
- Mantener login obligatorio sin defaults.
- Guardar todas las keys en Streamlit Secrets.
- Debug apagado por defecto.
- Limitar `limit` maximo efectivo en prod para controlar costo/latencia (por ejemplo 300-500).

---

## 9) Estado actual del analisis
Se realizo analisis estatico completo del repositorio y de la app principal.
Ademas, se aplicaron cambios de hardening compatibles con Streamlit Cloud (ver seccion 10).

## 10) Mejoras aplicadas (2026-03-04)
Se aplicaron mejoras orientadas a despliegue en Streamlit Cloud:
- Login sin credenciales por defecto:
  - ahora exige `ADMIN_USER` y `ADMIN_PASS` en `st.secrets`/env.
  - si faltan, la app se detiene con mensaje de configuracion.
- Debug tools controlado por flag:
  - `ENABLE_DEBUG_TOOLS=false` por defecto.
  - si esta apagado, no se puede activar modo debug desde UI.
- Credenciales API endurecidas:
  - se elimino ingreso manual de API keys en sidebar.
  - `TWITTERAPI_IO_KEY` y `APIFY_TOKEN` se leen solo desde `secrets`/config.
- Dependencias limpiadas:
  - se removio duplicado de `xlsxwriter`.
  - se removio `secure-smtplib` (innecesario).
- Plantillas de configuracion actualizadas:
  - `.env.example` y `.streamlit/secrets.toml.example` ahora incluyen `ADMIN_*` y flags de seguridad.
- Modo `prod-lite` de IA:
  - `AI_FAST_MODE=true` y `AI_MAX_TEXTS=300` por defecto.
  - cuando hay muchos posts, analiza una muestra priorizada por engagement para sentimiento/emociones.
  - reduce latencia/costo en Streamlit Cloud manteniendo calidad util para monitoreo.
  - si `ENABLE_DEBUG_TOOLS=true`, aparece control Debug/Admin en sidebar para alternar:
    - modo rapido (muestra)
    - modo precision (todos los posts)
