# Protocolo de anotación de evidencia relacionada

Versión: `evidence-annotation-2026-10-21-v1`

## Objetivo

Medir si la postura asignada por Kenta a cada fuente relacionada coincide con
una evaluación humana de la relación entre la fuente y la afirmación central.
Esta evaluación no mide si la noticia original es verdadera ni modifica su
`fakeScore`.

## Diseño elegido

Se utilizarán dos anotadores independientes, archivos ciegos y adjudicación de
desacuerdos. Un solo anotador sería más rápido, pero no permitiría estimar la
fiabilidad del instrumento. Tres anotadores reducirían la dependencia de la
adjudicación, pero aumentan considerablemente el costo para un piloto de tesis.
Dos anotadores más adjudicación ofrecen el mejor equilibrio en esta fase.

El piloto solicita 80 pares, con objetivo de 20 por estrato producido por el
sistema: `supports`, `refutes`, `discusses` y `unrelated`. Los estratos sirven
solo para muestrear; no se muestran a los anotadores ni se consideran etiquetas
verdaderas. Si una clase no tiene 20 candidatos, no se fabrican ni duplican
casos: el manifiesto registra la disponibilidad y el tamaño efectivo.

La unidad de muestreo es una combinación única de afirmación y dominio del
medio. Esto reduce la pseudorreplicación, aunque no demuestra independencia
editorial ni detecta notas sindicadas de una misma agencia.

## Preparación

1. Ejecutar las migraciones y regenerar fuentes con la política vigente.
2. Congelar el código, prompt, modelo y `assessmentVersion`.
3. Generar el lote:

```powershell
.\.venv\Scripts\python.exe scripts\build_evidence_annotation_pilot.py `
  --output-dir output\evidence_annotation_pilot `
  --sample-size 80 `
  --seed 20261021
