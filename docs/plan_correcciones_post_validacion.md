# Plan de correcciones posteriores a la validación — Kenta

## 1. Objetivo

Corregir los problemas detectados en la validación sin confundir tres conceptos
distintos:

1. **procedencia o autoridad de la fuente**: quién publica y para qué ámbito es
   una fuente primaria;
2. **riesgo estimado del contenido**: salida probabilística del clasificador de
   Kenta;
3. **respaldo externo**: evidencia independiente que apoya, contradice o solo
   menciona la afirmación analizada.

El resultado esperado es una versión más comprensible, trazable y evaluable, no
un sistema que presente predicciones automáticas como veredictos de verdad.

### Estado de implementación — 21 de octubre de 2026

Primer corte implementado:

- El score de El Peruano se conserva internamente para auditoría, pero no se
  publica mientras se investiga el fallo sistemático reportado. La API devuelve
  `riskLevel=not_assessed`, una política versionada y el disclaimer institucional;
  no sustituye el resultado por un 100 % de confiabilidad.
- El feed aplica por defecto `likely_real`, `indeterminate` y `not_assessed` en
  el servidor antes de contar y paginar. La interfaz permite incluir
  `likely_fake` explícitamente.
- Bordes y badges derivan de la misma categoría pública.
- La ingesta de X solicita `conversation_id` y `referenced_tweets`, conserva la
  publicación citada o respondida y la añade como bloque etiquetado a la entrada
  del modelo. El detalle muestra qué referencia fue considerada.
- Las fuentes relacionadas ya se registran con afirmación, postura, relevancia,
  método y versión. El estado agregado exige dos dominios de medios distintos y
  permanece separado del score base. En esta versión, “distinto” solo significa
  dominio editorial distinto; la detección de republicaciones de una misma
  agencia continúa pendiente y se declara mediante
  `independenceStatus=publisher_domain_only`.
- El piloto humano de postura ya cuenta con protocolo versionado, exportación
  ciega balanceada para dos anotadores, adjudicación y cálculo reproducible de
  kappa, macro-F1, métricas por clase, matriz de confusión e intervalo bootstrap.
  Se procesaron 80 noticias y se obtuvieron 69 evidencias elegibles. Tras
  deduplicar por afirmación y dominio editorial, el piloto congelado contiene 67
  pares: 49 clasificados por el sistema como `supports` y 18 como `discusses`.
  No aparecieron ejemplos `refutes` ni `unrelated`; por ello, el piloto sirve
  para medir acuerdo y desempeño en las clases observadas, pero no permite
  defender todavía un macro-F1 representativo de las cuatro clases. La
  anotación humana y la adjudicación finalizaron con 63 casos incluidos y 4
  excluidos por contexto insuficiente. El acuerdo bruto fue 88.9 % y el kappa
  de Cohen 0.715. Frente al gold adjudicado, el modelo obtuvo 82.5 % de
  exactitud y macro-F1 de 78.2 % en las clases observadas (`supports` y
  `discusses`), con intervalo bootstrap de 95 % entre 66.1 % y 88.3 %. El
  macro-F1 fijo de cuatro clases fue 39.1 % y se conserva únicamente como
  indicador de cobertura incompleta, porque dos clases tuvieron soporte cero.
- El 22 de octubre se inició el bloque de cobertura de clases escasas. La
  política de postura se versionó como `evidence-policy-2026-10-22-v2` y ahora
  exige coincidencia de todos los elementos materiales de la proposición para
  usar `supports`; una confirmación parcial, un antecedente o el estado de un
  proceso se etiqueta como `discusses`. También se preparó una muestra ciega de
  desafío con 40 pares: 13 `refutes`, 20 `unrelated` y 7 casos frontera
  `supports`/`discusses`. Es una muestra dirigida de desarrollo que reutiliza
  etiquetas humanas previas y no estima prevalencia ni reemplaza una evaluación
  confirmatoria independiente. La disponibilidad local solo permitió 13 casos
  `refutes`, concentrados en cobertura política y electoral, por lo que aún se
  requiere recolectar refutaciones nuevas y más diversas.

