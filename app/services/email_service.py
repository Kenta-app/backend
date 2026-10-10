from __future__ import annotations

import os

import requests


class EmailDeliveryError(RuntimeError):
    """Raised when a transactional email cannot be sent."""


class ResendEmailSender:
    API_URL = "https://api.resend.com/emails"

    def __init__(self, apiKey: str | None = None, fromAddress: str | None = None):
        self.apiKey = (apiKey if apiKey is not None else os.getenv("RESEND_API_KEY", "")).strip()
        self.fromAddress = (
            fromAddress
            if fromAddress is not None
            else os.getenv("EMAIL_FROM", "Kenta <verificacion@ikenta.app>")
        ).strip()

    def sendVerificationCode(self, email: str, code: str) -> None:
        if not self.apiKey or not self.fromAddress:
            raise EmailDeliveryError("El servicio de correo no está configurado.")

        ttl_minutes = int(os.getenv("EMAIL_VERIFICATION_TTL_MINUTES", "10"))
        self._send(
            email,
            "Confirma tu correo en Kenta",
            (
                f"Tu código de confirmación para Kenta es: {code}\n\n"
                f"Vence en {ttl_minutes} minutos. "
                "Si no solicitaste este código, puedes ignorar este correo."
            ),
        )

    def sendStudyReminder(self, email: str, username: str) -> None:
        public_url = os.getenv("FRONTEND_PUBLIC_URL", "https://ikenta.app").rstrip("/")
        display_name = username.strip() or "participante"
        self._send(
            email,
            "¿Nos ayudas a completar tu evaluación de Kenta?",
            (
                f"Hola, {display_name}:\n\n"
                "Hace dos días creaste tu cuenta en Kenta. Para completar correctamente "
                "la validación de la plataforma, te invitamos a volver y explorar las noticias, "
                "sus fuentes relacionadas y las demás funciones disponibles.\n\n"
                f"Continuar en Kenta: {public_url}/home\n\n"
                "Gracias por apoyar este proyecto académico. Recibes este único recordatorio "
                "porque aceptaste recibirlo al crear tu cuenta; no enviaremos recordatorios "
                "adicionales de este tipo."
            ),
        )

    def sendDrawConfirmation(self, email: str, username: str, drawId: str) -> None:
        plain_text = (
            "¡Hola! 👋\n\n"
            "🎉 ¡Felicidades! Eres el ganador del sorteo de Kenta y te llevas S/ 80! 🏆💜\n\n"
            "Queremos agradecerte por haber participado en nuestra investigación y por dedicar tu tiempo "
            "a probar Kenta. Tu apoyo ha sido muy importante para el desarrollo de nuestra tesis.\n\n"
            "Para coordinar la entrega de tu premio, necesitamos que nos compartas los siguientes datos:\n\n"
            "- 📱 Número de celular: Indícanos el número al que deseas recibir el premio.\n"
            "- 💜 Billetera digital de preferencia: Cuéntanos si prefieres recibir tu premio a través de "
            "Yape, Plin u otra billetera digital.\n\n"
            "Con esta información podremos realizar la transferencia de los S/ 80 directamente a la "
            "billetera que nos indiques. Una vez realizada, te enviaremos la confirmación de la transferencia "
            "por este medio.\n\n"
            "¡Muchas gracias por ser parte de Kenta y esperamos que hayas disfrutado la experiencia! 💜\n\n"
            "Saludos,\nEquipo Kenta 💜"
        )
        html = """<!doctype html>
<html lang="es">
  <body style="margin:0;padding:24px;background:#f7f3ff;font-family:Arial,sans-serif;color:#2d193d;line-height:1.55;">
    <main style="max-width:600px;margin:0 auto;padding:32px;background:#ffffff;border-radius:16px;">
      <p>¡Hola! 👋</p>
      <p style="font-size:18px;"><strong>🎉 ¡Felicidades! Eres el ganador del sorteo de Kenta y te llevas S/ 80! 🏆💜</strong></p>
      <p>Queremos agradecerte por haber participado en nuestra investigación y por dedicar tu tiempo a probar Kenta. Tu apoyo ha sido muy importante para el desarrollo de nuestra tesis.</p>
      <p>Para coordinar la entrega de tu premio, necesitamos que nos compartas los siguientes datos:</p>
      <ul>
        <li>📱 <strong>Número de celular:</strong> Indícanos el número al que deseas recibir el premio.</li>
        <li>💜 <strong>Billetera digital de preferencia:</strong> Cuéntanos si prefieres recibir tu premio a través de <strong>Yape, Plin u otra billetera digital</strong>.</li>
      </ul>
      <p>Con esta información podremos realizar la transferencia de los <strong>S/ 80</strong> directamente a la billetera que nos indiques. Una vez realizada, te enviaremos la confirmación de la transferencia por este medio.</p>
      <p>¡Muchas gracias por ser parte de Kenta y esperamos que hayas disfrutado la experiencia! 💜</p>
      <p>Saludos,<br><strong>Equipo Kenta</strong> 💜</p>
    </main>
  </body>
</html>"""
        self._send(
            email,
            "🎉 ¡Felicidades! Ganaste S/ 80 en el sorteo de Kenta 💜",
            plain_text,
            html=html,
        )

    def sendDrawTeamNotification(self, email: str, winnerEmail: str, drawId: str) -> None:
        self._send(
            email,
            "Confirmación de datos: ganador del sorteo Kenta",
            (
                "El ganador confirmó sus datos de contacto.\n\n"
                f"Sorteo: {drawId}\nCorreo del ganador: {winnerEmail}"
            ),
        )

    def _send(self, email: str, subject: str, body: str, html: str | None = None) -> None:
        if not self.apiKey or not self.fromAddress:
            raise EmailDeliveryError("El servicio de correo no está configurado.")

        payload = {
            "from": self.fromAddress,
            "to": [email],
            "subject": subject,
            "text": body,
        }
        if html:
            payload["html"] = html

        try:
            response = requests.post(
                self.API_URL,
                headers={"Authorization": f"Bearer {self.apiKey}"},
                json=payload,
                timeout=10,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EmailDeliveryError("No se pudo enviar el correo.") from exc
