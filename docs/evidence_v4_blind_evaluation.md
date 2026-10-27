# Evaluación ciega integral de evidencia v4

## Estado y propósito

Este protocolo se registra antes de ejecutar la recuperación con la política
v4. Su objetivo es estimar el desempeño de la versión corregida sobre casos que
no fueron usados para desarrollar las reglas. La regresión abierta de 26/29 se
conserva como diagnóstico y no se presentará como resultado confirmatorio.

## Configuración congelada

- Protocolo: `evidence-end-to-end-v4-blind-v1`.
- Semilla: `20261025`.
- Política de postura: `evidence-policy-2026-10-25-v4`.
- Política de recuperación: `retrieval-policy-2026-10-25-v2`.
- Unidad: una publicación representativa, como máximo una por clúster.
- Tamaño: 20 publicaciones web nuevas.
- SHA-256 de la muestra congelada:
  `90364164608ffd8c9eac6ea710f4e66cd373dec7a0998deba715a785a4f37904`.
- Cuotas de riesgo: 8 bajas, 8 medias y 4 altas.
- Mínimo por fuente todavía disponible: las 3 publicaciones elegibles de RPP
  Noticias; las posiciones restantes se seleccionan dentro de cada banda.
- Exclusiones: fuentes de justificación ya persistidas, contenido menor de 80
  caracteres y todo `prediction_id` presente en pilotos, claves o muestras
  integrales anteriores.
- La recuperación no persiste resultados en la base de producción.

La composición refleja la población fresca disponible después de las rondas
anteriores. No estima la prevalencia natural del feed y no debe compararse como
si fuera una muestra aleatoria simple.

## Criterios de aprobación prerregistrados

La versión v4 aprobará la prueba integral solo si cumple simultáneamente:

1. recuperación en al menos 16 de 20 publicaciones;
2. precisión de fuentes de al menos 90% entre URLs evaluables;
3. cobertura útil (`sufficient` o `partial`) en al menos 80% de los casos donde
   los anotadores determinen que existe evidencia;
4. exactitud de postura de al menos 75% contra consenso o adjudicación final;
5. no más de 20% de vacíos falsos entre resultados sin fuentes.

No se cambiarán estos umbrales después de ver la salida. Si una métrica no puede
calcularse por falta de casos evaluables, se reportará como no concluyente, no
como aprobada.

## Procedimiento ciego

1. Congelar y sellar la muestra antes de consultar Gemini.
2. Ejecutar la recuperación sin abrir ni editar la muestra congelada.
3. Generar dos libros con orden independiente y sin mostrar `model_stance`.
4. Cada anotador completa su libro sin comunicarse con el otro.
5. Calcular acuerdo previo antes de adjudicar.
6. Adjudicar solo los desacuerdos, sin usar la etiqueta del sistema como criterio.
7. Aplicar los cinco umbrales exactamente como fueron registrados.

La evaluación cubre el flujo web. El flujo de X requiere una muestra social
independiente con citas, respuestas e hilo disponibles.

## Ejecución

La muestra se congela localmente con:

```powershell
.\.venv\Scripts\python.exe scripts\run_evidence_end_to_end_pilot.py freeze `
  --output-dir output\evidence_end_to_end_v4_blind_2026_10_25 `
  --seed 20261025 `
  --protocol evidence-end-to-end-v4-blind-v1 `
  --sampling-design v4-blind
```

La corrida contra el modelo puede tardar y debe ejecutarla el responsable:

```powershell
.\.venv\Scripts\python.exe scripts\run_evidence_end_to_end_pilot.py run `
  --output-dir output\evidence_end_to_end_v4_blind_2026_10_25