Pendiente de fases posteriores: completar la doble anotación de la muestra
dirigida, recolectar al menos 7 refutaciones nuevas y más diversas para llegar a
20, construir después un conjunto confirmatorio independiente, reconstrucción
más amplia de hilos, anotación
humana y detección de confirmación circular entre fuentes, recuperación de
contraseña, auditoría de contraste oscuro y experimento de resúmenes.

## 2. Diagnóstico original que motivó los cambios

- El backend ya tiene una política ternaria única: `likely_real`,
  `indeterminate` y `likely_fake`, con umbrales configurables.
- La interfaz llama “credibilidad” a una señal que en realidad representa
  **riesgo de desinformación del contenido**.
- La tarjeta decide el color del borde a partir de `1 - fakeScore`, mientras la
  etiqueta usa `riskLevel`. Son dos rutas de presentación y pueden parecer
  contradictorias.
- Las fuentes relacionadas se recuperan, validan y muestran, pero no existe una
  evaluación explícita de si cada fuente apoya, contradice o solo trata el mismo
  tema. Por tanto, su mera existencia no debe incrementar la credibilidad.
- La ingesta de X recupera el texto principal, autor y multimedia, pero no pide
  `conversation_id` ni `referenced_tweets`; tampoco conserva una representación
  del hilo o de la publicación citada.
- El filtro de riesgo existente es client-side. Usarlo con paginación infinita
  produciría conteos y páginas incompletas si se activa por defecto.
- Existe cambio de contraseña para una sesión autenticada, pero no recuperación
  de contraseña para una persona que no puede iniciar sesión.
- Los resúmenes tienen límites globales de longitud; no existe todavía una
  evaluación de cobertura informativa por tipo y extensión de noticia.

## 3. Decisiones de diseño

### 3.1 El Peruano y fuentes institucionales

| Opción | Ventaja | Riesgo | Decisión |
|---|---|---|---|
| Forzar `fakeScore = 0` para El Peruano | Implementación rápida | Mezcla autoridad con veracidad, oculta errores y sesga métricas | Descartada |
| Reducir el score con un “prior” por medio | Permite una fusión numérica | Requiere calibración y datos etiquetados; puede introducir sesgo político | Trabajo futuro |
| Mantener el score y añadir autoridad institucional con alcance | Separa procedencia, contenido y evidencia; es auditable | Requiere cambios de datos y UI | **Elegida** |

Se implementará un registro de fuentes institucionales, inicialmente con El
Peruano, pero diseñado como configuración versionada y no como un `if` disperso.
Campos mínimos:

- `authority_type`: `official_state_publisher`;
- `authority_scope`: por ejemplo, `official_norms_and_state_announcements`;
- `authority_reason`: fundamento breve y visible;
- `authority_policy_version` y fecha de revisión;
- dominios y, si corresponde, rutas cubiertas;
- estado activo y responsable de aprobación.

La UI mostrará **“Fuente oficial del Estado peruano”** y este aviso:

> Esta identificación acredita el origen institucional de la publicación. No
> implica que Kenta haya verificado como verdadera cada afirmación ni reemplaza
> el contraste con evidencia independiente.

Regla recomendada por alcance:

- una norma legal o comunicado oficial es fuente primaria para demostrar qué
  norma se publicó o qué posición comunicó el Estado;
- una nota periodística, interpretación, proyección o cita de un tercero sigue
  siendo analizada como contenido;
- si el clasificador es inadecuado para una categoría documental, se mostrará
  `analysisStatus = not_applicable` o `insufficient_evidence`, no un 100 %
  inventado.

Antes de aplicar la política se auditará una muestra de falsos positivos de El
Peruano y se separarán al menos: normas, comunicados, noticias, opinión y texto
mal extraído. Esto permitirá saber si el problema proviene del dominio, del tipo
documental, del scraping o del modelo.

### 3.2 Contexto de publicaciones de X

Se conservará una instantánea estructurada, con límites explícitos, en vez de
concatenar texto sin procedencia. Datos mínimos:

- identificador nativo de la publicación;
- `conversation_id`;
- tipo de referencia: `replied_to`, `quoted` o `retweeted`;
- publicación padre y publicación citada, con autor y fecha;
- secuencia del hilo disponible en orden cronológico;
- estado de completitud: `complete`, `partial`, `deleted`, `private` o
  `unavailable`;
- fecha de captura y versión del constructor de contexto.

