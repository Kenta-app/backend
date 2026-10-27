# Evaluación confirmatoria de la política de evidencia v3

Fecha de ejecución: 2026-10-22 (America/Lima)

## Diseño

La política `evidence-policy-2026-10-22-v3` se congeló antes de abrir el gold
externo Challenge 05. El conjunto había sido congelado el 2026-09-29 y cuenta
con doble anotación independiente, adjudicación de dos desacuerdos y un acuerdo
previo de 97.5% (`κ = 0.967`).

Se verificó el hash SHA-256 del gold y se comprobó que sus 80 pares no presentan
coincidencias exactas ni coincidencias por afirmación con las muestras usadas
para desarrollar la política de evidencia. La muestra contiene 20 grupos de
fuentes y una distribución controlada cercana al balance:

- 20 `supports`;
- 21 `refutes`;
- 19 `discusses`;
- 20 `unrelated`.

La prueba fue de pares fijos: el modelo recibió la afirmación, medio, título,
URL y evidencia ya seleccionada. Por tanto, evalúa la clasificación semántica
de postura, no la recuperación de fuentes en Internet.

## Resultados

- Exactitud: 96.25%.
- Macro-F1 de cuatro clases: 96.20%.
- IC percentil bootstrap 95% de exactitud, remuestreando los 20 grupos:
  92.5%–100%.
- IC percentil bootstrap 95% de macro-F1: 92.12%–100%.
- F1 `supports`: 100%.
- F1 `refutes`: 95.45%.
- F1 `discusses`: 91.89%.
- F1 `unrelated`: 97.44%.

Se observaron tres errores: dos casos `discusses` clasificados como `refutes` y
un caso `unrelated` clasificado como `discusses`. No se modificará la política
con base en estos errores, para preservar el carácter confirmatorio del ensayo.

## Interpretación y límites

El resultado constituye evidencia confirmatoria independiente del componente
de clasificación semántica por pares. La composición controlada no estima la
prevalencia natural de las clases. Además, no se prerregistró un umbral de
aprobación específico para esta evaluación; las métricas deben reportarse de
forma descriptiva con sus intervalos.

La validación pendiente para el sistema completo es una prueba integral que
incluya búsqueda, selección y clasificación de fuentes, idealmente sobre
publicaciones nuevas y sin reutilizar este gold para ajustar prompts, umbrales
o reglas.
