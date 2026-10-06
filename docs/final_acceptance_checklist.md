# Lista final de aceptación antes de la validación con usuarios

Esta lista se ejecuta una sola vez sobre la versión candidata en producción. Durante
la ejecución no se corrige ni despliega cada defecto por separado: se registra la
evidencia, se agrupan los fallos y, si hace falta, se publica un único lote final.

## 1. Bitácora de la ejecución

- Fecha y hora de inicio (America/Lima): `________________`
- Fecha y hora de cierre: `________________`
- Responsable: `________________`
- Commit backend: `________________`
- Commit frontend: `________________`
- Navegador de escritorio y versión: `________________`
- Navegador/dispositivo móvil y versión: `________________`
- Cuenta participante de prueba: `P-____`
- Cuenta administradora: `P-____` (no forma parte de la muestra)
- Respaldo PostgreSQL: `________________`

Estados permitidos: `PENDIENTE`, `APROBADO`, `FALLÓ`, `NO APLICA`.

- **P0:** bloquea el inicio del estudio.
- **P1:** debe corregirse en el lote final antes de invitar participantes.
- **P2:** mejora no bloqueante; se registra para una versión futura.

Para cada fallo guardar: identificador, prioridad, pasos, resultado observado,
captura o log, navegador/dispositivo y hora.

## 2. Despliegue y disponibilidad

- [ ] **A01 — P0.** `api`, `frontend`, `nginx` y `postgres` aparecen `healthy`.
- [ ] **A02 — P0.** `/`, `/home`, `/login`, `/register`, `/saved` y `/privacy`
  responden sin `5xx`.
- [ ] **A03 — P0.** `/health` informa `databaseReady=true`,
  `classifierReady=true` y `schedulerEnabled=true`.
- [ ] **A04 — P0.** Los commits desplegados coinciden con los registrados en esta
  bitácora.
- [ ] **A05 — P1.** No aparecen `Traceback`, reinicios continuos ni errores nuevos
  en los últimos 200 registros de `api`, `frontend` y `nginx`.

## 3. Cuenta, consentimiento y perfil

- [ ] **B01 — P0.** Se puede registrar una cuenta con un correo nuevo y aceptar
  términos y privacidad.
- [ ] **B02 — P0.** La casilla del recordatorio es opcional, está desmarcada y
  explica que se enviará un único correo a los dos días.
- [ ] **B03 — P0.** Llega el código, se verifica la cuenta y se inicia sesión.
- [ ] **B04 — P1.** Género ofrece `Femenino`, `Masculino`, `Otro` y `Prefiero no
  responder`; las cuatro opciones son aceptadas y se muestran correctamente.
- [ ] **B05 — P0.** `Recuérdame` conserva la sesión después de cerrar y volver a
  abrir el navegador.
- [ ] **B06 — P1.** Con sesión iniciada, `/` dirige al usuario a su experiencia y
  no presenta un CTA que solicite registrarse otra vez.
- [ ] **B07 — P0.** El cambio de contraseña funciona; la contraseña anterior deja
  de autenticar y la nueva sí funciona.
- [ ] **B08 — P0.** Cerrar sesión invalida la sesión y las rutas privadas vuelven
  a solicitar autenticación.

## 4. Feed, navegación y diseño adaptable

- [ ] **C01 — P0.** El feed carga noticias y el desplazamiento infinito agrega
  resultados sin duplicados visibles.
- [ ] **C02 — P1.** Búsqueda, fuente, fecha y filtros combinados devuelven resultados
  coherentes y se pueden limpiar.
- [ ] **C03 — P1.** El cambio cuadrícula/lista funciona en escritorio.
- [ ] **C04 — P1.** En móvil se usa la presentación prevista y no aparece un control
  de cuadrícula sin efecto.
- [ ] **C05 — P0.** En móvil se puede navegar a Noticias, Guardados, Perfil y
  Configuración.
- [ ] **C06 — P1.** No hay desplazamiento horizontal, controles cortados ni texto
  ilegible en anchos móviles habituales.

## 5. Detalle y funciones de una noticia

- [ ] **D01 — P0.** El detalle muestra título, fuente, fecha, contenido o resumen y
  enlace original sin error de cliente.
- [ ] **D02 — P0.** Se muestra el riesgo público de desinformación con sus umbrales;
  no se presenta como veredicto absoluto.
- [ ] **D03 — P0.** Stance no aparece públicamente ni interviene en la interfaz
  (`STANCE_PUBLIC_ENABLED=false`).
- [ ] **D04 — P1.** Las fuentes relacionadas abren URLs válidas, no duplican la URL
  original y no pertenecen al mismo medio de la noticia principal.
- [ ] **D05 — P1.** Una noticia sin fuentes relacionadas presenta un estado vacío
  comprensible y no rompe la página.
- [ ] **D06 — P0.** Una publicación de X marcada oculta inicialmente el texto,
  presenta el aviso y permite revelarlo voluntariamente.