La consulta de la API deberá solicitar, según disponibilidad del plan de X:

- `tweet.fields=conversation_id,referenced_tweets,in_reply_to_user_id,entities`;
- expansiones de `referenced_tweets.id` y sus autores;
- búsqueda acotada por `conversation_id` para reconstruir el hilo cuando el
  endpoint y el nivel de acceso lo permitan.

Límites operativos recomendados: publicación principal + padre/cita + hasta 10
mensajes del mismo autor dentro de la conversación, con límite total de tokens.
No se incorporarán todas las respuestas públicas, porque agregan ruido y pueden
ser manipuladas.

La entrada al modelo distinguirá bloques:

```text
[PUBLICACION_ANALIZADA]
...
[PUBLICACION_CITADA]
...
[MENSAJES_PREVIOS_DEL_AUTOR]
...
[ENLACES_EXTERNOS_EXTRAIDOS]
...
```

Si el contexto no se pudo recuperar, la interfaz y el registro de inferencia lo
indicarán; no se fingirá que el análisis consideró el hilo completo.

### 3.3 Fuentes relacionadas como evidencia

Una fuente relacionada no equivale a una fuente corroborante. La decisión
elegida es mantener dos resultados separados en la primera versión:

- `contentRisk`: riesgo base del modelo;
- `evidenceAssessment`: `supported`, `disputed`, `mixed` o
  `insufficient_evidence`.

Cada evidencia tendrá:

- afirmación central asociada;
- relevancia con respecto a la afirmación;
- postura: `supports`, `refutes`, `discusses` o `unrelated`;
- fragmento literal que sustenta la postura;
- fuente, URL canónica, fecha y tipo de fuente;
- independencia respecto de la noticia original y de las demás evidencias;
- método/modelo y versión que produjo la evaluación.

El flujo será:

1. extraer una o más afirmaciones verificables;
2. recuperar candidatos;
3. descartar duplicados, mismo medio, baja relevancia y enlaces no resolubles;
4. detectar si varios medios repiten la misma fuente primaria para evitar
   “confirmación circular”;
5. clasificar la postura de cada evidencia;
6. agregar por diversidad e independencia, no por cantidad bruta;
7. mostrar razones y fragmentos auditables.

No se modificará el porcentaje público con esta señal hasta contar con un
conjunto etiquetado que permita calibrar y comparar una fusión contra el modelo
base. En una fase posterior se podrá probar una combinación supervisada y
calibrada; deberá mejorar Brier score/ECE y desempeño por clase sin empeorar de
forma relevante subgrupos por fuente o tipo de contenido.

### 3.4 Filtro predeterminado del feed

El filtro se implementará en el backend antes de paginar:

```http
GET /news?riskLevels=likely_real,indeterminate
```

Comportamiento recomendado:

- valor inicial: mostrar bajo riesgo + señales mixtas;
- control visible: **“Ocultar alto riesgo”**, activado por defecto;
- chip persistente que explique que hay contenido omitido;
- acción de un clic: **“Mostrar también alto riesgo”**;
- el backend devuelve conteo y cursor después de aplicar el filtro;
- la URL conserva la selección para que el estado sea reproducible;
- no eliminar ni despublicar contenido de alto riesgo.

Esto satisface la necesidad del feed sin crear una falsa impresión de que Kenta
solo contiene noticias verificadas. Para la tesis se registrará la versión del
filtro y no se cambiará durante una misma ronda formal de validación.

## 4. Plan de ejecución por fases

### Fase 0 — Congelar línea base y convertir comentarios en requisitos

1. Etiquetar el commit backend, frontend, modelos, umbrales y configuración de
   la ronda ya realizada.
2. Guardar los resultados cuantitativos y codificar los comentarios abiertos en
   temas: usabilidad, consistencia visual, comprensión, confianza y resumen.
3. Crear un conjunto de regresión con casos reales reportados: El Peruano,
   señales contradictorias, publicaciones citadas/respuestas, fuentes
   relacionadas y resúmenes demasiado cortos.
4. Definir métricas antes de tocar el sistema.

**Salida:** bitácora reproducible y backlog trazado desde hallazgo → requisito →
prueba → evidencia.

### Fase 1 — Corregir semántica y problemas de interfaz

