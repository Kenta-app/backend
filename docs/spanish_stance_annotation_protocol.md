# Protocolo de anotación de stance en español peruano

## Propósito

Crear un conjunto de prueba externo para evaluar el modelo de stance de Kenta
sobre pares reales de **claim–artículo político peruano**. Este conjunto se usa
solo para evaluación: no se mezcla con FNC-1 ni se utiliza para reentrenar el
checkpoint reportado en el paper.

## Material

`output/paper_v7/annotation_inputs/spanish_stance_annotation_workbook.xlsx`
es la planilla de anotación ciega. Cada tesista debe guardar una copia propia
y completar las columnas `Anotador`, `Etiqueta` y `Notas`. El CSV maestro
`output/paper_v7/annotation_inputs/spanish_stance_candidates_100.csv` contiene
los mismos 100 pares sin predicciones del modelo:

- 50 `source_pair`: el claim fue extraído del artículo fuente;
- 50 `cross_pair`: el claim y el artículo proceden de piezas distintas para
  incorporar candidatos naturalmente no relacionados.

La columna `pair_construction` es metadato de muestreo, **no una etiqueta**. No
la uses para decidir la clase.

## Flujo para los dos anotadores

1. Cada tesista trabaja en una copia independiente de la planilla, sin ver las
   etiquetas de la otra persona.
2. Lean el claim y el artículo completo. El título y la URL sirven para ubicar
   el contexto, pero la etiqueta debe basarse en el contenido del artículo.
3. No consulten predicciones del modelo ni elijan una clase por el veredicto de
   fake news. La tarea es exclusivamente la relación entre texto y claim.
4. Al terminar, integren ambas etiquetas en el CSV maestro. Para cada
   desacuerdo, discutan el caso y registren el resultado en
   `adjudicated_label` y una razón breve en `adjudication_note`.
5. Ejecuten `scripts/adjudicate_spanish_stance_annotations.py` para generar el
   CSV FNC-compatible, el informe de acuerdo y el test externo final.

## Definiciones de etiqueta

| Etiqueta | Decisión |
| --- | --- |
| `agree` | El artículo afirma, respalda o presenta el claim como verdadero. |
| `disagree` | El artículo refuta, niega o aporta evidencia claramente contraria al claim. |
| `discuss` | El artículo trata el claim, pero no lo respalda ni lo refuta de forma clara. |
| `unrelated` | El artículo no trata el mismo hecho, actor o proposición de forma sustantiva. |

En casos de duda, elijan la etiqueta más conservadora y expliquen el criterio
en `adjudication_note`. No inventen una quinta clase. Si un artículo está roto,
duplicado o no permite una decisión responsable, registren `exclude` como
`adjudicated_label` y justifiquen la exclusión.

## Criterio de aceptación

- Meta: al menos 80 pares adjudicados, con presencia de las cuatro etiquetas.
- Reportar tamaño final, distribución por clase, acuerdo inicial y Cohen's
  kappa antes de adjudicación.
- Si una clase queda con menos de 10 casos, recolectar/anotar candidatos
  adicionales antes de usar macro-F1 como resultado principal.
- El paper debe describir este conjunto como una validación externa manual,
  con sus límites de tamaño y de procedencia de fuentes.
