"""Probe candidate refutation pages without storing or labeling them."""

from __future__ import annotations

import requests

from collect_stance_articles import extract_article

URLS = [
    "https://larepublica.pe/verificador/2026/07/10/es-falso-que-juntos-por-el-peru-no-haya-denunciado-fraude-567890",
    "https://larepublica.pe/amp/verificador/2026/07/21/es-falso-que-el-congreso-nunca-haya-tenido-los-votos-para-vacar-a-castillo-como-indico-el-vocero-de-juntos-por-el-peru-1954554",
    "https://larepublica.pe/amp/verificador/2026/09/04/es-falso-que-keiko-fujimori-haya-disuelto-el-congreso-de-la-republica-la-presidenta-ha-rechazado-esa-posibilidad-178356",
    "https://larepublica.pe/amp/verificador/2026/09/05/es-falso-que-el-congreso-vaya-a-expulsar-hoy-a-oscar-arriola-comandante-general-de-la-pnp-no-existe-un-mecanismo-inmediato-para-removerlo-295725",
    "https://dev.ojo-publico.com/6334/es-falsa-la-version-laje-sobre-contraloria-confirmo-fraude",
    "https://convoca.pe/convoca-verifica/reportaje/desinformacion-electoral-cinco-narrativas-falsas-sobre-los-comicios-2026",
    "https://perucheck.pe/articles/verificadas/renovacion-popular/2026/08/24/es-falso-que-renovacion-popular-sea-el-unico-partido-con-una-bancada-en-el-congreso-como-dijo-lopez-aliaga-2033476",
    "https://perucheck.pe/articles/verificadas/2026/06/11/habra-una-tercera-vuelta-electoral-este-12-de-julio-es-falso-el-supuesto-comunicado-de-la-onpe-810436",
]


def main() -> None:
    for url in URLS:
        try:
            response = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            item = extract_article(response.text, response.url)
            print(f"OK\t{len(item['article'])}\t{item['title'][:75]}\t{response.url}")
        except Exception as exc:
            print(f"FAIL\t{type(exc).__name__}: {exc}\t{url}")


if __name__ == "__main__":
    main()