1. Renombrar “Credibilidad” a **“Evaluación del contenido”** o **“Riesgo de
   desinformación estimado”**.
2. Sustituir “Señales mixtas” por **“Resultado no concluyente”** y añadir una
   explicación breve: el score está entre ambos umbrales y no permite clasificar
   con suficiente seguridad.
3. Hacer que borde, badge, leyenda y filtro dependan exclusivamente de
   `riskLevel`; eliminar la segunda clasificación visual basada en
   `confidence`.
4. Mostrar qué significa el porcentaje, qué no significa y los umbrales
   vigentes. Evitar “100 % confiable” y “noticia verdadera”.
5. Añadir una introducción de tres pasos o ayuda contextual en la primera visita.
6. Revisar contraste WCAG en modo oscuro para botones normales, hover, focus y
   disabled; validar con medición, no solo apreciación visual.
7. Implementar recuperación de contraseña con token de un solo uso, expiración,
   rate limit, respuesta que no revele si el correo existe e invalidación de
   sesiones al completar el cambio.
8. Cambiar el detalle para que el resumen no sea el único acceso al contenido:
   resumen breve + puntos clave o botón “Ver más contexto”, según el resultado
   del piloto.

**Gate:** una misma noticia debe tener categoría y color coherentes en feed,
detalle y guardados; cinco usuarios del piloto deben poder explicar las tres
categorías sin ayuda del investigador.

### Fase 2 — Registro de autoridad institucional

1. Añadir el registro versionado y su migración.
2. Clasificar rutas/tipos documentales de El Peruano.
3. Exponer `sourceAuthority` y `analysisStatus` en la API.
4. Mostrar insignia y disclaimer separados del resultado del modelo.
5. Reprocesar la muestra auditada y documentar casos donde el modelo no aplica.

**Gate:** ninguna regla cambia silenciosamente `fakeScore`; toda excepción deja
motivo, alcance y versión en datos.

### Fase 3 — Contexto de X

1. Ampliar la ingesta y crear las tablas/campos de contexto social.
2. Resolver publicación padre, cita e hilo con caché y límites de costo.
3. Construir el texto estructurado para inferencia y conservar la instantánea.
4. Reprocesar una muestra anotada con y sin contexto.
5. Mostrar al usuario qué partes del contexto se consideraron.

**Gate:** reducir errores atribuibles a contexto sin degradar el conjunto general;
reportar cobertura de contexto y casos parciales.

### Fase 4 — Evaluación de evidencia relacionada

1. Crear esquema de evidencia y anotación humana.
2. Etiquetar un piloto balanceado de apoyo, refutación, discusión y no relación.
3. Implementar relevancia, postura, fragmento e independencia.
4. Mantener la evaluación de evidencia separada del score base.
5. Añadir explicaciones por fuente en el detalle.

**Gate:** medir precisión de recuperación y macro-F1 de postura en un test
congelado; revisar manualmente URLs, fragmentos y supuesta independencia.

### Fase 5 — Filtro de feed en servidor

1. Añadir `riskLevels` al repositorio y API antes del conteo/cursor.
2. Activar el valor predeterminado bajo riesgo + no concluyente.
3. Añadir control visible, estado en URL y opción de mostrar todo.
4. Probar combinaciones con fuente, título, fecha y scroll infinito.
5. Registrar el estado del filtro en telemetría si será analizado en la tesis.

**Gate:** conteo, cursor y resultados deben ser correctos para cada combinación;
el usuario siempre puede descubrir que hay contenido oculto y restaurarlo.

### Fase 6 — Calidad de resúmenes y revalidación

1. Construir una muestra estratificada por longitud, fuente y tipo de contenido.
2. Evaluar cobertura de hechos centrales, fidelidad, legibilidad y truncamiento,
   además de métricas automáticas.
3. Comparar resumen actual contra una variante más extensa o jerárquica.
4. Ejecutar pruebas automáticas, revisión de accesibilidad y piloto de 5–8
   personas ajenas a la muestra formal previa.
5. Corregir el lote, congelar la nueva versión y ejecutar de nuevo la lista de
   aceptación.

**Gate:** no iniciar otra muestra formal hasta congelar interfaz, modelos,
políticas, umbrales, instrumento y commits.

