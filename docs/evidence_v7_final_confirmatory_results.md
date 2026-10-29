# Resultados finales de la evaluación confirmatoria v7

Fecha de cierre: 2026-10-28 (America/Lima)

## Trazabilidad

- Protocolo: `evidence-end-to-end-v7-final-confirmatory-v1`.
- Muestra congelada: 24 publicaciones inéditas, 18 web y 6 de X.
- SHA-256: `e3df354495b2a43f87424efa9483e2822709334989e931094359a60085cdb7a5`.
- Modelo: `gemini-3.5-flash-lite`.
- Política evaluada: `evidence-policy-2026-10-27-v6`.
- Recuperación: `retrieval-policy-2026-10-25-v5`.
- Anotación: dos revisores independientes y adjudicación ciega de cuatro
  desacuerdos de postura y un caso de cobertura.
- La ejecución no modificó la base de datos de producción.

## Resultado por criterio prerregistrado

| Criterio | Umbral | Resultado final | Estado |
| --- | ---: | ---: | --- |
| Publicaciones con contenido devuelto | ≥80% | 21/24 (87.5%) | Cumple |
| Precisión de fuentes independientes evaluables | ≥90% | 37/37 (100.0%) | Cumple |
| Cobertura útil entre casos con evidencia | ≥80% | 22/22 (100.0%) | Cumple |
| Exactitud de postura contra gold final | ≥75% | 24/37 (64.9%) | No cumple |
| Vacíos falsos entre conjuntos sin fuentes | ≤20% | 0/3 (0.0%) | Cumple |
| Contexto social correcto en casos de X | ≥80% | 6/6 (100.0%) | Cumple |

La v7 cumple cinco de seis criterios. Como la puerta conjunta exigía cumplir
los seis, el resultado global es `overall_passed=false`.

## Acuerdo y adjudicación

- Evaluabilidad: 37/37 acuerdos.
- Postura: 33/37 acuerdos exactos (89.2%); kappa de Cohen 0.742.
- Cobertura: 23/24 acuerdos exactos (95.8%); kappa de Cohen 0.814.
- Contexto social: 6/6 acuerdos exactos.
- Las cuatro posturas controvertidas fueron adjudicadas como `discusses`.
- C7-007 fue adjudicado como cobertura `partial`, con evidencia relevante no
  recuperada y URL verificable.

## Diagnóstico final

El gold final contiene 24 fuentes `supports` y 13 `discusses`. La matriz de
confusión muestra:

- 22 `supports` correctamente clasificados;
- 2 `supports` clasificados como `discusses`;
- 2 `discusses` correctamente clasificados;
- 11 `discusses` clasificados como `supports`.

El error dominante ya no es el conservadurismo observado en v6. La política
corregida se desplazó demasiado hacia `supports` y deja de reconocer omisiones
materiales que justifican `discusses`. La precisión de recuperación, la
cobertura y el contexto social son fuertes, pero la postura no alcanza el nivel
prerregistrado para sostener una verificación robusta.

## Decisión de cierre

La v7 es la confirmación final planificada. Conforme al prerregistro, no se abre
otra iteración post hoc con esta evidencia. Para la tesis, el resultado debe
presentarse como una limitación final defendible: el sistema recupera evidencia
pertinente y contextualiza correctamente X, pero su clasificación de postura
sobrerrepresenta `supports` frente a `discusses`.

El prototipo puede conservarse como herramienta de apoyo con explicaciones y
revisión humana. No debe afirmarse que la política de postura v6 quedó validada
por la prueba confirmatoria.
