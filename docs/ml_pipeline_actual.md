# Pipeline ML actual

Este documento describe la arquitectura vigente despues de retirar el enfoque
multitask como ruta principal.

## Decision de arquitectura

El pipeline actual usa componentes dedicados:

1. Extraccion de claims: `app/ml/claim_extractor.py`
2. Clasificacion de fake news: `app/ml/fakenews_classifier.py`
3. Clasificacion de stance: `app/ml/stance_classifier.py`
4. Agregacion de claims: `app/ml/pipeline.py`
5. Resumen: `app/ml/summarizer.py`

El modelo multitask quedo fuera del flujo principal porque no fue el componente
que dio mejores resultados. La ruta activa ahora es `dedicated_components`.

## Configuracion runtime

Archivo: `.env`

```text
FAKENEWS_MODEL_DIR=output/fakenews_es_pe_full_v1/best_model
FAKENEWS_ARTICLE_LOW_THRESHOLD=0.8805
FAKENEWS_ARTICLE_HIGH_THRESHOLD=0.8889
FAKENEWS_USE_CLAIMS=true
STANCE_MODEL_DIR=output/stance_bert/best_model
SUMMARIZER_MODEL_NAME=facebook/bart-large-cnn
```

## Modelo de fake news

Modelo activo:

```text
output/fakenews_es_pe_full_v1/best_model
```

Base:

```text
xlm-roberta-base
```

Etiquetas:

```text
False -> falso / fake
True  -> verdadero / real
```

Metricas del checkpoint:

| Split | Macro-F1 | Accuracy |
| --- | ---: | ---: |
| Validation | 0.9357 | 0.9426 |
| Test | 0.9478 | 0.9530 |

Calibracion sobre:

```text
data/calibration_candidates_v11_annotated_reanalyzed_es_pe_full_v1_clean.csv
```

Umbrales activos:

| Umbral | Valor | Uso |
| --- | ---: | --- |
| Low | 0.8805 | `risk_score <= low` => probable verdadero |
| High | 0.8889 | `risk_score >= high` => probable falso |

Metricas de calibracion:

| Metrica | Valor |
| --- | ---: |
| false_precision | 0.9570 |
| false_recall | 0.9780 |
| true_precision | 0.9863 |
| true_recall | 0.9731 |
| macro_f1 | 0.9735 |
| decided_accuracy | 0.9749 |
| coverage | 1.0000 |

## Claims

El extractor actual es heuristico:

```text
strategy = heuristic_v9
```

Responsabilidades:

- Detectar claims verificables desde titulo y cuerpo.
- Proyectar claims reportados o refutados hacia un `stance_target`.
- Construir `model_input` autocontenido cuando el claim necesita contexto.
- Filtrar opiniones, citas subjetivas, preguntas de bajo valor, fragmentos
  numericos y textos promocionales.

Cuando hay stance disponible, la agregacion usa:

```text
claim_veracity_x_article_stance
```

Cuando no hay checkpoint de stance disponible, la agregacion cae a:

```text
claim_veracity_only
```

Ese fallback ya no depende de multitask.

## Stance

Componente dedicado:

```text
app/ml/stance_classifier.py
```

Checkpoint esperado:

```text
output/stance_bert/best_model
```

Entrenamiento:

```text
python -m app.ml.training.train_stance
```

Etiquetas:

```text
unrelated
discuss
agree
disagree
```

Uso dentro del pipeline:

- Stance articulo: clasifica relacion titulo/cuerpo.
- Stance por claim: mide si el articulo apoya o refuta el claim extraido.
- Si el checkpoint no existe, el pipeline no falla mientras el modelo de fake
  news este listo; agrega claims solo con veracidad y devuelve un warning.

## Resumen

Servicio:

```text
app/ml/summarizer.py
```

Modelo por defecto:

```text
facebook/bart-large-cnn
```

El resumen se genera solo si:

- `include_summary=true`, y
- el texto supera `SUMMARY_MIN_CHARS`, o se usa `force_summary=true`.

## Archivos retirados

Se retiro la ruta multitask antigua:

- `app/ml/multitask_model.py`
- `app/ml/roberta_loader.py`
- `app/ml/training/config.py`
- `app/ml/training/train.py`
- `app/ml/training/trainer.py`

Se mantuvieron los entrenamientos dedicados:

- `app/ml/training/train_fakenews.py`
- `app/ml/training/train_stance.py`
- `app/ml/training/fakenews_data.py`
- `app/ml/training/datasets.py`
- `app/ml/training/losses.py`

## Pendientes recomendados

1. Confirmar si el checkpoint de stance existe o entrenarlo en
   `output/stance_bert/best_model`.
2. Generar un reporte final de calibracion versionado para `full_v1`.
3. Evaluar un extractor de claims con API IA como experimento comparativo, no
   como reemplazo inmediato del baseline.
4. Si se adopta claims con IA, recomputar calibracion porque cambia la
   distribucion de entradas al clasificador.
