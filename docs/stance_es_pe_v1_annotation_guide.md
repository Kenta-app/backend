# Guía de anotación de Kenta Stance Perú v1

## 1. Objetivo y unidad de análisis

La tarea asigna una relación de *stance* a cada par formado por un **claim** y
un **artículo** peruano. La pregunta es: **¿qué posición adopta el artículo
respecto de la proposición exacta del claim?** No se evalúa si el claim es
verdadero en el mundo ni si la fuente es confiable.

Las etiquetas válidas son `agree`, `disagree`, `discuss` y `unrelated`.
`exclude` se usa solo durante la adjudicación para retirar un caso defectuoso;
no es una quinta clase del modelo.

## 2. Reglas de trabajo

1. Cada anotador recibe una copia ciega y trabaja sin ver la etiqueta del otro,
   la predicción del modelo, el modo de construcción del par ni una etiqueta
   sugerida.
2. Se lee primero el claim y luego el artículo completo. El título y la URL
   ayudan a recuperar contexto, pero la decisión se sustenta en el texto del
   artículo.
3. Se etiqueta la proposición completa: actor, acción, objeto, tiempo, lugar,
   cantidad, modalidad y atribución.
4. Si falta información para decidir, se registra una nota breve. No se
   completa el contenido con conocimiento externo.
5. Solo la persona adjudicadora ve ambas etiquetas. Todo desacuerdo debe quedar
   resuelto y justificado antes de crear los conjuntos de entrenamiento,
   validación o prueba.

## 3. Definiciones operacionales

### `agree`

El artículo afirma la misma proposición, la respalda con evidencia o la
presenta como establecida. Deben coincidir los componentes materiales del
claim. Una diferencia menor de redacción no cambia la etiqueta.

Ejemplo: claim «La entidad abrió una investigación»; artículo «La entidad
inició diligencias preliminares por el caso».

### `disagree`

El artículo niega, refuta o aporta evidencia incompatible con la proposición.
La contradicción debe recaer sobre un componente material, no sobre un detalle
periférico.

Ejemplo: claim «Todas las mesas quedaron sin instalar»; artículo «La autoridad
confirmó la instalación del 100 % de las mesas».

### `discuss`

El artículo trata de forma sustantiva la misma proposición, pero no la confirma
ni la refuta con claridad. Incluye investigaciones en curso, acusaciones
atribuidas, versiones contrapuestas sin resolución y evidencia insuficiente.

Ejemplo: claim «El funcionario cometió el delito»; artículo «La fiscalía abrió
una investigación por la presunta comisión del delito».

### `unrelated`

El artículo no aborda la proposición de manera sustantiva. Compartir una
persona, institución o tema general no basta.

Ejemplo: claim sobre fraude electoral; artículo sobre el presupuesto anual de
la misma entidad electoral sin referencia al fraude.

## 4. Árbol de decisión

1. ¿El artículo trata la misma proposición o una paráfrasis reconocible?
   - No: `unrelated`.
   - Sí: continuar.
2. ¿El artículo la sostiene o aporta evidencia compatible suficiente?
   - Sí: `agree`.
   - No: continuar.
3. ¿El artículo la niega o aporta evidencia incompatible suficiente?
   - Sí: `disagree`.
   - No: `discuss`.

## 5. Casos difíciles

### Atribución y voz de la fuente

Una cita no convierte automáticamente el claim en `agree`. Si el artículo solo
informa que alguien hizo una acusación y no la adopta ni la verifica, corresponde
`discuss`. Si el claim es precisamente «X afirmó Y» y el artículo confirma que X
lo afirmó, corresponde `agree`, aunque Y no haya sido probado.

### Investigación, denuncia y presunción

«Fue denunciado», «es investigado» y «habría ocurrido» no equivalen a «cometió
el hecho». Para un claim categórico de culpabilidad suelen ser `discuss`, salvo
que el artículo lo niegue o confirme explícitamente.

### Negación, rectificación y contraste

La negación directa de la proposición es `disagree`. Si el artículo presenta
una negación y una acusación sin resolver cuál está respaldada, es `discuss`.
Una rectificación explícita prevalece sobre una afirmación anterior cuando el
artículo deja clara la conclusión vigente.

### Alcance parcial

Si el claim contiene varias proposiciones unidas, `agree` requiere respaldo de
todas las partes materiales. Si el artículo confirma una parte y deja otra sin
resolver, corresponde `discuss`. Si refuta una parte indispensable, corresponde
`disagree`.

