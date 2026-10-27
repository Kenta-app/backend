# Prueba integral de recuperación y postura de evidencia

## Objetivo

Evaluar el flujo completo que parte de una publicación, busca fuentes externas,
selecciona evidencia y asigna una postura. Esta prueba complementa la evaluación
confirmatoria de pares fijos: no sustituye esa medición, porque aquí también se
evalúa la recuperación.

## Diseño congelado

- Protocolo: `evidence-end-to-end-pilot-v1`.
- Fecha de ejecución: 24 de octubre de 2026.
- Semilla: `20261024`.
- Unidad de muestreo: una publicación representativa; como máximo una por clúster existente.
- Población elegible: publicaciones web con texto suficiente, sin fuentes de
  justificación persistidas y no usadas en los archivos previos de desarrollo.
- Muestra: 20 publicaciones.
- Estratificación por medio: El Comercio 10, RPP Noticias 7 y Peru21 3.
- Estratificación por riesgo del clasificador: 9 bajo, 5 medio y 6 alto.
- La muestra se escribió y se selló antes de la primera consulta. SHA-256:
  `da028c761787d558f290006f9e8aec7b951fbda57c35ff141014cf166c886485`.

La selección sobre-representa medios minoritarios y bandas de riesgo medio y
alto. Por tanto, esta prueba sirve para detectar fallos y estimar desempeño en
la muestra, pero no estima directamente la prevalencia natural del feed.

## Ejecución del sistema

- Modelo: `gemini-3.5-flash-lite` con Google Search Grounding.
- Política de postura: `evidence-policy-2026-10-22-v3`.
- Casos con una o más fuentes: 11 de 20.
- Casos sin fuentes: 9 de 20.
- Errores operativos: 0.
- Pares publicación-fuente devueltos: 22.
- Posturas propuestas por el sistema: 11 `supports` y 11 `discusses`.

La distribución de posturas no debe interpretarse todavía como exactitud. Las
etiquetas permanecen ocultas en las planillas de los anotadores.

## Control de no persistencia

La tabla de fuentes de justificación tenía 69 filas antes de la ejecución y 69
filas al terminar. La prueba llamó la ruta de generación y validación, pero no
la operación que persiste fuentes. Los resultados de evaluación quedaron en
archivos separados.

## Evaluación humana ciega

Cada anotador recibe un libro con el mismo contenido y orden independiente.
Primero evalúa cada fuente:

- disponibilidad o suficiencia de contexto;
- relación con la afirmación;
- postura: `supports`, `refutes`, `discusses` o `unrelated`;
- confianza y nota justificativa.

Después evalúa cada caso completo mediante una búsqueda independiente breve:

- cobertura suficiente, parcial o nula;
- ausencia aparente de evidencia periodística;
- evidencia relevante omitida y, cuando exista, su URL.

Los anotadores no deben consultar entre sí ni acceder a la clave privada antes
de entregar sus archivos.

## Métricas posteriores

Tras recibir ambas planillas se calcularán, sin modificar las etiquetas del
sistema:

1. tasa de URLs evaluables;
2. precisión de recuperación entre fuentes evaluables;
3. acuerdo entre anotadores para relevancia, postura y cobertura;
4. exactitud y macro-F1 de postura contra consenso/adjudicación;
5. proporción de casos con cobertura suficiente o parcial;
6. tasa de omisiones relevantes y falsos vacíos de recuperación;
7. análisis de errores por medio y banda de riesgo.

Los desacuerdos se adjudicarán después de calcular el acuerdo previo. Como no se
definió un umbral de aprobación antes de esta corrida, el resultado debe
reportarse como piloto integral y no como una prueba confirmatoria con criterio
de éxito preregistrado.

## Limitación del flujo social

La instantánea de producción contenía 122 publicaciones web y ninguna
publicación de X. Esta corrida valida únicamente el flujo web. El contexto de
respuestas, citas e hilo de X requiere una prueba dirigida separada cuando haya
publicaciones sociales ingeridas con `social_context`; no es defendible afirmar
que quedó validado a partir de casos web o casos artificiales.

## Resultados previos a adjudicación

Los dos anotadores completaron los 22 pares y los 20 casos. El acuerdo de
postura entre las 19 fuentes que ambos pudieron evaluar fue 94,7% (κ=0,890).
Hubo 18 posturas con consenso exacto. En ese subconjunto, las 18 fuentes fueron
relevantes, pero la postura del sistema coincidió en 12 casos: 66,7% de
exactitud y macro-F1 de 0,663 para las clases observadas.

El acuerdo de cobertura fue menor: 50,0% (κ=0,310). Solo 10 de los 20 casos
tuvieron una categoría de cobertura consensuada. Entre los nueve casos
consensuados donde existía evidencia, cinco tuvieron cobertura útil. Entre los
cinco casos consensuados sin fuentes recuperadas, cuatro fueron vacíos falsos y
uno fue una abstención correcta.