```

4. Conservar `evidence_model_key.csv` fuera del alcance de los anotadores.
5. Entregar `evidence_annotations_a.csv` y `evidence_annotations_b.csv` por
   separado. No deben conversar sobre los casos durante la anotación.

Antes del lote formal, ambos anotadores resolverán 10 casos de calibración que
no formarán parte de la evaluación. Las discrepancias de interpretación se
resolverán ajustando esta guía antes de congelar el piloto.

## Pregunta de anotación

> Considerando la afirmación central y el contenido de la fuente enlazada,
> ¿qué relación sostiene esa fuente con la misma afirmación?

Se debe abrir la URL y revisar el contenido suficiente. El título o el extracto
generado por Kenta no bastan por sí solos.

### Estado de revisión

- `include`: existe contexto suficiente para asignar postura.
- `exclude_unavailable`: la fuente no se puede consultar, fue eliminada o exige
  acceso no disponible.
- `exclude_insufficient_context`: la página abre, pero no contiene información
  suficiente para evaluar la afirmación.

Las filas excluidas deben dejar vacía `human_stance`.

### Etiquetas de postura

- `supports`: la fuente afirma explícitamente la misma proposición o presenta
  evidencia que la confirma directamente.
- `refutes`: la fuente niega explícitamente la misma proposición o presenta
  evidencia incompatible con ella.
- `discusses`: trata el mismo asunto, pero no confirma ni contradice la
  proposición completa; también se usa ante ambigüedad.
- `unrelated`: la fuente no trata la misma afirmación o la coincidencia es solo
  superficial.

### Regla operativa para `supports` y `discusses`

Antes de etiquetar, descomponga la afirmación en sus elementos materiales:
actor, acción o hecho, objeto, tiempo, lugar y cantidad cuando correspondan.

- Use `supports` solo si la fuente confirma explícitamente todos los elementos
  necesarios para sostener la proposición completa.
- Use `discusses` si coincide el tema, actor o evento, pero falta, cambia o se
  matiza al menos un elemento material; si la fuente solo presenta antecedentes,
  reacciones o el estado de un proceso; o si repite la afirmación sin confirmarla
  de manera independiente.
- Una confirmación parcial no se divide ni se promedia: la postura de la fuente
  frente a la proposición completa es `discusses`.
- Ante duda entre `supports` y `discusses`, use `discusses` y explique qué
  elemento material no quedó confirmado.

Ejemplo: si la afirmación dice que una reunión ocurrirá entre dos personas para
iniciar una transferencia, una fuente que solo confirma que existen
coordinaciones de transferencia es `discusses`; no confirma la reunión concreta.

No se debe inferir respaldo por reputación del medio, cantidad de enlaces,
coincidencia temática o ausencia de una refutación. Una fuente oficial solo es
primaria para lo que la institución publicó, dispuso o declaró.

### Aclaraciones incorporadas tras el desafío dirigido

La política operativa `evidence-policy-2026-10-22-v3` añade tres reglas surgidas
de patrones repetidos en la muestra de desarrollo:

- En afirmaciones compuestas, cada hecho unido es material. Si la evidencia solo
  confirma una parte, la etiqueta es `discusses`, no `supports`.
- Una fuente que indica que una acusación carece de pruebas puede `refutes` la
  proposición de que esa acusación fue demostrada. Una negación general también
  puede refutar una variante específica comprendida por ella.
- Compartir una persona, organización o tema amplio no basta para `discusses`.
  Si la fuente no aborda el hecho o predicado central, es `unrelated`.

Estas aclaraciones se derivaron de una muestra de desarrollo; por ello deben
congelarse antes de la evaluación confirmatoria independiente.

### Revisión de postura v4

La política `evidence-policy-2026-10-25-v4` separa dos tareas que antes se
resolvían en una sola llamada: primero recupera y filtra las fuentes y luego
revisa la postura usando únicamente la afirmación, el título, el extracto y la
URL ya seleccionados. La segunda etapa no puede buscar ni sustituir fuentes.
Si su respuesta es incompleta o inválida, se conservan las etiquetas obtenidas
durante la recuperación.

La revisión aplica además estas reglas generales:

- una consecuencia posterior no prueba por sí sola el antecedente; este debe
  aparecer expresamente en la fuente;
- dos estados sucesivos de un procedimiento no se contradicen solo por ocurrir
  en momentos diferentes;
- una fecha, día, cifra, lugar o canal documental exactos son materiales cuando
  la afirmación los destaca;
- el título y el extracto se evalúan juntos; una salvedad de alcance expresa no
  puede ignorarse porque el extracto describa una regla general;
- que un dominio esté autorizado para recuperación significa que es una fuente
  identificable, no que su contenido reciba credibilidad automática.

Estas reglas se ajustaron con el conjunto adjudicado ya abierto. Sus resultados
son evidencia de regresión de desarrollo y no reemplazan una evaluación ciega.

## Confianza y notas

`confidence` puede ser `high`, `medium` o `low`. No entra en la métrica
principal, pero permite revisar casos ambiguos. Las notas deben señalar el
fragmento o la razón de la decisión sin copiar textos extensos.

## Adjudicación

Después de terminar ambas planillas se ejecuta el evaluador. Este produce
`adjudication_needed.csv`. Una tercera revisión conjunta completa
`final_status`, `final_stance` y `rationale` únicamente para los desacuerdos.
Después se vuelve a ejecutar el evaluador indicando `--adjudication`.

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_evidence_annotations.py `
  --model-key output\evidence_annotation_pilot\evidence_model_key.csv `
  --annotator-a output\evidence_annotation_pilot\evidence_annotations_a.csv `
  --annotator-b output\evidence_annotation_pilot\evidence_annotations_b.csv `
  --adjudication output\evidence_annotation_results\adjudication_needed.csv `
  --output-dir output\evidence_annotation_results
```

## Métricas

El informe calcula:

- acuerdo exacto y kappa de Cohen entre anotadores;
- accuracy del sistema;
- macro-F1 fijo sobre las cuatro clases;
- precision, recall y F1 por clase;
- matriz de confusión;
- intervalo percentil bootstrap del 95 % para macro-F1.

Este primer lote es diagnóstico. No se fijará un umbral de aprobación después
de observar sus resultados. El umbral para una evaluación confirmatoria debe
prerregistrarse usando el piloto para estimar dificultad y tamaño muestral.

## Reglas de reporte

- Informar el número solicitado, disponible, incluido, excluido y adjudicado.
- No presentar el muestreo balanceado como prevalencia natural de las clases.
- Reportar intervalos y métricas por clase, no solo accuracy.
- Mantener el conjunto humano separado del entrenamiento y del ajuste del
  prompt evaluado.
- Declarar que dominio distinto no equivale todavía a independencia editorial.
