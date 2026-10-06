# Protocolo longitudinal mínimo de validación con usuarios — Kenta

## 1. Propósito y alcance

El estudio evalúa la versión desplegada de Kenta con estudiantes universitarios
adultos de Lima Metropolitana. Busca determinar si el prototipo es usable, si su
análisis se percibe como útil para comprender noticias políticas y qué funciones
son utilizadas durante un periodo breve de uso real.

El diseño **no** pretende demostrar que Kenta aumenta causalmente la comprensión,
que sus predicciones son correctas porque los usuarios las valoran positivamente
ni que cambia la conducta política a largo plazo. Tampoco utiliza las reacciones
de los participantes como etiquetas de verdad para reentrenar modelos.

## 2. Preguntas y criterios predefinidos

1. ¿Qué nivel de usabilidad percibida alcanza Kenta mediante la escala SUS?
2. ¿En qué medida los participantes consideran útil y comprensible el análisis
   completo de Kenta?
3. ¿Cómo utilizan durante el estudio el feed, resúmenes, señales del modelo,
   fuentes relacionadas, enlaces originales, guardados y reacciones?
4. ¿Qué dificultades, riesgos de interpretación y mejoras reportan?

Antes del reclutamiento se registran estos criterios orientativos:

- SUS se reportará con media, mediana, desviación o rango intercuartílico e
  intervalo de confianza al 95 %. El valor 68 se usará solamente como referencia
  descriptiva habitual, no como garantía universal de calidad.
- La utilidad percibida global se resumirá en escala de 1 a 5 y como proporción
  de respuestas 4–5.
- El uso de funciones se describirá mediante participantes únicos, sesiones,
  tiempo visible, lecturas, aperturas, clics originales, clics relacionados,
  guardados y reacciones.

## 3. Diseño

- **Tipo:** estudio longitudinal breve, prospectivo, observacional y de métodos
  mixtos, con telemetría, cuestionario estandarizado y preguntas abiertas.
- **Duración individual:** 72 horas de uso; la encuesta final se completa entre
  las 72 y 96 horas posteriores al registro.
- **Población objetivo:** estudiantes universitarios de Lima Metropolitana de
  18 años o más.
- **Muestreo:** por conveniencia. Los resultados describen a la muestra y no se
  generalizan automáticamente a toda la población peruana.
- **Piloto:** 3–5 personas, excluidas de la muestra formal.
- **Muestra formal prevista:** mínimo 30 participantes con protocolo completo.
  El número final y la reserva por abandono deben aprobarse con el asesor antes
  de iniciar; no se reajustan después de observar resultados.
- **Versión:** backend, frontend, modelos, umbrales y cuestionario se congelan al
  iniciar la recolección formal.

No se construirá una condición adicional de lectura convencional en esta etapa.
Por ello, el paper presentará evidencia de usabilidad, utilidad percibida y uso,
no una comparación causal contra portales periodísticos u otro sistema.

## 4. Secuencia de participación

### Antes del registro

1. El investigador entrega información del estudio y un código seudonimizado.
2. La persona confirma que tiene 18 años o más y acepta voluntariamente.
3. El consentimiento de investigación se recoge fuera de los términos de uso de
   la aplicación y antes de crear la cuenta.

### Día 0

1. Crear y verificar una cuenta de Kenta.
2. Decidir voluntariamente si se desea recibir el único recordatorio por correo.
3. Completar estas tareas de familiarización:
   - recorrer el feed y aplicar al menos un filtro;
   - abrir al menos tres noticias;
   - leer sus resúmenes y señales;
   - abrir al menos una fuente relacionada y una noticia original;
   - guardar al menos una noticia;
   - valorar la utilidad de al menos dos análisis.
4. Comunicar cualquier error al investigador sin incluir contraseñas.

### Días 1–3

- Utilizar Kenta libremente cuando se desee. Las instrucciones no exigen una
  cantidad artificial de sesiones adicionales.
- Quien aceptó el recordatorio recibe un solo correo alrededor de las 48 horas.
- El recordatorio invita a continuar usando la plataforma, pero no condiciona
  la participación ni reemplaza el consentimiento.

### Entre las 72 y 96 horas