### Cantidades, fechas y ámbito

Una diferencia material de cantidad, fecha, lugar o población puede producir
`disagree`. Si el artículo no permite establecer si la diferencia es material,
se usa `discuss` y se documenta la duda.

### Opiniones y lenguaje valorativo

Para claims valorativos, se identifica si el artículo adopta, rechaza o solo
atribuye esa valoración. Compartir el tema sin adoptar la valoración es
`discuss`, no `agree`.

### Artículos defectuosos

En adjudicación se usa `exclude` cuando el artículo está vacío, truncado,
duplicado por error, en un idioma no previsto, no corresponde a la URL o el
claim es ininteligible. La nota debe indicar el defecto concreto.
Que el artículo sea legible pero no aborde el claim corresponde a `unrelated`,
no a `exclude`.

### Evidencia y contenido incrustado

Para `agree`, `disagree` o `discuss`, la evidencia debe ser un fragmento literal
del cuerpo del artículo entregado, suficientemente corto para identificar el
pasaje decisivo. Si se omite texto intermedio, se debe citar un tramo continuo
en vez de construir una cita con puntos suspensivos. Para `unrelated`, se escribe
`SIN EVIDENCIA PERTINENTE` y se explica brevemente qué proposición falta.

Los bloques «lea también», avances de otras noticias, pies promocionales y
publicaciones incrustadas no constituyen por sí solos apoyo, refutación o
discusión sustantiva del artículo. Si el scraping los mezcla con el cuerpo,
marque `review`; en adjudicación se corrige el texto o se excluye el par si no
puede recuperarse el artículo correcto.

### Claim y refutación

Una palabra como «niega», «rechaza» o «desmiente» no garantiza `disagree`.
Primero se compara la proposición exacta negada con la del claim, incluida su
atribución. Un artículo que dice «X negó Y» puede ser `agree` respecto de
«X negó Y», `discuss` respecto de «Y ocurrió» si solo presenta versiones, o
`disagree` respecto de «Y ocurrió» cuando adopta una refutación sustentada.
No se construye un claim falso invirtiendo automáticamente una negación.

## 6. Campos que completa cada anotador

- `annotator_id`: código acordado, no el nombre completo.
- `label`: una de las cuatro etiquetas.
- `evidence`: fragmento o descripción breve del pasaje decisivo, sin copiar
  párrafos extensos.
- `confidence`: `alta`, `media` o `baja`.
- `notes`: explicación obligatoria cuando la confianza es baja.

## 7. Piloto, acuerdo y adjudicación

La primera calibración de 80 pares usó 20 candidatos por estrategia de
construcción: título del mismo artículo, posible refutación, claim reportado y
negativo difícil. La estrategia no es una etiqueta sugerida: la distribución
real de clases solo se conoce tras la anotación. Se calcula
acuerdo observado, matriz entre anotadores y
Cohen's kappa. La meta previa es kappa mayor o igual a 0.70. Si no se alcanza,
se revisa esta guía, se discuten ejemplos abstractos y se anota un nuevo piloto;
no se cambian etiquetas para elevar artificialmente el acuerdo.

La calibración 01 obtuvo κ = 0,7118 pero ningún anotador utilizó `disagree`.
Por ello, la siguiente ola no reutiliza la recuperación automática de
«refutaciones». Cada candidato de ese tipo requiere un claim documentado con
URL y cita de origen, un pasaje contradictorio literal del artículo de destino,
un código de revisor y una justificación privada. Esa revisión controla la
selección de candidatos, no fija la etiqueta para los anotadores.

En la adjudicación se conserva la etiqueta original de cada anotador, se registra
la etiqueta final y una justificación. Los casos excluidos también permanecen en
el maestro con su motivo.

## 8. Separación y prevención de fuga

Los pares del mismo evento, familia de claim o artículo deben compartir
`group_id` y quedar en un solo *split*. El test final se congela antes del
entrenamiento, no se usa para seleccionar épocas, umbrales ni hiperparámetros y
debe proceder de una recolección distinta del piloto histórico de 122 pares.

## 9. Control previo al cierre

- Las cuatro clases están presentes en cada *split*.
- No hay `group_id` compartidos entre entrenamiento, validación y test.
- Cada par incluido tiene dos etiquetas independientes o una adjudicación
  documentada ante desacuerdo.
- El test final tiene al menos 40 ejemplos por clase (160 en total).
- Se publican distribución, acuerdo, exclusiones, fuentes, temas, fechas y
  huellas SHA-256 de los archivos usados.
