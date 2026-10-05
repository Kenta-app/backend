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

    def _send(self, email: str, subject: str, body: str) -> None:
        if not self.apiKey or not self.fromAddress:
            raise EmailDeliveryError("El servicio de correo no está configurado.")

        payload = {
            "from": self.fromAddress,
            "to": [email],
            "subject": subject,
            "text": body,
        }

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
