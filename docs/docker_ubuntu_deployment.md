# Docker Compose en Ubuntu

## Servicios

La app no tiene un microservicio ML separado: fake news, stance y BART viven en
el proceso FastAPI. Por eso hay una sola imagen backend:

- `api`: FastAPI + modelos locales, con `uvicorn --workers 1`.
- `postgres`: PostgreSQL 16.
- `nginx`: reverse proxy HTTP.
- `summary-backfill`: job opcional que usa la misma imagen de `api` para generar
  resumenes fuera del request.
- `news-images-backfill`: job de una sola ejecución que completa las URLs de
  imagen de noticias ya publicadas que aún no la tienen.

PostgreSQL queda solo en la red interna de Docker. En producción no se publica
`5432` hacia internet.

Los checkpoints no se copian dentro de la imagen. Se montan desde el host:

```text
./output:/app/output:ro
./data:/app/data:ro
```

Antes de levantar producción, confirmar que existan:

```bash
ls output/fakenews_xlmroberta_full_v1/best_model
ls output/stance_mbert_weighted_paper/best_model
```

## Variables de entorno

Crear `.env` desde la plantilla y completar los valores obligatorios:

```bash
cp .env.example .env
nano .env
```

Minimo para producción:

```env
POSTGRES_DB=kenta
POSTGRES_USER=kenta_app
POSTGRES_PASSWORD=generar-una-clave-larga
HTTP_PORT=80
CORS_ORIGINS=https://tu-dominio.com
SUMMARY_INLINE_ENABLED=false
SUMMARY_MAX_CONCURRENT_GENERATIONS=1
SUMMARY_NUM_BEAMS=4
JUSTIFICATION_AUTO_ENABLED=false
```

Puedes generar una clave para PostgreSQL con:

```bash
openssl rand -base64 32
```

`POSTGRES_PASSWORD` y `CORS_ORIGINS` son obligatorios en `docker-compose.yml`.
Si quedan vacios, `docker compose config` o `docker compose up` deben fallar en
vez de levantar una configuración insegura.

## Levantar

```bash
docker compose config
docker compose up -d --build postgres api nginx
docker compose ps
curl http://localhost/health
curl http://localhost/ml/health
```

## Medir memoria del compose

Medicion puntual:

```bash
docker stats --no-stream
free -h
```

Medicion continua mientras se prueba la app:

```bash
watch -n 2 'docker stats --no-stream; echo; free -h'
```

Para forzar carga de fake news y stance dentro del proceso `api`, usar cualquier
endpoint que invoque `/ml/predict` o el pipeline. Para forzar BART dentro de
FastAPI, llamar `/ml/analyze` con `include_summary=true` y un texto largo.

Ejemplo:

```bash
curl -X POST http://localhost/ml/analyze \
  -H 'Content-Type: application/json' \
  -d '{"title":"Prueba de resumen","content":"Texto largo de noticia politica. Texto largo de noticia politica. Texto largo de noticia politica. Texto largo de noticia politica. Texto largo de noticia politica. Texto largo de noticia politica. Texto largo de noticia politica. Texto largo de noticia politica. Texto largo de noticia politica. Texto largo de noticia politica.","include_summary":true,"force_summary":true}'
```

## Backfill de resumenes

Ejecutar una tanda controlada:

```bash
docker compose --profile jobs run --rm summary-backfill
```

Cambiar limite:

```bash
SUMMARY_BACKFILL_LIMIT=50 docker compose --profile jobs run --rm summary-backfill
```

## Búsqueda reciente en X/Twitter

Para leer publicaciones públicas se requiere `TWITTER_BEARER_TOKEN`; el
Consumer Key y el Access Token de usuario no reemplazan ese token. Configurar
en `.env` un Bearer Token de lectura y una consulta específica de hasta 512
caracteres:

```env
TWITTER_BEARER_TOKEN=pega_el_bearer_token_solo_en_el_servidor
TWITTER_MAX_RESULTS=10
TWITTER_SEARCH_QUERY="(Perú OR peruano) (Congreso OR Gobierno OR elecciones OR política OR presidenta OR presidente) lang:es -is:retweet -is:reply"
```

Después de desplegar, registra o actualiza la fuente una sola vez. El comando
no consulta X ni procesa noticias; solo guarda la consulta en PostgreSQL:

```bash
docker compose exec -T api python scripts/configure_twitter_search_source.py
```

El scheduler procesa la fuente como `twitter` en su siguiente ejecución. La
consulta devuelve solo una página de hasta `TWITTER_MAX_RESULTS` publicaciones
para limitar el costo y el volumen. No pongas tokens en Git, en código ni en
mensajes de chat.

## Backfill de imágenes de noticias

Se usa solo cuando se añade `image_url` a una base de datos que ya contiene
noticias. El job consulta exclusivamente filas de `serving.news` sin imagen; no
sobrescribe URLs existentes ni crea o elimina noticias. Primero ejecuta una
vista previa de 10 filas:

```bash
docker compose exec -T api python scripts/backfill_news_images.py --limit 10
```

Si las URLs mostradas son correctas, ejecútelo una sola vez. Se ejecuta en un
contenedor temporal y no reinicia `api`, `frontend` ni `nginx`:

```bash
docker compose --profile jobs run --rm news-images-backfill
```

Al terminar, comprueba cuántas noticias quedaron con imagen:

```bash
docker compose exec -T postgres sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT COUNT(*) AS total, COUNT(image_url) AS con_imagen FROM serving.news;"'
```

## Reglas para 4 GB RAM

Mantener:

```env
SUMMARY_INLINE_ENABLED=false
SUMMARY_MAX_CONCURRENT_GENERATIONS=1
SUMMARY_NUM_BEAMS=4
ML_WARMUP_ON_STARTUP=true
```

No subir `api` a mas de un worker mientras los modelos vivan dentro del mismo
proceso. Cada worker cargaria otra copia de fake news, stance y BART.
