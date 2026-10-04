# Despliegue previo a la validación con usuarios

Este procedimiento actualiza Kenta conservando una copia recuperable de la base de datos y de las imágenes actualmente desplegadas. Debe ejecutarse desde `/root/kenta` en el droplet después de fusionar las ramas aprobadas de backend y frontend.

## 1. Registrar el estado y respaldar

```bash
git status --short --branch
git -C /root/frontend status --short --branch
docker compose ps
mkdir -p backups
umask 077
docker compose exec -T postgres sh -c 'pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB"' > backups/kenta-prevalidation-$(date +%Y%m%d-%H%M%S).dump
latest_backup=$(ls -1t backups/kenta-prevalidation-*.dump | head -n 1)
test -s "$latest_backup"
docker compose exec -T postgres pg_restore -l < "$latest_backup" > /dev/null
docker commit kenta-api kenta-api:prevalidation-rollback
docker commit kenta-frontend kenta-frontend:prevalidation-rollback
```

No se deben borrar los archivos no versionados del servidor (`backups/`, certificados ni copias de configuración).

## 2. Actualizar código y configuración

```bash
git pull --ff-only origin master
git -C /root/frontend pull --ff-only origin master
```

Conservar los secretos existentes y validar en `.env`:

```dotenv
API_DOCS_ENABLED=false
ENABLE_SCHEDULER=true
SCRAPING_SCHEDULE_HOURS=8,20
SCRAPING_SCHEDULE_MINUTE=30
SCRAPER_MAX_ARTICLES_PER_SOURCE=5
STANCE_PUBLIC_ENABLED=false
JUSTIFICATION_AUTO_ENABLED=true
JUSTIFICATION_MAX_PER_SCHEDULED_RUN=5
RELATED_CLUSTER_MIN_SCORE=0.60
```

El último par limita Gemini a cinco intentos automáticos por ciclo completo de scraping, es decir, un máximo de diez intentos diarios con el horario anterior. Si la cuota no está disponible, usar `JUSTIFICATION_AUTO_ENABLED=false`; el resto de la aplicación seguirá funcionando.

## 3. Construir sin interrumpir el servicio

```bash
docker compose build api migrate frontend
docker compose run --rm --no-deps api python -c 'import app.main; print("API_IMPORT_OK")'
docker compose run --rm migrate
```

La imagen de producción no incluye `pytest`. La batería automatizada debe ejecutarse antes del merge; en el servidor se hace una prueba de importación y luego pruebas de humo.

## 4. Reemplazar servicios y validar Nginx

```bash
docker compose up -d --no-deps api
docker compose ps api
docker compose exec -T api python -c 'import requests; r=requests.get("http://localhost:8000/health", timeout=30); print(r.status_code, r.json()); r.raise_for_status()'
docker compose up -d --no-deps frontend
docker compose ps frontend
docker compose exec -T nginx nginx -t
docker compose up -d --no-deps nginx
docker compose ps
```

## 5. Verificaciones funcionales y de datos

```bash
curl -fsS https://api.ikenta.app/health
curl -fsS -o /dev/null -w 'HOME_HTTP %{http_code}\n' https://ikenta.app/home
curl -fsS -o /dev/null -w 'SAVED_HTTP %{http_code}\n' https://ikenta.app/saved
docker compose exec -T api python -c 'import os; keys=["ENABLE_SCHEDULER","SCRAPING_SCHEDULE_HOURS","SCRAPING_SCHEDULE_MINUTE","SCRAPER_MAX_ARTICLES_PER_SOURCE","STANCE_PUBLIC_ENABLED","JUSTIFICATION_AUTO_ENABLED","JUSTIFICATION_MAX_PER_SCHEDULED_RUN","API_DOCS_ENABLED"]; print({k:os.getenv(k,"<unset>") for k in keys})'
docker compose exec -T api python -c 'from app.db.database import SessionLocal; from app.raw.models import Source; s=SessionLocal(); print([(x.name,x.is_active) for x in s.query(Source).order_by(Source.source_id)]); s.close()'
docker compose exec -T api python -c 'from sqlalchemy import text; from app.db.database import SessionLocal; s=SessionLocal(); print(s.execute(text("SELECT to_regclass(:table_name)"), {"table_name":"serving.news_related_source_clicks"}).scalar()); s.close()'
docker compose exec -T api python scripts/related_sources_stats.py
docker compose logs --tail=150 api frontend nginx
```

En pruebas manuales, comprobar al menos: inicio de sesión con “recordarme”, redirección desde `/` hacia el feed cuando ya existe sesión, navegación móvil, cambio de contraseña, perfil, favoritos con contenido, scroll infinito, aviso/revelado de lenguaje fuerte en X, clics en fuentes relacionadas y acceso del administrador a analítica.

## 6. Backfill controlado de fuentes relacionadas

El trabajo automático solo cubre predicciones nuevas. Para reducir el pendiente histórico sin agotar cuota:

```bash
RELATED_SOURCES_LIMIT=5 RELATED_SOURCES_SLEEP=3 docker compose run --rm related-sources
docker compose exec -T api python scripts/related_sources_stats.py
```

Repetir únicamente después de revisar consumo, errores y calidad de las fuentes obtenidas. No ejecutar lotes grandes antes de la validación.

## 7. Rollback

Si una verificación crítica falla, conservar los logs y volver temporalmente a las imágenes guardadas:

```bash
docker compose logs --tail=300 api frontend nginx > backups/prevalidation-failure.log
docker image tag kenta-api:prevalidation-rollback kenta-api:latest
docker image tag kenta-frontend:prevalidation-rollback kenta-frontend:latest
docker compose up -d --no-build --no-deps api
docker compose up -d --no-build --no-deps frontend
```

La restauración de PostgreSQL es una medida separada y solo debe realizarse si una migración de datos produjo daño confirmado; las migraciones de este despliegue son aditivas.
