#!/usr/bin/env python3
"""
Script de prueba simple para el módulo de justificación.
Ejecuta pruebas básicas para verificar que está funcionando.
"""

import sys
import os
from pathlib import Path

# Agregar el directorio backend al path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

def main():
    print("=" * 80)
    print("PRUEBA DEL MÓDULO DE JUSTIFICACIÓN")
    print("=" * 80)

    # Test 1: Verificar .env
    print("\n[1/5] Verificando archivo .env...")
    env_file = backend_dir / ".env"
    if env_file.exists():
        print(f"   ✓ Archivo .env encontrado en: {env_file}")
        with open(env_file) as f:
            content = f.read()
            if "GEMINI_API_KEY" in content:
                print("   ✓ Variable GEMINI_API_KEY presente en .env")
                if "your-gemini-api-key-here" in content:
                    print("   ⚠ ADVERTENCIA: GEMINI_API_KEY aún tiene valor por defecto")
                    print("       → Actualiza .env con tu clave real")
            else:
                print("   ✗ GEMINI_API_KEY no encontrada en .env")
    else:
        print(f"   ✗ Archivo .env no encontrado en: {env_file}")

    # Test 2: Verificar requirements.txt
    print("\n[2/5] Verificando dependencias en requirements.txt...")
    req_file = backend_dir / "requirements.txt"
    if req_file.exists():
        print(f"   ✓ Archivo requirements.txt encontrado")
        with open(req_file) as f:
            content = f.read()
            deps = {
                "google-generativeai": "Google Gemini API",
                "cachetools": "Cache con TTL",
                "fastapi": "Framework API",
                "sqlalchemy": "ORM Database",
                "pydantic": "Validación",
            }
            for dep, desc in deps.items():
                if dep in content:
                    print(f"   ✓ {dep:25} - {desc}")
                else:
                    print(f"   ✗ {dep:25} - FALTA INSTALAR")
    else:
        print(f"   ✗ Archivo requirements.txt no encontrado")

    # Test 3: Verificar estructura de archivos
    print("\n[3/5] Verificando estructura de archivos...")
    files_to_check = [
        ("app/application_services/justification_service.py", "Servicio Gemini"),
        ("app/api_controllers/justification_controller.py", "Controlador API"),
        ("app/routers/justification_router.py", "Router REST"),
        ("app/schemas/justification_schemas.py", "Esquemas Pydantic"),
        ("app/interfaces/justification_service.py", "Interfaz"),
        ("app/dependencies.py", "Inyección de dependencias"),
    ]

    for file_path, description in files_to_check:
        full_path = backend_dir / file_path
        if full_path.exists():
            print(f"   ✓ {file_path:50} - {description}")
        else:
            print(f"   ✗ {file_path:50} - NO ENCONTRADO")

    # Test 4: Verificar registro en main.py
    print("\n[4/5] Verificando registro en main.py...")
    main_file = backend_dir / "app/main.py"
    if main_file.exists():
        with open(main_file) as f:
            content = f.read()
            checks = {
                "from app.routers.justification_router import": "Importación",
                "app.include_router(justification_router": "Registro del router",
                "prefix=\"/justifications\"": "Prefijo de ruta",
            }
            for check, desc in checks.items():
                if check in content:
                    print(f"   ✓ {desc:40} - OK")
                else:
                    print(f"   ✗ {desc:40} - NO ENCONTRADO")

    # Test 5: Mostrar próximos pasos
    print("\n[5/5] Próximos pasos para usar el módulo...")
    print("\n   1️⃣  Obtener API Key de Gemini:")
    print("       → Ve a https://aistudio.google.com/app/apikeys")
    print("       → Crea una nueva API key")
    print("       → Cópiala y pégala en .env")
    print("\n   2️⃣  Instalar dependencias:")
    print("       → pip install -r requirements.txt")
    print("\n   3️⃣  Iniciar la aplicación:")
    print("       → uvicorn app.main:app --reload --host 0.0.0.0 --port 8000")
    print("\n   4️⃣  Prueba la API:")
    print("       → Accede a http://localhost:8000/docs")
    print("       → O usa el archivo: justification_tests.http")
    print("\n" + "=" * 80)
    print("✓ VERIFICA QUE TODOS LOS CHECKS HAYAN PASADO")
    print("=" * 80)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n✗ Error: {e}")
        sys.exit(1)