- [ ] **D07 — P0.** Guardar y quitar de Guardados funciona; `/saved` carga tanto con
  cero como con una o más noticias.
- [ ] **D08 — P0.** La pregunta de reacción indica que se evalúa el análisis completo
  de Kenta. `Sí, fue útil`, `No fue útil`, cambio y eliminación persisten tras
  recargar.
- [ ] **D09 — P1.** La reacción se interpreta como utilidad percibida y no como
  etiqueta correcta/incorrecta del modelo.

## 6. Telemetría y panel administrativo

- [ ] **E01 — P0.** Una cuenta participante genera apertura de detalle, lectura,
  clic original, clic relacionado, reacción, favorito y sesión.
- [ ] **E02 — P0.** Después del ciclo de envío, la cola local queda vacía y los siete
  tipos aparecen en PostgreSQL sin error `422`.
- [ ] **E03 — P0.** Reintentar o recargar no duplica un mismo `client_event_id` ni
  una misma `client_session_id`.
- [ ] **E04 — P0.** El panel solo es accesible para administración y no expone
  correos; identifica participantes como `P-####`.
- [ ] **E05 — P0.** Los rangos de fecha filtran resumen, tendencia, desglose por
  noticia, participantes y cronología individual de forma coherente.
- [ ] **E06 — P1.** El CSV descarga, abre correctamente y coincide con los agregados
  visibles.
- [ ] **E07 — P0.** Las reacciones del panel se describen como utilidad percibida del
  análisis completo, no como desempeño predictivo.

## 7. Automatizaciones y fuentes

- [ ] **F01 — P0.** El scraping está programado a las 08:30 y 20:30 America/Lima,
  con cinco artículos máximos por medio y ciclo.
- [ ] **F02 — P0.** El Comercio, RPP, La República, Agencia Andina, El Peruano y X
  están activos; Peru21 permanece inactivo y documentado por bloqueo `403`.
- [ ] **F03 — P1.** La última ejecución completó cada fuente activa sin detener el
  ciclo completo ante un fallo individual.
- [ ] **F04 — P1.** Gemini está limitado al presupuesto configurado, distribuye los
  intentos entre medios y no borra fuentes válidas anteriores.
- [ ] **F05 — P1.** En las 100 noticias más recientes se registra la cobertura de
  fuentes relacionadas y se revisa una muestra de enlaces.
- [ ] **F06 — P0.** El recordatorio está habilitado, programado cada hora en el
  minuto 15 y exige cuenta verificada, consentimiento, rol `user`, 48 horas y
  ausencia de envío previo.
- [ ] **F07 — P0.** El envío de prueba figura una sola vez, sin error y no vuelve a
  ser elegible.

## 8. Seguridad y privacidad

- [ ] **G01 — P0.** `/docs` y `/openapi.json` responden `404` en producción.
- [ ] **G02 — P0.** Endpoints privados sin sesión responden `401` o `403` y no aceptan
  un identificador de usuario proporcionado por el navegador.
- [ ] **G03 — P0.** La cookie de sesión es `HttpOnly`, `Secure` y `SameSite=Lax`.
- [ ] **G04 — P1.** HTTPS incluye HSTS, `X-Content-Type-Options`, política de
  referer y política de permisos configuradas.
- [ ] **G05 — P0.** No aparecen secretos, correos de otros usuarios ni trazas
  internas en interfaz, consola o respuestas públicas.
- [ ] **G06 — P0.** Privacidad versión `2026-10-05` describe telemetría, correo
  transaccional y recordatorio opcional.

## 9. Congelamiento antes del estudio

- [ ] **H01 — P0.** El asesor aprueba el protocolo, instrumento, duración,
  reclutamiento y criterio de inclusión/exclusión.
- [ ] **H02 — P0.** Se ejecuta primero un piloto; sus participantes y eventos no se
  mezclan con la muestra formal.
- [ ] **H03 — P0.** Se registra el instante exacto de inicio formal. Toda actividad
  anterior, incluidas las cuentas 4 y 12, se clasifica como prueba técnica.
- [ ] **H04 — P0.** Se registra respaldo, commits, configuración pública y lista de
  noticias disponible al inicio.
- [ ] **H05 — P0.** Durante la recolección no se cambian instrumento, hipótesis,
  umbrales, modelos ni interfaz salvo un incidente P0 documentado.
- [ ] **H06 — P0.** Se fija fecha de cierre y se exportan telemetría, encuesta y
  bitácora de incidencias conservando códigos seudonimizados.

## 10. Criterio de salida

El estudio puede comenzar únicamente cuando todos los casos P0 estén `APROBADO`
y los P1 estén aprobados o tengan una justificación explícita aceptada por el
equipo y el asesor. Los P2 no bloquean el estudio y pasan a trabajo futuro.

La prueba de aceptación no demuestra eficacia científica: solo confirma que la
versión congelada implementa correctamente el protocolo. Los resultados de los
participantes se analizan después con el plan estadístico predefinido.
