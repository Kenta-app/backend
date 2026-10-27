# Prerregistro de la evaluación confirmatoria integral v6

Fecha de prerregistro: 2026-10-26 (America/Lima)

## Propósito

Esta evaluación medirá, sobre publicaciones nuevas y no utilizadas durante el
desarrollo, el flujo completo de evidencia: construcción de la afirmación,
recuperación, selección, clasificación de postura y suficiencia de cobertura.
La política queda congelada antes de seleccionar y consultar los casos.

## Diseño congelado

- Protocolo: `evidence-end-to-end-v6-confirmatory-v1`.
- Semilla: `20261026`.
- Tamaño: 24 publicaciones.
- Plataformas: 18 publicaciones web y 6 publicaciones de X.
- Contexto de X: al menos 4 de los 6 casos deben contener una cita, respuesta o
  republicación disponible dentro del contexto almacenado.
- Diversidad editorial: al menos tres fuentes web y cuatro fuentes totales;
  ninguna fuente puede aportar más de ocho publicaciones.
- Fuentes oficiales: al menos dos publicaciones de El Peruano o Agencia Andina.
- Riesgo: mínimo seis casos bajos, seis medios y cuatro altos. Los ocho lugares
  restantes pueden distribuirse según la población elegible.
- Unidad de muestreo: una publicación representativa y como máximo una por
  clúster existente.
- Exclusiones: predicciones, afirmaciones o pares afirmación–URL utilizados en
  evaluaciones anteriores; publicaciones con fuentes de justificación ya
  persistidas; contenido web menor de 80 caracteres o social menor de 20.
- La recuperación no debe persistir fuentes en la base de datos.

El muestreo se ejecutará únicamente si todos los requisitos de composición se
cumplen simultáneamente. Si la población disponible no los satisface, se
ampliará la ingesta antes de congelar la muestra; no se relajarán las cuotas
después de observar resultados.

## Criterios de aprobación prerregistrados

La versión aprobará solo si cumple simultáneamente:

1. contenido devuelto en al menos 80% de las 24 publicaciones;
2. precisión de al menos 90% entre fuentes independientes evaluables;
3. cobertura útil (`sufficient` o `partial`) en al menos 80% de los casos
   evaluables por humanos;
4. exactitud de postura de al menos 75% contra consenso o adjudicación final;
5. no más de 20% de vacíos falsos entre conjuntos sin fuentes;
6. interpretación correcta del contexto social en al menos 80% de los seis
   casos de X, incluyendo la identificación de quién afirma qué en quotes y
   respuestas.

Si el denominador de una métrica es cero, se informará el número de eventos y
la métrica quedará como no estimable. No se considerará evidencia de desempeño
por clase si el gold final no contiene ejemplos de esa clase.

## Procedimiento ciego

1. Auditar la disponibilidad sin seleccionar ni consultar casos.
2. Congelar la muestra y registrar su SHA-256.
3. Ejecutar la recuperación de forma reanudable y no persistente.
4. Generar dos libros con orden independiente y sin mostrar la postura del
   sistema.
5. Obtener doble anotación independiente.
6. Calcular acuerdo antes de adjudicar.
7. Adjudicar solo desacuerdos, sin usar la predicción como criterio.
8. Aplicar los seis criterios sin cambiar reglas, prompt ni umbrales.

## Estado de preparación inicial

La auditoría del 26 de octubre encontró 33 candidatos inéditos: todos
correspondían a El Comercio, 26 eran de riesgo bajo y siete de riesgo medio. No
había publicaciones de X, casos de riesgo alto ni fuentes oficiales elegibles.
Por ello la muestra no se congeló. Hacerlo habría incumplido el presente diseño
y producido una prueba confirmatoria sesgada.

## Muestra congelada

Después de ampliar la ingesta web y social, la muestra se congeló antes de la
recuperación con los siguientes controles:

- 24 publicaciones y 24 identificadores únicos;
- 18 publicaciones web y 6 publicaciones de X;
- 5 de los 6 casos sociales con publicación referenciada disponible;
- seis fuentes originales: El Comercio (6), La República (4), Agencia Andina
  (3), El Peruano (3), RPP Noticias (2) y X (6);
- 11 casos de riesgo bajo, 6 medios y 7 altos;
- 6 publicaciones procedentes de fuentes oficiales;
- política de recuperación `retrieval-policy-2026-10-25-v5`;
- política de evaluación `evidence-policy-2026-10-25-v5`;
- modelo de recuperación `gemini-3.5-flash-lite`;
- SHA-256 de la muestra:
  `e4b675d17b94c13db7c0ec91c92ec6db28d7142b52ecba86ebcad921c6f5551b`.

El hash fue verificado y no existía ningún resultado de recuperación al momento
del sello. Desde este punto no se permiten cambios en la muestra, la política,
el prompt ni los umbrales antes de completar la evaluación.

## Comandos

Primero se amplía la población elegible. Este comando puede tardar porque
ejecuta la ingesta y el pipeline; requiere `TWITTER_BEARER_TOKEN` y debe
ejecutarlo el responsable del entorno:

```powershell
.\.venv\Scripts\python.exe scripts\refresh_evidence_v6_candidates.py
```

La corrida desactiva las justificaciones automáticas para no contaminar la
muestra antes del congelamiento. Si una fuente falla, registra el error y
continúa con las demás.

Auditoría rápida:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_evidence_v6_confirmatory.py audit
```

Congelamiento, solo cuando la auditoría indique `ready_to_freeze: true`:

```powershell
.\.venv\Scripts\python.exe scripts\prepare_evidence_v6_confirmatory.py freeze
```

Recuperación posterior, potencialmente lenta y reanudable:

```powershell
.\.venv\Scripts\python.exe scripts\run_evidence_end_to_end_pilot.py run `
  --output-dir output\evidence_confirmatory_v6_2026_10_26
```
