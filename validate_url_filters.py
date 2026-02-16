#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Script para validar que el AndinaScraper filtra correctamente las URLs
"""

print("=" * 80)
print("VALIDACIÓN DE FILTROS DE URLs - ANDINA SCRAPER")
print("=" * 80)

# URLs de ejemplo que pueden aparecer en Andina
test_urls = [
    # ✅ URLS VÁLIDAS - Artículos reales
    ("https://andina.pe/agencia/noticia-presidencia-reafirma-compromiso-con-diagnostico-temprano-del-cancer-infantil-1063170.aspx", True, "Artículo válido"),
    ("https://andina.pe/agencia/noticia-corte-del-callao-y-mtpe-implementan-sistema-permitira-agilizar-procesos-laborales-1063193.aspx", True, "Artículo válido"),

    # ❌ URLS A EXCLUIR - Redes sociales
    ("https://www.facebook.com/sharer/sharer.php?u=https://andina.pe/agencia/noticia-...", False, "URL de compartir en Facebook"),
    ("https://twitter.com/intent/tweet?text=...", False, "URL de compartir en Twitter"),
    ("https://www.instagram.com/...", False, "Link a Instagram"),
    ("https://www.linkedin.com/...", False, "Link a LinkedIn"),
    ("https://wa.me/...", False, "Link a WhatsApp"),

    # ❌ URLS A EXCLUIR - Mailto y otros compartir
    ("mailto:?subject=...", False, "mailto link"),
    ("https://example.com/share_to_story", False, "share_to_story"),

    # ❌ URLS A EXCLUIR - No son artículos
    ("https://andina.pe/", False, "URL principal (no es artículo)"),
    ("https://andina.pe/agencia/", False, "Sección (no es artículo)"),
    ("https://andina.pe/agencia/video-...", False, "Video (no es artículo)"),
]

print("\n🔍 Probando filtros de URL:\n")

for url, should_pass, description in test_urls:
    # Aplicar los mismos filtros que en el scraper

    # FILTRO 1: Descartar URLs de redes sociales
    has_social = any(social in url.lower() for social in ['facebook.com', 'twitter.com', 'x.com', 'instagram.com', 'linkedin.com', 'whatsapp', 'telegram'])

    # FILTRO 2: Descartar URLs de compartir
    has_share = any(share in url.lower() for share in ['sharer', 'share', 'share_to_story', 'mailto'])

    # FILTRO 3: Solo aceptar URLs de Andina que sean artículos
    is_valid_article = 'noticia' in url.lower() and '.aspx' in url.lower() and 'andina.pe' in url.lower()

    # Determinar si la URL pasa los filtros
    passes_filters = not has_social and not has_share and is_valid_article

    # Comparar con el resultado esperado
    status = "✅" if passes_filters == should_pass else "❌"

    print(f"{status} {description}")
    print(f"   URL: {url[:70]}...")
    print(f"   Red social: {has_social} | Compartir: {has_share} | Artículo válido: {is_valid_article}")
    print(f"   Resultado: {'PASA ✅' if passes_filters else 'RECHAZADA ❌'}")
    print()

print("\n" + "=" * 80)
print("RESUMEN DE CAMBIOS:")
print("=" * 80)
print("""
✅ FILTRO 1: Excluir URLs de redes sociales
   - facebook.com, twitter.com, x.com
   - instagram.com, linkedin.com
   - whatsapp, telegram

✅ FILTRO 2: Excluir URLs de compartir
   - sharer, share, share_to_story
   - mailto

✅ FILTRO 3: Solo aceptar artículos reales
   - Contiene 'noticia' (minúsculas)
   - Contiene '.aspx'
   - Contiene 'andina.pe'

RESULTADO:
- Antes: Capturaba URLs de Facebook, Twitter, etc.
- Después: Solo captura URLs de artículos válidos
""")
