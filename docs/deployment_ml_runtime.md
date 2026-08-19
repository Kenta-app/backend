# Runtime ML para despliegue

## Decision

El resumen no debe estar en el camino critico de publicacion o lectura de
noticias. Fake news y stance se ejecutan durante el pipeline; el resumen se
genera una vez por noticia procesada y se persiste en `processed.summaries`.

Configuracion recomendada:

```env
SUMMARY_INLINE_ENABLED=false
SUMMARY_MAX_CONCURRENT_GENERATIONS=1
SUMMARY_NUM_BEAMS=4
ML_WARMUP_ON_STARTUP=false
```

Con esta configuracion, el pipeline publica la noticia aunque el resumen aun no
exista. `PublishedNews.summary` usa el fallback existente y luego se refresca
cuando el backfill genera el resumen definitivo.

## Generar resumenes

Backfill de resumenes faltantes:

```bash
python scripts/backfill_summaries.py --limit 20
```

Regenerar resumenes existentes:

```bash
python scripts/backfill_summaries.py --limit 20 --force
```

Ver candidatos sin ejecutar BART:

```bash
python scripts/backfill_summaries.py --limit 20 --dry-run
```

## Prueba de memoria

Medir carga base de clasificadores y BART:

```bash
python scripts/profile_model_memory.py --summary-runs 1 --concurrent-summaries 1 --json
```

Probar presion de concurrencia:

```bash
python scripts/profile_model_memory.py --summary-runs 1 --concurrent-summaries 2 --json
```

Campos clave:

- `classifiers_loaded.rss_mb`: memoria con fake news y stance cargados.
- `summarizer_loaded.rss_mb`: memoria con BART cargado.
- `summary_run_*.rss_mb`: pico aproximado despues de generar resumen.
- `run_elapsed_sec`: latencia real de generacion en esa maquina.

Si el pico queda cerca del limite de RAM disponible, no aumentar workers ni
concurrencia. En servidores pequenos, ejecutar FastAPI con un solo worker y
mantener el backfill como proceso controlado.

## Workers

No ejecutar varios workers si BART vive dentro del mismo backend:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
```

Cada worker es otro proceso y cargaria otra copia de los modelos.