Quedan pendientes de adjudicación cuatro pares de fuentes y diez casos de
cobertura. Las cifras anteriores deben citarse como resultados
**previos a adjudicación**; no son las métricas finales del piloto.

## Resultados finales adjudicados

La adjudicación resolvió los cuatro desacuerdos de fuentes y los diez casos de
cobertura. Las decisiones finales se aplicaron sobre el conjunto completo, sin
modificar las anotaciones originales ni recalcular el acuerdo entre anotadores.
El acuerdo se mantiene como una medición previa a la adjudicación.

- Las 22 fuentes quedaron evaluables y pertinentes: precisión de recuperación
  100,0% (22/22; IC95% de Wilson 85,1%–100,0%).
- La postura del sistema coincidió con la decisión humana final en 14 de 22
  fuentes: exactitud 63,6% (IC95% 43,0%–80,3%). El macro-F1 fue 0,633 para las
  clases observadas y 0,317 para las cuatro clases fijas.
- La matriz final solo tuvo ejemplos `supports` y `discusses`. Cinco fuentes
  `supports` fueron clasificadas como `discusses`, y tres `discusses` como
  `supports`.
- Existía evidencia relevante en 19 de 20 casos. Once de esos 19 tuvieron
  cobertura útil (`sufficient` o `partial`): 57,9%. Solo siete tuvieron
  cobertura suficiente: 36,8%.
- La distribución final de cobertura fue: 7 `sufficient`, 4 `partial`, 8
  `none` y 1 `no_evidence_found`.
- El sistema devolvió cero fuentes en nueve casos. Ocho fueron vacíos falsos y
  uno fue una abstención correcta. En doce casos se confirmó la omisión de al
  menos una fuente importante.

La lectura defendible es que la selección de fuentes funciona bien cuando la
recuperación encuentra resultados, pero el *recall* y la exhaustividad son el
cuello de botella. El módulo debe conservarse como prototipo y priorizar la
recuperación de evidencia, el contexto de la afirmación y la calibración de la
frontera `supports`/`discusses` antes de presentarse como un verificador robusto.
Estas conclusiones corresponden a un piloto estratificado pequeño, sin casos de
X y sin umbral de aprobación preregistrado.

## Criterios registrados para la siguiente iteración

Estos criterios se fijan después del piloto anterior y antes de ejecutar la
siguiente evaluación; no se aplican retroactivamente al resultado de octubre:

- al menos 16 de 20 casos con una o más fuentes recuperadas;
- cobertura útil en al menos 80% de los casos donde exista evidencia;
- tasa de vacíos falsos no mayor de 20% entre los casos sin resultados;
- exactitud de postura de al menos 75%;
- precisión de fuentes recuperadas no inferior a 90%.

La muestra congelada anterior se reutilizará únicamente como prueba de regresión.
Una muestra nueva y ciega será necesaria para la estimación confirmatoria, con
intervalos de confianza y los mismos criterios calculados antes de abrir las
anotaciones.

## Regresión de recuperación posterior a las correcciones

La misma muestra congelada se ejecutó nuevamente con la política
`retrieval-policy-2026-10-25-v1`. La política añade una segunda búsqueda cuando
no se alcanzan dos medios independientes, consultas literales y reformuladas,
una última búsqueda para resultados vacíos y un catálogo ampliado de medios
reconocidos. Los enlaces citados se usan como pistas, no como respaldo
automático, y las fuentes oficiales solo acreditan lo que publican o resuelven
dentro de su competencia.

- La recuperación aumentó de 11/20 a 17/20 publicaciones (55,0% a 85,0%).
- El número de pares recuperados aumentó de 22 a 29.
- No hubo errores operativos ni escrituras en la base de datos: la tabla de
  fuentes permaneció en 69 filas.
- El objetivo de al menos 16/20 casos con fuentes se cumplió.
- Persistieron tres resultados vacíos. Uno era la abstención correcta ya
  adjudicada y dos eran vacíos falsos; la tasa de vacíos falsos entre resultados
  vacíos fue 66,7%, por encima del máximo registrado de 20%.

La mejora de *recall* es material, pero no cierra la validación. Como las 29
fuentes no son las mismas del piloto anterior, dos anotadores deben revisar la
nueva salida antes de recalcular precisión, cobertura útil y exactitud de
postura. No deben trasladarse las etiquetas humanas anteriores a fuentes nuevas.

### Resultados ciegos previos a adjudicación

Los dos libros completados cubrieron los 29 pares de evidencia y los 20 casos
de cobertura. No se detectaron identificadores duplicados, etiquetas fuera del
protocolo ni notas obligatorias vacías. Estos resultados siguen siendo
preliminares: siete pares de fuentes y cuatro casos de cobertura requieren
adjudicación.

