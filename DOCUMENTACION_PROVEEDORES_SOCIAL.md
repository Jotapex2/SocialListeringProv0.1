# Documentacion de Proveedores Sociales

## Objetivo

La app ahora permite elegir proveedor para `Instagram` y `Facebook`, manteniendo:

- `X (Twitter)` por `twitterapi.io`
- `TikTok` por `Apify`

## Variables de entorno

Configurar en `.env` o en `st.secrets`:

- `TWITTERAPI_IO_KEY`
- `APIFY_TOKEN`
- `SCRAPECREATORS_API_KEY`
- `BRIGHTDATA_API_TOKEN`
- `DEEPSEEK_API_KEY`
- `ADMIN_USER`
- `ADMIN_PASS`

## Selector de proveedor

En sidebar, cuando la plataforma es `Instagram` o `Facebook`, aparece:

- `Auto`
- `Apify`
- `ScrapeCreators`
- `Bright Data`

### Comportamiento de `Auto`

`Auto` intenta usar proveedor alternativo si existe credencial configurada y, si no obtiene datos, hace fallback a `Apify` cuando aplica.

## Cobertura por plataforma

### X (Twitter)

- Proveedor fijo: `twitterapi.io`
- No usa `ScrapeCreators` ni `Bright Data`

### TikTok

- Proveedor fijo: `Apify`
- No usa `ScrapeCreators` ni `Bright Data`

### Instagram

#### Modos soportados en la UI

- `Por tematica (hashtags)`
- `Por tematica (busqueda IG)`
- `Por usuario`

#### Proveedores disponibles

- `Apify`
  - Soporta `hashtag`, `keyword` y `user`
  - Sigue siendo el fallback principal

- `ScrapeCreators`
  - `Por usuario`: usa perfil para extraer posts recientes
  - `Por tematica (hashtags)` y `Por tematica (busqueda IG)`: intenta búsqueda de reels/posts

- `Bright Data`
  - `Por usuario`: usa coleccion de posts desde URL de perfil
  - `Por tematica (hashtags)`: usa URL de hashtag
  - `Por tematica (busqueda IG)`: no tiene mapeo estable en esta app; si no devuelve datos, la app cae a otro proveedor si está disponible

#### Orden practico de resolucion

- `provider=Apify`: usa solo Apify
- `provider=ScrapeCreators`: usa solo ScrapeCreators
- `provider=Bright Data`: usa Bright Data y, si no devuelve datos en flujos soportados por la app, puede caer a Apify
- `provider=Auto`:
  - `user`: intenta proveedor alternativo configurado y luego Apify
  - `hashtag`: intenta alternativo configurado y luego Apify
  - `keyword`: intenta alternativo configurado y luego Apify

### Facebook

#### Modos soportados en la UI

- `Por tematica`
- `Por usuario`

#### Proveedores disponibles

- `Apify`
  - `Por tematica`: proveedor efectivo principal
  - `Por usuario`: soportado

- `ScrapeCreators`
  - `Por usuario`: soportado
  - `Por tematica`: no se usa en esta app

- `Bright Data`
  - `Por usuario`: soportado
  - `Por tematica`: no se usa en esta app

#### Regla importante

`Facebook -> Por tematica` sigue resolviéndose con `Apify`, aunque en la UI se seleccione otro proveedor. La app muestra aviso y usa Apify porque el flujo tematico ya estaba estable y los proveedores alternativos no quedaron mapeados con la misma cobertura.

## Credenciales requeridas por proveedor

### Instagram

- `Apify` requiere `APIFY_TOKEN`
- `ScrapeCreators` requiere `SCRAPECREATORS_API_KEY`
- `Bright Data` requiere `BRIGHTDATA_API_TOKEN`
- `Auto` requiere al menos una de esas credenciales

### Facebook

- `Por tematica` requiere `APIFY_TOKEN`
- `Por usuario`:
  - `Apify` requiere `APIFY_TOKEN`
  - `ScrapeCreators` requiere `SCRAPECREATORS_API_KEY`
  - `Bright Data` requiere `BRIGHTDATA_API_TOKEN`
  - `Auto` requiere al menos una de esas credenciales

## Normalizacion de datos

Todos los proveedores terminan normalizando a un esquema comun antes de analitica/export:

- `id`
- `text`
- `username`
- `likes`
- `comments`
- `shares`
- `views`
- `url`
- `created_at`
- `platform`

Luego la app aplica:

- conversion de fechas
- deduplicacion
- filtro temporal
- analitica IA
- export CSV/Excel

## Resiliencia implementada

- retry con backoff para `Apify`
- retry con backoff para `ScrapeCreators`
- retry con backoff para `Bright Data`
- fallback por proveedor en `Instagram` y `Facebook` segun el modo
- validacion de credenciales antes de ejecutar
- logs para detectar cuando un proveedor falla o cuando se activa fallback

## Limitaciones actuales

- `Bright Data` para `Instagram keyword search` no tiene un mapeo estable en esta implementacion
- `Facebook por tematica` no se desvio a `ScrapeCreators` ni `Bright Data`
- las respuestas de `ScrapeCreators` y `Bright Data` se normalizan de forma defensiva porque sus payloads pueden variar

## Archivos tocados

- `streamlit_twitterapi_io_app.py`
- `.env.example`
- `README.md`
- `DOCUMENTACION_PROVEEDORES_SOCIAL.md`

## Siguiente validacion recomendada

Probar manualmente estos casos con credenciales reales:

1. `Instagram -> Por usuario` con `Apify`
2. `Instagram -> Por usuario` con `ScrapeCreators`
3. `Instagram -> Por usuario` con `Bright Data`
4. `Instagram -> Por tematica (hashtags)` con `Bright Data`
5. `Facebook -> Por usuario` con `ScrapeCreators`
6. `Facebook -> Por usuario` con `Bright Data`
7. `Facebook -> Por tematica` con `Apify`
