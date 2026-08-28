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

        payload = {
            "from": self.fromAddress,
            "to": [email],
            "subject": "Confirma tu correo en Kenta",
            "text": (
                f"Tu código de confirmación para Kenta es: {code}\n\n"
                "Vence en 10 minutos. Si no solicitaste este código, puedes ignorar este correo."
            ),
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
            raise EmailDeliveryError("No se pudo enviar el correo de confirmación.") from exc
