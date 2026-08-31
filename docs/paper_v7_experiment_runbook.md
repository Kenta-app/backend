# Runbook de experimentos — paper Kenta v7

Este runbook separa evidencia ya reproducible, trabajo humano pendiente y los
resultados que se pueden reportar en el paper.

## 1. Línea base y significancia estadística

Ejecutar desde la raíz del repositorio con el entorno virtual activo:

```powershell
.\.venv\Scripts\python.exe scripts\paper_statistics.py --tasks fakenews --bootstrap-samples 10000 --results-dir output\paper_v7\statistics\fakenews
.\.venv\Scripts\python.exe scripts\paper_statistics.py --tasks stance --bootstrap-samples 10000 --results-dir output\paper_v7\statistics\stance
.\.venv\Scripts\python.exe scripts\paper_statistics.py --tasks summarization --bootstrap-samples 10000 --results-dir output\paper_v7\statistics\summarization
```

El script guarda predicciones sin texto de artículos, IC 95% por modelo,
comparaciones bootstrap pareadas y McNemar para accuracy en clasificación.

Resultados ya obtenidos con 10 000 remuestreos (semilla 42):

- Fake news: XLM-RoBERTa alcanza el mayor macro-F1 observado (0.9478), pero
  sus diferencias frente a mBERT y DistilmBERT no son significativas.
- Stance FNC-1: mBERT con muestreo ponderado obtiene macro-F1 0.7225
  (IC 95%: 0.7111–0.7338), con mejoras pareadas frente a mBERT y DistilmBERT
  ponderado (ambos p bootstrap = 0.0002).
- Resumen sintético: BART tiene el mayor ROUGE-L observado (0.3165), pero la
  diferencia BART–mT5 en ROUGE-L no es significativa (p = 0.5440).

**Regla de redacción:** si el IC 95% de la diferencia incluye 0, el paper debe
decir *best observed performance* y no *superior performance*.

## 2. Resúmenes con referencias humanas

Abrir `output/paper_v7/annotation_inputs/human_summary_annotation_workbook.xlsx`.

1. Cada autor redacta referencias originales para aproximadamente 50 filas
   `Selected` de la hoja `References`.
2. Cada referencia debe tener 60–100 palabras, ser neutral y derivarse del
   artículo de la hoja `Candidates`.
3. Marcar `Complete` únicamente después de una segunda lectura.
4. Sustituir una fila excluida por una fila `Reserve`.
5. Cuando existan 100 referencias completas, exportarlas a CSV y usarlas como
   entrada de `scripts/benchmark_summarizers.py`.

No presentar las referencias sintéticas actuales como referencias humanas ni
mezclarlas en el nuevo benchmark.

## 3. Validación de stance en español peruano

1. Hacer dos copias independientes de
   `output/paper_v7/annotation_inputs/spanish_stance_annotation_workbook.xlsx`.
2. Seguir `docs/spanish_stance_annotation_protocol.md` y etiquetar sin mirar
   la columna del otro anotador.
3. Consolidar ambas etiquetas en el CSV maestro y adjudicar desacuerdos.
4. Generar el test final:

```powershell
.\.venv\Scripts\python.exe scripts\adjudicate_spanish_stance_annotations.py
```

5. Evaluar el checkpoint seleccionado en el nuevo conjunto:

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_stance_model.py `
  --model_dir output\stance_mbert_weighted_paper\best_model `
  --validation_stances output\paper_v7\spanish_stance_test\test_stances.csv `
  --validation_bodies output\paper_v7\spanish_stance_test\test_bodies.csv `
  --output_json output\paper_v7\spanish_stance_test\evaluation.json `
  --output_md output\paper_v7\spanish_stance_test\evaluation.md
```

No reentrenar el modelo usando ese test externo. Si la validación requiere un
conjunto de entrenamiento peruano, crear un split separado y reservar estos
pares exclusivamente para prueba final.

## 4. Criterio para actualizar el paper

Actualizar Results/Discussion/Conclusion solo cuando se hayan guardado:

- el reporte de IC 95% y comparaciones pareadas;
- el informe de acuerdo de stance y su distribución final de clases; y
- el benchmark de resumen contra las referencias humanas.

Declarar con precisión qué hallazgos se sostienen solo en FNC-1 y qué hallazgos
se replican sobre los nuevos datos peruanos.
