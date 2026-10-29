# Recuperación segura de contraseña

## Objetivo y alcance

El flujo permite recuperar acceso mediante un enlace enviado al correo registrado,
sin revelar públicamente si una cuenta existe. No sustituye la verificación de
correo ni inicia sesión automáticamente después del cambio.

## Controles implementados

- La solicitud responde siempre `202` con el mismo mensaje para correos existentes,
  inexistentes o temporalmente limitados.
- El envío se programa como tarea posterior a la respuesta para reducir diferencias
  de tiempo observables entre cuentas existentes e inexistentes.
- El token contiene 32 bytes aleatorios generados con `secrets.token_urlsafe`, vence
  por defecto en 20 minutos y solo puede utilizarse una vez.
- La base de datos almacena un HMAC-SHA-256 del token, nunca el token original.
- Correos e IP se almacenan únicamente como huellas HMAC con un secreto independiente.
- El límite predeterminado es tres solicitudes por correo y diez por IP cada quince
  minutos. Nginx añade un límite adicional para las rutas públicas de autenticación.
- Un nuevo enlace invalida enlaces anteriores únicamente cuando la nueva solicitud
  queda registrada.
- Al cambiar la contraseña se invalidan todas las sesiones anteriores porque el
  token de sesión contiene una huella del hash de contraseña.
- La página retira el token de la barra del navegador y aplica `Referrer-Policy:
  no-referrer`.
- El usuario recibe una notificación posterior al cambio, sin incluir la contraseña.
- Los registros de solicitudes se conservan siete días por defecto y después se
  eliminan durante el siguiente ciclo de solicitud.

## Almacenamiento de contraseñas

Las contraseñas nuevas usan PBKDF2-HMAC-SHA-256 con sal aleatoria y 600 000
iteraciones. El formato guarda algoritmo y factor de trabajo para permitir futuras
actualizaciones. Los hashes históricos de 120 000 iteraciones siguen siendo
verificables y se actualizan automáticamente en el siguiente inicio de sesión válido.

## Configuración obligatoria

`PASSWORD_RESET_SECRET` debe ser aleatorio, independiente de los demás secretos y
tener al menos 32 caracteres. La API devuelve `503` si falta, evitando iniciar un
flujo parcialmente configurado. Los demás parámetros están documentados en
`.env.example`.

## Evidencia de verificación

- Prueba de respuesta indistinguible para correo existente e inexistente.
- Prueba de límite por correo sin envío adicional.
- Prueba de token no almacenado en claro y de un solo uso.
- Prueba de rechazo de la contraseña anterior e invalidación de sesiones existentes.
- Pruebas unitarias de autenticación y sesión.
- Lint, validación de traducciones y pruebas del frontend.

## Límites y operación

- El envío depende de Resend; sus fallos se registran en el servidor sin cambiar la
  respuesta pública. Deben monitorizarse los errores de entrega.
- `PASSWORD_RESET_TRUST_PROXY_HEADERS=true` solo es seguro cuando la API no es
  accesible directamente y Nginx reemplaza los encabezados del cliente, como en el
  despliegue Docker del proyecto.
- El rate limit no sustituye alertas operativas ni protección adicional ante ataques
  distribuidos de gran escala.

## Referencias

- OWASP Forgot Password Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Forgot_Password_Cheat_Sheet.html>
- OWASP Password Storage Cheat Sheet:
  <https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html>