- El acuerdo de evaluabilidad fue 100,0% (29/29; κ=1,000).
- El acuerdo de postura entre fuentes evaluables fue 75,9% (22/29; κ=0,545).
- En los 22 pares con postura consensuada, las 22 fuentes fueron relevantes:
  precisión preliminar de recuperación de 100,0% (IC95% de Wilson
  85,1%–100,0%).
- La postura del sistema coincidió con el consenso en 16 de 22 pares: 72,7%
  (IC95% 51,8%–86,8%). El macro-F1 de las clases observadas fue 0,686.
- El acuerdo exacto de cobertura fue 80,0% (16/20; κ=0,630). En los 15 casos
  consensuados donde existía evidencia, 13 tuvieron cobertura útil (86,7%) y
  12 cobertura suficiente (80,0%).
- Los tres casos sin resultados tuvieron consenso: uno fue una abstención
  correcta y dos fueron vacíos falsos. La tasa de vacíos falsos permaneció en
  66,7% (2/3).

Frente a los criterios registrados, la recuperación de 17/20, la precisión de
fuentes y la cobertura útil cumplen de forma preliminar; la tasa de vacíos
falsos no cumple y la exactitud de postura queda por debajo del 75%. La decisión
final debe recalcularse después de adjudicar los 11 desacuerdos, sin consultar
la etiqueta del sistema durante la adjudicación.

### Resultados finales adjudicados de la regresión

La adjudicación resolvió los siete desacuerdos de postura y los cuatro de
cobertura. Las 29 fuentes quedaron como evaluables y relevantes. La regresión
cumplió tres de los cinco criterios registrados, por lo que no corresponde
declarar que el módulo superó la validación completa.

- recuperación: 17/20 publicaciones (85,0%; cumple el mínimo de 16/20);
- precisión de fuentes: 29/29 (100,0%; IC95% de Wilson 88,3%–100,0%; cumple
  el mínimo de 90%);
- cobertura útil: 17/19 casos con evidencia (89,5%; cumple el mínimo de 80%);
- cobertura suficiente: 14/19 casos con evidencia (73,7%);
- exactitud de postura: 20/29 (69,0%; IC95% 50,8%–82,7%; no cumple el mínimo
  de 75%);
- vacíos falsos: 2/3 resultados sin fuentes (66,7%; no cumple el máximo de
  20%).

Frente al piloto inicial, la proporción de publicaciones con fuentes aumentó
de 55,0% a 85,0%, la cobertura útil de 57,9% a 89,5% y la cobertura suficiente
de 36,8% a 73,7%. La precisión se mantuvo en 100,0%. La exactitud de postura
subió de 63,6% a 69,0%, pero sigue por debajo del criterio registrado. Los dos
casos `refutes` fueron clasificados por el sistema como `supports` o
`discusses`, y seis de los 18 casos `supports` fueron clasificados como
`discusses`.

La siguiente iteración debe concentrarse en los dos vacíos falsos persistentes
y en la calibración de `supports`, `discusses` y `refutes`. Como esta evaluación
reutilizó la muestra congelada del piloto, una muestra nueva y ciega sigue
siendo necesaria para una estimación confirmatoria.

## Corrección posterior v4 (regresión de desarrollo)

Se implementaron dos cambios dirigidos a los fallos adjudicados:

1. una búsqueda corta y focalizada para resultados vacíos, con términos
   distintivos, anclas numéricas y consultas por dominio; y
2. una revisión separada de postura que no puede buscar ni cambiar las fuentes
   recuperadas.

El catálogo de recuperación incorporó `canalb.pe`, `voz.pe` y `willax.pe` para
el caso dirigido que antes quedaba vacío. Su inclusión solo autoriza que sean
considerados como resultados identificables: no los convierte en fuentes
verdaderas por defecto ni modifica la evaluación de postura.

En ejecuciones dirigidas, `E2E-016` pasó de cero a una fuente relacionada y
`E2E-018` de cero a dos fuentes relacionadas. Sobre los 29 pares ya adjudicados,
la revisión v4 obtuvo 26 aciertos (89,7%), frente a 20 (69,0%) de la salida
anterior. La matriz resultante contiene 17/18 aciertos en `supports`, 8/9 en
`discusses` y 1/2 en `refutes`.

Este 89,7% **no es una nueva medición confirmatoria**: las etiquetas ya habían
sido abiertas y se usaron para desarrollar las reglas. Sirve para demostrar
que los errores conocidos no reaparecen en la mayoría de los casos. El siguiente
paso metodológico sigue siendo congelar v4 y evaluarla con noticias y anotaciones
nuevas, sin consultar este conjunto durante el análisis.
