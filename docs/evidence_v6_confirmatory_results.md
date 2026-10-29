# Resultados finales de la evaluación confirmatoria integral v6

Fecha de cierre: 2026-10-27 (America/Lima)

## Trazabilidad

- Protocolo: `evidence-end-to-end-v6-confirmatory-v1`.
- Muestra congelada: 24 publicaciones, 18 web y 6 de X.
- SHA-256: `e4b675d17b94c13db7c0ec91c92ec6db28d7142b52ecba86ebcad921c6f5551b`.
- Modelo evaluado: `gemini-3.5-flash-lite`.
- Política evaluada: `evidence-policy-2026-10-25-v5`.
- Recuperación evaluada: `retrieval-policy-2026-10-25-v5`.
- Anotación: dos revisores independientes y adjudicación ciega de siete
  desacuerdos de postura y dos campos de cobertura.

Los resultados de esta corrida permanecen asociados a la política v5. La
corrección posterior de postura se registra como v6 y no modifica ni reetiqueta
retroactivamente esta evaluación.

## Resultado por criterio prerregistrado

| Criterio | Umbral | Resultado final | Estado |
| --- | ---: | ---: | --- |
| Publicaciones con contenido devuelto | ≥80% | 23/24 (95.8%) | Cumple |
| Precisión de fuentes independientes evaluables | ≥90% | 39/41 (95.1%) | Cumple |
| Cobertura útil entre casos evaluables | ≥80% | 22/24 (91.7%) | Cumple |
| Exactitud de postura contra gold final | ≥75% | 25/41 (61.0%) | No cumple |
| Vacíos falsos entre conjuntos sin fuentes | ≤20% | 0/1 (0.0%) | Cumple |
| Contexto social correcto en casos de X | ≥80% | 6/6 (100.0%) | Cumple |

La versión evaluada no supera la puerta conjunta porque los seis criterios
debían cumplirse simultáneamente.

## Acuerdo antes de adjudicar

- Evaluabilidad de fuentes: 41/41 acuerdos.
- Postura: 34/41 acuerdos exactos (82.9%); kappa de Cohen 0.649.
- Cobertura: 23/24 acuerdos exactos (95.8%); kappa de Cohen 0.784.
- Contexto social: 6/6 acuerdos exactos.

## Diagnóstico de postura

El gold final contiene 26 `supports`, 10 `discusses`, 3 `refutes` y 2
`unrelated`. El sistema acertó 25 de 41 fuentes. Los errores se distribuyen así:

- 10 `supports` finales clasificados como `discusses`;
- 3 `discusses` finales clasificados como `supports`;
- 2 `unrelated` finales clasificados como `discusses`;
- 1 `supports` final clasificado como `refutes`.

El error dominante es una aplicación excesivamente conservadora de
`discusses`: el sistema trata la falta de detalles accesorios como si fuera la
omisión de un elemento material. En publicaciones sociales también confundió
fuentes que confirmaban el post respondido con evidencia sobre la afirmación
nueva escrita por el autor del reply.

## Decisión y siguiente validación

Se conserva la v6 como resultado confirmatorio fallido y auditable; no se
cambian sus umbrales ni su gold. La política posterior
`evidence-policy-2026-10-27-v6` ajusta únicamente la revisión de postura:

1. identifica la proposición mínima verificable;
2. acepta paráfrasis del mismo núcleo actor–acción–objeto como `supports`;
3. exige que una omisión sea material para usar `discusses`;
4. trata como `unrelated` una fuente que solo confirma el contenido padre de un
   reply o quote y no la afirmación nueva del autor.

La política corregida requiere una nueva muestra inédita y congelada. La v6 no
se reutilizará para afirmar desempeño confirmatorio de la corrección.
