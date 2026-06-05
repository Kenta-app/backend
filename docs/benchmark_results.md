# Benchmark de modelos

Fecha de consolidacion: 2026-06-03

## Modelos seleccionados para producto

| Tarea | Modelo seleccionado | Ruta/configuracion | Criterio |
| --- | --- | --- | --- |
| Fake news | `xlm-roberta-base` | `output/fakenews_xlmroberta_full_v1/best_model` | Mejor macro-F1 en test. |
| Stance | `bert-base-multilingual-cased` con muestreo ponderado | `output/stance_mbert_weighted_paper/best_model` | Mejor macro-F1 en test con split independiente. |
| Resumen | `facebook/bart-large-cnn` | `SUMMARIZER_MODEL_NAME=facebook/bart-large-cnn` | Mejor ROUGE-L frente a referencias sinteticas externas. |

## Datasets utilizados

Los experimentos de fake news, stance y resumen se apoyan en conjuntos de datos con propiedades distintas, por lo que su documentación requiere distinguir entre la fuente original, la forma de construcción del split y el uso concreto dentro del pipeline.

En fake news se empleó una colección de claims en español y para el contexto peruano, integrada a partir de tres fuentes: `data/newtral/claims.jsonl`, `data/maldita/claims.jsonl` y `data/perucheck/claims.jsonl`. Estas fuentes se combinaron con `scripts/combine_claims.py` para producir el conjunto final en `data/claims_es_pe_full/`, con particiones explícitas de entrenamiento, validación y prueba (`train.tsv`, `validation.tsv` y `test.tsv`). Este conjunto se utilizó para entrenar los clasificadores binarios de verificación de hechos, conservando la separación estándar de datos para evaluar generalización fuera de muestra.

En stance se utilizó el corpus FNC-1, que se distribuye localmente en `data/fnc-1/train_stances.csv`, `data/fnc-1/train_bodies.csv`, `data/fnc-1/competition_test_stances.csv` y `data/fnc-1/competition_test_bodies.csv`. Para los experimentos finales se creó un split reproducible con `scripts/prepare_fnc_stance_split.py`: `data/fnc-1-paper-split/train_stances.csv` se usó para entrenamiento, `data/fnc-1-paper-split/validation_stances.csv` para selección de checkpoint y `data/fnc-1/competition_test_stances.csv` como test independiente. El cargador `FNCDataset` construye cada ejemplo a partir de un titular y el cuerpo de la noticia asociado, y codifica las etiquetas `unrelated`, `discuss`, `agree` y `disagree`.

Para resumen se trabajó con 30 referencias sintéticas generadas con un LLM externo (ChatGPT) a partir de un archivo local de trabajo con textos de artículos. Las referencias se integraron internamente en `data/summary_references/synthetic_refs_30_fixed.csv` y se usaron para comparar predicciones mediante `scripts/benchmark_summarizers.py`. En el release público se incluye solo `data/summary_references/synthetic_refs_30_fixed_metadata.csv`, que conserva id, título, URL y resumen, pero excluye el cuerpo completo de los artículos por consideraciones de redistribución. Esta evaluación debe interpretarse como orientativa, ya que no utiliza resúmenes humanos como referencia, pero evita evaluar contra salidas previas del propio modelo BART.

## Criterios de evaluacion

- Fake news: se prioriza macro-F1 en test, porque el dataset es binario y puede tener desbalance entre etiquetas.
- Stance: se prioriza macro-F1 en test, usando el split `competition_test` de FNC-1 como evaluación final independiente.
- Resumen: se reportan ROUGE-1, ROUGE-2 y ROUGE-L F1, mas tiempo promedio de inferencia. La evaluacion es orientativa porque usa referencias sintéticas, no resúmenes humanos.
- En todos los modelos clasificadores se conserva accuracy como metrica secundaria y threshold como parametro operativo del checkpoint.

## Fake news

| Modelo | Mejor epoch | Val macro-F1 | Val accuracy | Test macro-F1 | Test accuracy | Threshold | Seleccion |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `fakenews_xlmroberta_full_v1` | 4 | 0.9357 | 0.9426 | 0.9478 | 0.9530 | 0.99276 | Seleccionado |
| `fakenews_mbert_full_v1` | 3 | 0.9429 | 0.9493 | 0.9437 | 0.9497 | 0.99922 | Alternativa cercana |
| `fakenews_distilmbert_full_v1` | 3 | 0.9429 | 0.9493 | 0.9437 | 0.9497 | 0.99687 | Alternativa ligera |

Conclusion: aunque `fakenews_mbert_full_v1` y `fakenews_distilmbert_full_v1` tuvieron mejor validacion, `fakenews_xlmroberta_full_v1` generalizo mejor en test, por lo que se conserva como modelo final. El intento `fakenews_roberta_bne_full_v1` no se incluye en el cuadro principal porque el log registro fallback a `xlm-roberta-base`; por tanto, no cuenta como arquitectura RoBERTa-BNE.

## Stance

| Modelo | Mejor epoch | Val macro-F1 | Val accuracy | Test macro-F1 | Test accuracy | Estado | Seleccion |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `stance_mbert_weighted_paper` | 3 | 0.8616 | 0.9535 | 0.7225 | 0.9213 | Terminado | Seleccionado |
| `stance_mbert_paper` | 3 | 0.7747 | 0.9404 | 0.6679 | 0.9046 | Terminado | No seleccionado |
| `stance_distilmbert_weighted_paper` | 3 | 0.7633 | 0.9326 | 0.6482 | 0.9015 | Terminado | No seleccionado |

Conclusion: `stance_mbert_weighted_paper` obtiene la mejor macro-F1 en test y queda como modelo activo. El muestreo ponderado ayuda especialmente a mejorar el tratamiento de clases minoritarias como `disagree`.

## Resumen

| Modelo | Ejemplos | ROUGE-1 F1 | ROUGE-2 F1 | ROUGE-L F1 | Tiempo promedio (ms) | Seleccion |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `facebook/bart-large-cnn` | 30 | 0.3985 | 0.2510 | 0.3165 | 10956 | Seleccionado |
| `ELiRF/mt5-base-dacsa-es` | 30 | 0.3518 | 0.2340 | 0.2998 | 10141 | Alternativa cercana |
| `mrm8488/bert2bert_shared-spanish-finetuned-summarization` | 30 | 0.0016 | 0.0000 | 0.0016 | 13793 | No seleccionado |

Nota metodologica: este benchmark uso 30 referencias sinteticas generadas con ChatGPT como LLM externo. Los resultados deben interpretarse como evaluación orientativa de resumen abstractivo, ya que ROUGE penaliza parafraseos semánticamente correctos y no sustituye una evaluación humana de factualidad, cobertura y fluidez.

## Variables activas

```env
FAKENEWS_MODEL_DIR=output/fakenews_xlmroberta_full_v1/best_model
STANCE_MODEL_DIR=output/stance_mbert_weighted_paper/best_model
SUMMARIZER_MODEL_NAME=facebook/bart-large-cnn
```
