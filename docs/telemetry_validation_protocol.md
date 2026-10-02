# Protocolo de telemetría para la validación con usuarios

## Alcance

Kenta registra interacciones de usuarios autenticados para describir el uso de la
aplicación durante la validación. Las cuentas con rol `admin` o `moderator` se
excluyen de los agregados para que las pruebas del equipo no contaminen la
muestra.

El panel administrativo muestra códigos seudonimizados (`P-####`) y no expone
correos electrónicos. La correspondencia con la cuenta existe en la base de
datos y solo debe emplearse para soporte o auditoría autorizada.

## Unidad de cada métrica

- **Participante activo:** cuenta no administrativa con al menos un evento en
  el intervalo seleccionado.
- **Sesión:** una apertura continua de la aplicación en una pestaña. Se mide
  solo el tiempo durante el cual la pestaña está visible. Las instantáneas de
  una misma sesión actualizan un único registro mediante `client_session_id`.
- **Apertura de detalle:** selección de una noticia para abrir su página de
  detalle.
- **Lectura:** apertura del detalle con al menos un segundo visible. El tiempo
  acumulado de una misma apertura actualiza un único registro mediante
  `client_event_id`.
- **Clic original:** selección del enlace que lleva al medio de origen.
- **Reacción:** estado actual de utilidad de una noticia para un usuario. Un
  cambio sustituye el valor anterior; no es un historial de votos.
- **Favorito:** noticia que permanece guardada. Si se elimina, el registro deja
  de existir; por tanto, es estado actual y no historial de guardados.

Los clics, lecturas y sesiones enviados nuevamente por reintentos de red se
deduplican en el servidor. El panel permite agregados globales, evolución por
periodo, desglose por noticia, desglose por participante, cronología de eventos
y exportación CSV de los agregados por participante.

## Corte entre piloto y validación

La instrumentación anterior generaba varios registros cuando una misma sesión
se ocultaba, cerraba o cambiaba de estado. Por ello, el número histórico de
filas de `serving.user_app_sessions` anterior al despliegue de esta versión no
se interpreta como número de visitas independientes.

Antes de iniciar la validación formal se debe registrar en la bitácora:

1. fecha y hora de despliegue de la instrumentación deduplicada;
2. fecha y hora de inicio y cierre de la validación;
3. versión o commit desplegado de backend y frontend;
4. criterios de inclusión y exclusión de participantes;
5. incidencias técnicas ocurridas durante el periodo.

Los resultados finales se consultan usando como inicio una fecha posterior al
despliegue. Los datos previos se conservan como piloto técnico y no se mezclan
con los resultados formales.

## Acceso administrativo

Se recomienda crear una cuenta separada para administración. No se debe elevar
a `admin` una cuenta usada como participante porque las cuentas administrativas
se excluyen de las métricas, incluidos sus eventos anteriores.

Después de registrar y verificar la cuenta administrativa, el rol se asigna en
PostgreSQL con una actualización explícita por correo:

```sql
UPDATE serving.users
SET role = 'admin'
WHERE lower(email) = lower('CORREO_ADMINISTRADOR');
```

Se debe comprobar que exactamente una fila fue actualizada y volver a iniciar
sesión para que la interfaz redirija a `/admin/analytics`.

## Tablas de origen

- `serving.user_app_sessions`: sesiones y tiempo visible acumulado.
- `serving.news_detail_clicks`: aperturas de detalle.
- `serving.news_views`: lecturas y tiempo visible en el detalle.
- `serving.news_click`: clics hacia la noticia original.
- `serving.news_reactions`: reacción actual por usuario y noticia.
- `serving.news_favorites`: favoritos actuales.

La autenticación usa una cookie de sesión firmada, `HttpOnly`, `Secure` y
`SameSite=Lax`. El identificador de usuario no se acepta desde una cabecera
controlada por el navegador.
