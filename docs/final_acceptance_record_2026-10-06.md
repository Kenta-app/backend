# Acta de aceptación de la versión candidata para validación con usuarios

## 1. Identificación de la versión

- Fecha de congelamiento de la candidata: `2026-10-06T20:40:43-05:00`
  (America/Lima).
- Backend desplegado: `a982708461a4073e518ffb26f8971d7e97a048e4`.
- Frontend desplegado: `71c406a185d06c2d717ca9e3e5c1eb10740d2c72`.
- Respaldo PostgreSQL: `/root/kenta/backups/kenta-candidate-20261006-204033.dump`.
- Tamaño observado del respaldo: `6.0M`.
- SHA-256 del respaldo:
  `999a96259d920d94e55c5f409987f827a34e4332a0a6500d502f2c556f236edc`.
- Cuentas `4` y `12`: pruebas técnicas; deben excluirse de la muestra formal.

La revisión se realizó sobre la aplicación productiva en `https://ikenta.app`.
Esta acta acredita aceptación técnica, no eficacia científica ni resultados con
participantes.

## 2. Estado de infraestructura

Al congelar la candidata, `api`, `frontend`, `nginx` y `postgres` figuraban en
estado `healthy`, con cero reinicios. Las páginas públicas y privadas probadas
respondieron sin errores `5xx`; `/health` confirmó base de datos, clasificador y
programador disponibles. `/docs` y `/openapi.json` respondieron `404`.

La cookie `kenta_session` fue inspeccionada en el navegador y presentó los
atributos `HttpOnly`, `Secure` y `SameSite=Lax`. HTTPS publicó HSTS,
`X-Content-Type-Options`, política de referente y política de permisos.

## 3. Resultado de la lista de aceptación

| Bloque | Casos | Resultado |
|---|---:|---|
| A. Despliegue y disponibilidad | A01–A05 | Aprobado |
| B. Cuenta, consentimiento y perfil | B01–B08 | Aprobado |
| C. Feed, navegación y diseño adaptable | C01–C06 | Aprobado |
| D. Detalle y funciones de noticia | D01–D09 | Aprobado |
| E. Telemetría y panel administrativo | E01–E07 | Aprobado |
| F. Automatizaciones y fuentes | F01–F07 | Aprobado |
| G. Seguridad y privacidad | G01–G06 | Aprobado |
| H. Congelamiento del estudio | H01–H06 | Pendiente del piloto e inicio formal |

## 4. Evidencia de telemetría

La prueba controlada del participante técnico `P-0012` produjo los siete tipos
esperados:

- apertura de detalle;
- lectura con duración;
- clic en noticia original;
- clic en fuente relacionada;
- utilidad percibida;
- guardado;
- sesión con duración.

La cola local se vació tanto durante el uso como inmediatamente después del
cierre de sesión. La consulta de integridad obtuvo `duplicate_extra = 0` para
`detail-click`, `original-click`, `related-click`, `session` y `view`. El panel
administrativo mostró códigos `P-####`, rangos temporales, cronología individual
y exportación CSV sin exponer correos.

Durante la aceptación se corrigieron dos carreras de cierre: la finalización de
sesión/lectura antes de invalidar la cookie y la espera de un envío automático
ya iniciado antes del vaciado obligatorio del logout. También se añadió el
control de cierre de sesión a la navegación móvil.

## 5. Configuración operativa aceptada

- Scraping: `08:30` y `20:30`, America/Lima.
- Máximo por medio y ciclo: `5` artículos.
- Fuentes activas: El Comercio, RPP Noticias, La República, Agencia Andina,
  El Peruano y X.
- Peru21: inactivo y documentado por respuesta `403` del proveedor.
- Justificación automática: habilitada con presupuesto máximo de `10` por ciclo.
- Recordatorio del estudio: habilitado, una sola vez, alrededor de 48 horas tras
  el registro, únicamente con consentimiento y cuenta verificada.
- Stance público: deshabilitado; no forma parte de la experiencia desplegada.
- Reacción útil/no útil: utilidad percibida del análisis completo, no etiqueta de
  verdad ni realimentación automática del modelo.

En la revisión de las cien noticias más recientes se observó cobertura visible
de fuentes relacionadas en `67 %`. Esta cifra describe el estado de la muestra
en ese momento; no constituye una garantía por noticia ni debe presentarse como
una métrica fija del sistema.

## 6. Limitaciones aceptadas

- Una noticia puede no tener una fuente relacionada válida; la interfaz muestra
  un estado vacío en lugar de inventar o duplicar enlaces.
- La disponibilidad de medios externos depende de sus sitios y políticas de
  acceso.
- La clasificación de riesgo se presenta como señal estimada, no como veredicto
  absoluto.
- El corpus y los experimentos de stance se conservan como evidencia de
  investigación, pero el resultado no se expone como clasificador peruano
  operativo.

## 7. Condiciones antes de iniciar la muestra formal

1. Obtener aprobación del asesor para protocolo, instrumento, duración,
   reclutamiento y criterios de inclusión/exclusión.
2. Ejecutar un piloto con tres a cinco participantes y excluir sus cuentas y
   eventos del análisis formal.
3. Validar el listado del archivo de respaldo desde el contenedor PostgreSQL.
4. Registrar un nuevo instante de inicio formal y el identificador de cada cuenta
   piloto excluida.
5. No modificar interfaz, modelos, umbrales ni instrumento durante la recolección,
   salvo incidente P0 documentado.
6. Al cierre, exportar telemetría y encuesta preservando los códigos
   seudonimizados.

La aplicación está técnicamente preparada para el piloto. La muestra formal no
debe declararse iniciada hasta completar estas condiciones.