1. Completar SUS y las preguntas de utilidad, comprensión y confianza.
2. Responder las preguntas abiertas.
3. Registrar incidentes y confirmar si se completaron las tareas iniciales.

## 5. Variables y fuentes de evidencia

### Resultado primario

- Puntaje SUS total (0–100) por participante.

### Resultados secundarios

- Utilidad percibida global y por función (Likert 1–5).
- Comprensión de que el riesgo de desinformación es una señal probabilística y
  no un veredicto.
- Intención declarada de volver a usar la plataforma.
- Proporción actual de análisis marcados como útiles/no útiles.
- Sesiones, tiempo visible, lecturas, detalle, fuentes originales y relacionadas,
  guardados y retorno en más de un día.
- Temas cualitativos de respuestas abiertas e incidencias.

La telemetría describe conducta dentro de la aplicación; no demuestra por sí
sola comprensión, confianza ni exactitud del modelo. La reacción útil/no útil
evalúa el análisis completo y no se trata como etiqueta supervisada.

## 6. Inclusión y exclusión

Se incluye a quien:

- cumple el criterio de edad y población;
- acepta el consentimiento;
- crea y verifica una cuenta;
- completa la familiarización y la encuesta final.

Se excluyen del análisis formal:

- cuentas del equipo, administración y pruebas técnicas;
- participantes del piloto;
- duplicados confirmados;
- quien retire su consentimiento;
- registros sin exposición suficiente para responder SUS o sin encuesta final.

La baja frecuencia de uso posterior a la familiarización no se elimina: es un
resultado del estudio. Toda exclusión se decide antes de analizar resultados y
se reporta con su motivo.

## 7. Privacidad y manejo de datos

- La cuenta requiere correo, nombre de usuario, fecha de nacimiento y género o
  la opción `Prefiero no responder`, según la política publicada.
- El recordatorio es opcional y su consentimiento queda registrado.
- La contraseña se conserva únicamente como hash y nunca es accesible al equipo.
- El conjunto de análisis usa el código `P-####`; no exporta correo, contraseña
  ni fecha de nacimiento exacta.
- La edad se transforma a rangos antes del análisis. Categorías demográficas con
  muy pocos casos se agrupan o no se publican para reducir reidentificación.
- Consentimientos y tabla de correspondencia se guardan separados de respuestas
  y telemetría exportada.
- Debe completarse el correo del investigador, plazo de conservación, mecanismo
  de retiro y responsables de acceso antes de reclutar.

## 8. Plan de análisis

1. Aplicar criterios de inclusión/exclusión y presentar diagrama de participantes.
2. Calcular SUS conforme a su regla estándar y reportar distribución e intervalo
   de confianza al 95 %, preferentemente mediante bootstrap de participantes.
3. Resumir ítems Likert con mediana, rango intercuartílico y distribución; la
   media puede mostrarse solo como complemento.
4. Describir telemetría por participante y de forma agregada. No interpretar
   múltiples eventos de una persona como observaciones independientes.
5. Explorar asociaciones entre SUS, utilidad declarada y uso mediante análisis
   por participante; cualquier prueba inferencial adicional se marca exploratoria.
6. Codificar respuestas abiertas en temas, con ejemplos anonimizados y sin
   presentar texto que identifique a participantes.
7. Reportar abandonos, datos faltantes, incidencias y cualquier desviación del
   protocolo.

## 9. Alcance de stance

Las etiquetas automáticas de stance permanecen fuera de la interfaz pública y
no intervienen en el riesgo mostrado (`STANCE_PUBLIC_ENABLED=false`). La
validación no mide stance. El paper reportará su corpus y evaluación técnica,
así como la decisión de no desplegarlo por no alcanzar el criterio operacional.

## 10. Congelamiento y control de calidad

Antes del piloto y de la muestra formal se debe:

1. aprobar todos los casos P0 de `docs/final_acceptance_checklist.md`;
2. registrar fecha/hora, commits, configuración, respaldo y periodo del estudio;
3. declarar como prueba técnica toda actividad previa, incluidas las cuentas 4
   y 12;
4. revisar el protocolo y el instrumento con el asesor;
5. no modificar interfaz, modelos, umbrales ni preguntas durante la recolección,
   salvo un incidente P0 documentado.
