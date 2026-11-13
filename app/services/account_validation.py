from __future__ import annotations


USERNAME_ERROR = (
    "El nombre de usuario debe tener entre 3 y 20 caracteres y contener "
    "solo letras, números y guiones."
)
PASSWORD_ERROR = (
    "La contraseña debe tener entre 8 y 128 caracteres e incluir al menos "
    "una mayúscula, un número y un símbolo, sin espacios."
)


def validate_username(value: str) -> str:
    normalized = value.strip()
    if not 3 <= len(normalized) <= 20:
        raise ValueError(USERNAME_ERROR)
    if not all(char.isalnum() or char == "-" for char in normalized):
        raise ValueError(USERNAME_ERROR)
    return normalized


def validate_password(value: str) -> str:
    if not 8 <= len(value) <= 128:
        raise ValueError(PASSWORD_ERROR)
    if any(char.isspace() for char in value):
        raise ValueError(PASSWORD_ERROR)
    if not any(char.isupper() for char in value):
        raise ValueError(PASSWORD_ERROR)
    if not any(char.isdigit() for char in value):
        raise ValueError(PASSWORD_ERROR)
    if not any(not char.isalnum() for char in value):
        raise ValueError(PASSWORD_ERROR)
    return value