## 5. Métricas recomendadas

### Modelo y políticas

- macro-F1, precision/recall por clase y matriz de confusión;
- Brier score y error de calibración (ECE);
- tasa de falsos positivos por fuente y tipo documental;
- cobertura y completitud del contexto de X;
- desempeño con/sin contexto en el mismo conjunto;
- precisión de recuperación, macro-F1 de postura y acuerdo humano;
- porcentaje de evidencia independiente frente a republicaciones de un mismo
  origen.

### Interfaz y comprensión

- SUS y tasa de finalización de tareas;
- comprensión correcta de “resultado no concluyente” y del porcentaje;
- identificación de la diferencia entre fuente oficial y contenido verificado;
- número de contradicciones color/etiqueta: objetivo cero;
- contraste WCAG AA;
- éxito de recuperación de contraseña;
- utilidad y suficiencia percibida del resumen y fuentes.

No usar “me gusta/no me gusta” ni “fue útil” como etiqueta de verdad. Tampoco
interpretar el número de enlaces como exactitud del contenido.

## 6. Pruebas de aceptación añadidas

- Una noticia de El Peruano puede mostrar “Fuente oficial” y a la vez un
  resultado no concluyente, sin contradicción textual.
- El disclaimer institucional es visible y accesible desde teclado/lector.
- Una publicación que cita a otra conserva y presenta la cita utilizada por el
  modelo.
- Una respuesta conserva el padre; un hilo parcial se identifica como parcial.
- Un enlace temáticamente relacionado pero neutral no aparece como respaldo.
- Dos medios que replican la misma nota de agencia no cuentan como dos
  corroboraciones independientes.
- Un resultado refutado y uno con evidencia mixta no comparten la misma etiqueta.
- El filtro predeterminado se aplica antes de paginar y “mostrar todo” recupera
  las noticias de alto riesgo.
- Borde, badge, porcentaje, leyenda y filtros derivan de la misma política.
- Recuperar contraseña no permite enumerar correos y revoca sesiones anteriores.

## 7. Orden de prioridad

1. **P0 metodológico:** semántica única, eliminación de contradicciones,
   disclaimer y congelamiento de evidencia.
2. **P0 funcional:** recuperación de contraseña y filtro server-side correcto.
3. **P1 de exactitud:** auditoría de El Peruano y contexto de X.
4. **P1 de evidencia:** postura e independencia de fuentes relacionadas.
5. **P1 de experiencia:** modo oscuro, onboarding y calidad de resúmenes.
6. **P2 experimental:** fusión calibrada del modelo base con evidencia.

## 8. Cómo defenderlo en la tesis

La tesis debe presentar estos cambios como respuesta trazable a evidencia de
usuarios y a una limitación técnica observada. La afirmación defendible es:

> Kenta separa procedencia institucional, riesgo automático del contenido y
> corroboración externa; comunica incertidumbre y conserva evidencia auditable.

No son defendibles, sin una validación adicional, afirmaciones como “El Peruano
es siempre verdadero”, “varios enlaces prueban una noticia” o “el porcentaje de
Kenta es la probabilidad real de que una noticia sea falsa”.

Cada modificación deberá quedar asociada a: versión, motivación, hipótesis,
prueba, resultado y limitación. Si los datos de usuarios ya pertenecen a la
muestra formal, esta versión debe reportarse como posterior y no mezclarse con
los resultados originales.

## 9. Referencias iniciales para la justificación

- Diario Oficial El Peruano, naturaleza institucional de Editora Perú:
  <https://www.elperuano.pe/noticia/264069-presidencia-de-la-republica-saluda-a-editora-peru-por-su-49-aniversario>
- X API, campos `conversation_id`, `referenced_tweets` y expansiones:
  <https://docs.x.com/x-api/posts/english-language-firehose-stream>
- Roozenbeek et al., efectos de información de credibilidad de fuente y normas
  sociales sobre discernimiento: <https://www.nature.com/articles/s41598-024-57560-7>
- Wadden et al., integración de recuperación, postura, confiabilidad de fuente y
  verificación: <https://arxiv.org/abs/1804.08012>
- Distinción entre credibilidad de la fuente y solidez del contenido:
  <https://www.sciencedirect.com/science/article/pii/S2398534822000183>