```

El comando es reanudable: si se interrumpe, conserva cada caso terminado y al
volver a ejecutarlo omite los identificadores ya presentes en `retrieval_run.jsonl`.

## Registro de ejecución previo a la anotación

La recuperación terminó el 25 de octubre de 2026 (hora de Lima) sin errores
operativos. Procesó los 20 casos congelados, devolvió 24 pares de evidencia para
14 publicaciones y dejó 6 publicaciones sin fuentes. La tabla de fuentes de
justificación permaneció en 69 filas antes y después de la prueba.

Por tanto, la recuperación observada fue 14/20 (70,0%) y no alcanza el primer
umbral prerregistrado de 16/20. Esta conclusión no depende de las etiquetas
humanas. La anotación debe continuar para medir precisión, cobertura, postura y
vacíos falsos, y para caracterizar los seis casos sin resultados.

## Resultado final adjudicado

Los dos anotadores evaluaron 24 pares afirmación–fuente y la cobertura de las 20
publicaciones. Antes de adjudicar, el acuerdo exacto fue 91,7% para
evaluabilidad, 86,4% para postura entre pares que ambos consideraron evaluables
y 80,0% para cobertura. Se adjudicaron cinco desacuerdos de fuente y cuatro de
cobertura, sin mostrar la etiqueta del sistema como criterio de decisión.

La versión v4 cumplió dos de los cinco criterios prerregistrados:

| Criterio | Umbral | Resultado | Decisión |
| --- | ---: | ---: | --- |
| Publicaciones con fuentes | ≥16/20 | 14/20 (70,0%) | No cumple |
| Precisión de fuentes evaluables | ≥90% | 24/24 (100,0%) | Cumple |
| Cobertura útil | ≥80% | 14/20 (70,0%) | No cumple |
| Exactitud de postura | ≥75% | 19/24 (79,2%) | Cumple |
| Vacíos falsos entre resultados sin fuentes | ≤20% | 6/6 (100,0%) | No cumple |

En consecuencia, la prueba integral queda **no aprobada**. Los resultados sí
respaldan dos afirmaciones acotadas: las fuentes recuperadas fueron pertinentes
en esta muestra y el clasificador de postura superó el umbral fijado. No
respaldan afirmar que el módulo de evidencia esté validado de extremo a extremo,
porque la recuperación y la cobertura todavía omiten evidencia material.

La siguiente iteración debe priorizar los seis vacíos falsos y los casos donde
la evidencia recuperada no cubre el elemento central de la publicación. Después
de corregirlos, corresponde repetir el mismo protocolo sobre otra muestra fresca
y ciega. Debido al tamaño muestral y a la ausencia de casos finales `refutes` y
`unrelated`, estos resultados no estiman con precisión el desempeño por clase ni
la prevalencia natural del feed. El flujo de X continúa fuera del alcance de
esta evaluación y requiere una prueba específica con hilo, respuesta y quote.

## Diagnóstico posterior y política v5

La revisión de los seis vacíos falsos separó dos fenómenos que la primera
rúbrica trataba como uno solo. En cinco casos, los anotadores localizaron
únicamente la publicación original. En un caso existía cobertura independiente
que la búsqueda no recuperó. Por ello, la política siguiente distingue:

- `primary_context`: publicación original disponible para comprender el claim;
- `independent_evidence`: cobertura de otro editor elegible para corroborar;
- `distinctPublisherSources`: solo cuenta evidencia independiente.

La publicación original puede evitar un panel vacío, pero no aumenta los
conteos de respaldo o contradicción y no puede convertir el estado agregado en
`supported` o `disputed`. La búsqueda v3 también añadió consultas dirigidas a
Infobae, Gestión y La República.

En la regresión diagnóstica de los seis casos, los seis devolvieron contenido:
cinco como contexto primario no independiente y uno con una fuente independiente
de La República. Los cinco primeros conservaron `insufficient_evidence`, cero
fuentes independientes y cero violaciones de la regla de independencia. Este
resultado es de desarrollo y no reemplaza la decisión final adjudicada de v4.

## Cierre de la regresión de desarrollo v5

La política v5 se ejecutó sobre las mismas 20 publicaciones congeladas. La
recuperación devolvió contenido en 20/20 casos: 17 tuvieron al menos una fuente
independiente y tres quedaron únicamente con `primary_context`. Después de
eliminar una fuente no relacionada, no quedaron violaciones visibles de la
política de independencia.

La revisión humana focalizada incluyó 13 fuentes independientes nuevas y los 16
conjuntos de evidencia modificados. Los registros sin cambios conservaron su
decisión humana v4 únicamente cuando coincidieron exactamente `case_id` y URL.
Antes de adjudicar, el acuerdo de postura en las 13 fuentes nuevas fue 92,3%
(κ=0,831). Se adjudicó un desacuerdo de postura y cinco de cobertura.

La evaluación integrada de desarrollo quedó así:

| Criterio de referencia | Umbral | Resultado v5 | Decisión |
| --- | ---: | ---: | --- |
| Publicaciones con contenido | ≥16/20 | 20/20 (100,0%) | Cumple |
| Precisión de fuentes independientes | ≥90% | 26/26 (100,0%) | Cumple |
| Cobertura útil | ≥80% | 20/20 (100,0%) | Cumple |
| Exactitud de postura | ≥75% | 21/26 (80,8%) | Cumple |
| Vacíos falsos | ≤20% | 0 eventos; no hubo conjuntos vacíos | Cumple |

Los cinco umbrales se cumplen como referencia de desarrollo. Esto demuestra que
las correcciones resolvieron los fallos observados en la muestra, pero **no es
una confirmación independiente**: la misma muestra se utilizó para diagnosticar
y mejorar el sistema. Además, tres casos fueron suficientes solo porque la
publicación primaria permitía evaluar directamente una declaración u opinión;
no se contabilizaron como corroboración independiente.

El siguiente paso defendible es congelar una muestra nueva y repetir la prueba
ciega completa. Esa muestra debe incluir publicaciones de X con quotes,
respuestas e hilos, así como casos `refutes` y `unrelated`, ausentes en el gold
final de esta ronda.

