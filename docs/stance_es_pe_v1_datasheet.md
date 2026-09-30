# Ficha del corpus Kenta Stance Perú v1

## Estado

Versión en construcción. El lote histórico de 122 pares se conserva como
`development` y no constituye el test final. Sus dos casos inicialmente
pendientes fueron reanotados; la distribución adjudicada es 50 `agree`,
12 `disagree`, 9 `discuss` y 51 `unrelated`. No se permite usar esos 122 pares
en validación ni en el test final.

## Propósito

Adaptar y evaluar un clasificador de *stance* para claims y artículos de noticias
políticas peruanas en español. El corpus no mide veracidad, sesgo ni credibilidad
de la fuente.

## Diseño previsto

- Objetivo: 800 pares adjudicados, 200 por clase.
- Entrenamiento: 480 pares, 120 por clase.
- Validación: 160 pares, 40 por clase.
- Test final congelado: 160 pares, 40 por clase.
- Contingencia mínima: 640 pares (400/80/160), sin reducir el test.
- Anotación doble ciega y adjudicación de todos los desacuerdos.
- Al menos seis fuentes peruanas; ninguna debe aportar más del 25 % del total.
- Agrupación por evento, familia de claim y artículo para evitar fuga.

## Procedencia

Los textos deben provenir de medios o entidades peruanas y conservar nombre de
fuente, título, URL, fecha cuando exista y un identificador estable. La selección
debe cubrir varios actores, instituciones, regiones, temas y momentos. Los casos
dirigidos para aumentar `disagree` o `discuss` se identifican en metadatos, nunca
se presentan al anotador como etiqueta sugerida.

## Esquema mínimo

| Campo | Descripción |
| --- | --- |
| `pair_id` | Identificador estable del par. |
| `corpus_version` | Versión del corpus. |
| `intended_use` | `development`, `train_candidate`, `validation_candidate` o `test_candidate`. |
| `batch_id` | Lote de recolección/anotación. |
| `group_id` | Grupo indivisible para el *split*. |
| `event_id` | Evento o historia periodística común. |
| `claim_id` | Identificador de la familia de claim. |
| `article_id` | Identificador estable o huella del artículo. |
| `source_name`, `ownership_group`, `title`, `original_url`, `published_at` | Procedencia y concentración editorial. |
| `collected_at`, `collection_method`, `article_sha256` | Trazabilidad de la captura textual. |
| `claim`, `article` | Textos de entrada. |
| `label_annotator_1`, `label_annotator_2` | Etiquetas independientes. |
| `evidence_annotator_1/2`, `confidence_annotator_1/2` | Evidencia textual y seguridad de la decisión. |
| `adjudicated_label`, `adjudication_note` | Resolución del desacuerdo o exclusión. |
| `final_label` | Etiqueta derivada y validada, no editada manualmente. |
| `quality_status`, `quality_flags` | Inclusión y observaciones de auditoría. |
| `split` | `train`, `validation` o `test`, asignado después de adjudicar. |

## Calidad y exclusión

Se excluyen textos vacíos o truncados, claims ininteligibles, pares duplicados por
error, páginas que no corresponden al contenido y casos sin evidencia suficiente
para una anotación responsable. Los duplicados intencionales de un artículo con
claims diferentes permanecen, pero comparten `group_id`.

## División y publicación

La división se realiza después de la adjudicación mediante grupos, con semilla
registrada. Se exporta un manifiesto con conteos por clase, grupos por *split*,
fuentes y SHA-256. El test final se mantiene separado de los ciclos de ajuste.

## Evaluación prevista

La métrica principal es macro-F1 con intervalo de confianza del 95 % mediante
*bootstrap* por grupos. También se reportan exactitud, matriz de confusión,
precision/recall/F1 por clase y, de forma explícita, recall y F1 de `disagree`.
Se ejecutan semillas 42, 123 y 2026.

