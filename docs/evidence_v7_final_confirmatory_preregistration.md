# Prerregistro de la evaluación confirmatoria final v7

Fecha de prerregistro: 2026-10-27 (America/Lima)

## Propósito

Esta evaluación es la confirmación final de la política de postura
`evidence-policy-2026-10-27-v6`. La v6 previa cumplió cinco de seis criterios,
pero obtuvo 25/41 (61.0%) en exactitud de postura. Después de cerrar y adjudicar
esa evaluación se modificó únicamente la revisión `supports` / `discusses` y el
manejo de fuentes que solo confirman el post padre de un reply o quote.

La muestra v6 se considera conjunto de desarrollo histórico para esta política
y queda excluida íntegramente. No se reutilizarán sus resultados como evidencia
confirmatoria de la corrección.

## Diseño congelable

- Protocolo: `evidence-end-to-end-v7-final-confirmatory-v1`.
- Semilla: `20261027`.
- Tamaño: 24 publicaciones inéditas.
- Plataformas: 18 publicaciones web y 6 publicaciones de X.
- Contexto de X: al menos 4 de los 6 casos contendrán una cita, respuesta o
  republicación disponible.
- Diversidad editorial: al menos tres fuentes web y cuatro fuentes totales;
  ninguna fuente aportará más de ocho publicaciones.
- Fuentes oficiales: al menos dos publicaciones de El Peruano o Agencia Andina.
- Riesgo: mínimo seis casos bajos, seis medios y cuatro altos.
- Unidad de muestreo: una publicación representativa y como máximo una por
  clúster existente.
- Exclusiones: cualquier prediction_id, claim normalizado o par claim–URL usado
  en evaluaciones anteriores, incluida la v6; publicaciones con fuentes de
  justificación persistidas; contenido web menor de 80 caracteres o social
  menor de 20.
- La recuperación no persistirá fuentes en la base de datos.

## Política y criterios congelados

- Política de evaluación: `evidence-policy-2026-10-27-v6`.
- Política de recuperación: `retrieval-policy-2026-10-25-v5`.
- Modelo: `gemini-3.5-flash-lite`.

La versión aprobará solo si cumple simultáneamente:

1. contenido devuelto en al menos 80% de las 24 publicaciones;
2. precisión de al menos 90% entre fuentes independientes evaluables;
3. cobertura útil (`sufficient` o `partial`) en al menos 80% de los casos
   evaluables por humanos;
4. exactitud de postura de al menos 75% contra consenso o adjudicación final;
5. no más de 20% de vacíos falsos entre conjuntos sin fuentes;
6. interpretación correcta del contexto social en al menos 80% de los seis
   casos de X.

Si el denominador de una métrica es cero, se informará como no estimable. No se
cambiarán prompts, reglas, modelo, muestra ni umbrales después del congelamiento.

## Auditoría previa

La auditoría realizada antes del congelamiento encontró 74 candidatos inéditos
y 74 grupos únicos:

- 60 publicaciones web y 14 sociales;
- 7 casos sociales con contexto referenciado;
- 12 publicaciones de fuentes oficiales;
- 34 casos de riesgo bajo, 18 medios y 22 altos;
- seis fuentes originales disponibles.

Todas las comprobaciones marginales requeridas resultaron verdaderas. La
selección solo se congelará si una combinación conjunta satisface todas las
cuotas simultáneamente.

## Muestra congelada

La selección quedó congelada antes de ejecutar retrieval:

- 24 publicaciones y 24 grupos únicos;
- 18 publicaciones web y 6 de X;
- 5 de los 6 casos sociales con contexto referenciado;
- El Comercio (8), X (6), El Peruano (4), RPP Noticias (3), La República (2)
  y Agencia Andina (1);
- 10 casos de riesgo bajo, 6 medios y 8 altos;
- 5 publicaciones procedentes de fuentes oficiales;
- SHA-256 de la muestra:
  `e3df354495b2a43f87424efa9483e2822709334989e931094359a60085cdb7a5`.

El manifiesto registra `evidence-policy-2026-10-27-v6` y no existía archivo de
resultados de recuperación al momento del sello.

## Regla de cierre

Esta es la última evaluación confirmatoria planificada. Si cumple los seis
criterios se congelará la política para la tesis. Si no los cumple, el resultado
se reportará como limitación final y no se abrirá otra iteración post hoc con la
misma evidencia.