## Umbral de despliegue predeclarado

Para considerar el componente local: macro-F1 mayor o igual a 0.60; F1 y recall
de `disagree` mayores o iguales a 0.50; ninguna clase con F1 menor a 0.40; ninguna
clase sin predicciones. Además, se revisa un lote operacional prospectivo de al
menos 120 pares consecutivos con prevalencia natural. Si falla un criterio, el
componente permanece experimental o deshabilitado.

## Limitaciones conocidas

El balance intencional por clase no representa la prevalencia real. El dominio
político y las fuentes seleccionadas limitan la generalización. Las etiquetas
expresan la relación textual claim–artículo, no una sentencia de veracidad.

## Lote de calibración 01

Se recolectaron 162 artículos no duplicados y se generaron 543 pares candidatos.
El lote ciego contiene 80 pares: 20 por cada estrategia de construcción
(`same_article_title`, `explicit_refutation`, `reported_claim` y `hard_negative`).
Estas estrategias son estratos de muestreo privados, no etiquetas sugeridas ni
garantías de clase. Los anotadores no reciben esos metadatos.

Jimena y Salvador anotaron de forma independiente los 80 pares. Coincidieron
en 71 (88,75 %; κ de Cohen = 0,7118). Ninguno emitió `disagree`. La revisión
posterior resolvió 49 filas prioritarias: 46 quedaron con `include` y 3 con
`exclude`; las 31 filas de consenso sin banderas todavía requieren el control
de muestra previsto antes de pasar a un maestro final. Entre los 46 incluidos
revisados hay 26 `agree`, 9 `discuss` y 11 `unrelated`.

La estrategia automática de posible refutación falló como mecanismo de
muestreo para `disagree`. El generador posterior exige candidatos de
refutación revisados con URL de procedencia del claim, cita de origen, pasaje
contradictorio literal del artículo y justificación privada. No se generan
etiquetas a partir de esas estrategias. La ausencia de `disagree` en esta ola
impide presentarla como corpus nuevo completo de cuatro clases o como test
local del modelo.

## Estado de uso en Kenta

`STANCE_PUBLIC_ENABLED=false` es la configuración predeterminada. En ese
estado, el pipeline no carga ni consulta el checkpoint de stance para el
análisis público, no usa stance para ajustar el riesgo agregado de claims y
no publica la etiqueta como capacidad validada. Los experimentos offline
pueden seguir evaluando el checkpoint. La habilitación pública exige superar
las puertas de evaluación anteriores y revisar las predicciones ya persistidas:
desactivar el cálculo nuevo no recalcula retrospectivamente puntajes guardados.

## Calibración 02a (pendiente de anotación)

Se preparó un piloto ciego de 20 pares, con semilla 20260920: cinco candidatos
por estrategia de muestreo y 20 artículos distintos. Cinco pares proceden de
verificaciones peruanas que contienen un pasaje de refutación literal; esto
**no** constituye una etiqueta `disagree`. La búsqueda original identificó
seis leads y uno quedó en reserva por la selección aleatoria. Los cuerpos de
los cinco pares seleccionados se extrajeron con éxito y sus fragmentos de
refutación se verificaron como subcadenas literales. Una fuente original se
leyó directamente; los enlaces originales de cinco videos/publicaciones de
los seis leads no pudieron reproducirse en esta sesión y conservan ese estado
de procedencia en la clave privada.

Las planillas de Jimena y Salvador muestran únicamente el claim y el cuerpo
fijado, sin titular, medio, URL, estrategia ni evidencia de cribado. Ambos
deben anotar independientemente antes de comparar respuestas. El piloto no
entra al corpus maestro, al entrenamiento ni al test hasta pasar la revisión
de procedencia, anotación y adjudicación. Los artículos de verificación son
un estrato dirigido para encontrar refutaciones; su estilo no debe dominar
el test local representativo ni el lote operacional prospectivo.
