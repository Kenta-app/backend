"""
Servicio de verificaci?n de evidencias usando Gemini 2.5 Flash con Google Search Grounding.
Fuerza al modelo a generar una respuesta JSON estructurada con fuentes reales del contexto peruano.
"""

from __future__ import annotations

import logging
import os
import time
import json
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from google import genai
from cachetools import TTLCache
from sqlalchemy.orm import Session

from app.interfaces.justification_service import IJustificationService
from app.processed.models import MlPrediction, ProcessedNews
from app.raw.models import RawNews

logger = logging.getLogger(__name__)


class GeminiJustificationService(IJustificationService):
    GEMINI_MODEL = "gemini-2.5-flash"
    MAX_DEBUG_TEXT_LENGTH = 4000
    JOURNALISTIC_SOURCES = {
        "andina": ("andina.pe",),
        "afp factual": ("factual.afp.com",),
        "chequeado": ("chequeado.com",),
        "colombiacheck": ("colombiacheck.com",),
        "convoca": ("convoca.pe",),
        "el b?ho": ("elbuho.pe",),
        "el buho": ("elbuho.pe",),
        "el comercio": ("elcomercio.pe",),
        "epicentro": ("epicentro.tv",),
        "exitosa": ("exitosanoticias.pe",),
        "gesti?n": ("gestion.pe",),
        "gestion": ("gestion.pe",),
        "la rep?blica": ("larepublica.pe",),
        "la republica": ("larepublica.pe",),
        "maldita": ("maldita.es",),
        "n60": ("n60.pe",),
        "ojo p?blico": ("ojo-publico.com",),
        "ojo publico": ("ojo-publico.com",),
        "ojo bi?nico": ("ojo-publico.com",),
        "ojo bionico": ("ojo-publico.com",),
        "per?21": ("peru21.pe",),
        "peru21": ("peru21.pe",),
        "rpp": ("rpp.pe",),
        "verificador": ("larepublica.pe",),
    }
    BLOCKED_DOMAINS = {
        "wikipedia.org",
        "reddit.com",
        "quora.com",
        "blogspot.com",
        "medium.com",
        "facebook.com",
        "x.com",
        "twitter.com",
        "tiktok.com",
        "youtube.com",
        "google.com",
    }

    def __init__(
            self,
            db: Session,
            api_key: Optional[str] = None,
            cache_ttl: int = 3600,
            max_retries: int = 3,
            retry_delay: float = 2.0,
    ):
        self.db = db
        self.cache_ttl = cache_ttl
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._cache: TTLCache = TTLCache(maxsize=1000, ttl=cache_ttl)
        self._cache_stats = {"hits": 0, "misses": 0}

        api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY no configurada en variables de entorno")

        self.client = genai.Client(api_key=api_key)
        logger.info("GeminiJustificationService inicializado como generador de evidencia period?stica.")

    def generate_justification(
        self,
        prediction_id: int,
        include_context: bool = True,
        regenerate: bool = False,
    ) -> dict:
        """
        Busca evidencias web que respalden o desmientan la noticia y devuelve fuentes estructuradas en JSON.
        """
        if not regenerate and prediction_id in self._cache:
            self._cache_stats["hits"] += 1
            cached = self._cache[prediction_id].copy()
            cached["from_cache"] = True
            return cached

        self._cache_stats["misses"] += 1

        prediction = self.db.query(MlPrediction).filter(
            MlPrediction.prediction_id == prediction_id
        ).first()

        if not prediction:
            raise ValueError(f"Predicci?n con ID {prediction_id} no encontrada")

        processed = None
        raw_news = None
        if include_context and prediction:
            processed = self.db.query(ProcessedNews).filter(
                ProcessedNews.news_processed_id == prediction.representative_news_processed_id
            ).first()
            if processed:
                raw_news = self.db.query(RawNews).filter(
                    RawNews.news_raw_id == processed.news_raw_id
                ).first()

        # Obtenemos el JSON estructurado desde Gemini
        evidence_report = self._generate_with_retries(
            prediction=prediction,
            processed_news=processed if include_context else None,
            raw_news=raw_news if include_context else None,
        )

        response = {
            "prediction_id": prediction_id,
            "sources": evidence_report["sources"],
            "verification_summary": evidence_report["verification_summary"],
            "ml_prediction": {
                "fake_score": float(prediction.fake_score),
                "sentiment_label": prediction.sentiment_label,
            },
            "from_cache": False,
            "generated_at": datetime.utcnow().isoformat(),
            "model_used": self.GEMINI_MODEL,
        }

        self._cache[prediction_id] = response.copy()
        response["from_cache"] = False

        return response

    def _generate_with_retries(
            self,
            prediction: MlPrediction,
            processed_news: Optional[ProcessedNews] = None,
            raw_news: Optional[RawNews] = None,
            attempt: int = 0,
    ) -> dict:
        try:
            prompt = self._build_prompt(prediction, raw_news, processed_news)
            response = self._generate_gemini_response(prompt)
            texto_generado = self._response_text(response)

            if not texto_generado:
                raise ValueError("Respuesta vac?a de Gemini")

            grounded_sources = self._sources_from_grounding(response)
            grounded_urls = {source["url"] for source in grounded_sources}
            if self._debug_enabled():
                logger.info("Gemini raw text: %s", texto_generado[: self.MAX_DEBUG_TEXT_LENGTH])
                logger.info("Gemini grounded sources: %s", grounded_sources)

            # Parseamos el JSON generado por el propio modelo
            try:
                data = self._parse_json_response(texto_generado)
                return self._normalize_report(
                    data,
                    grounded_urls=grounded_urls,
                    grounding_sources=grounded_sources,
                )
            except json.JSONDecodeError:
                # Si por alguna raz?n no es JSON v?lido, intentamos limpiar bloques markdown si los hay.
                cleaned_text = re.sub(r"```json\s*|```", "", texto_generado).strip()
                return self._normalize_report(
                    self._parse_json_response(cleaned_text),
                    grounded_urls=grounded_urls,
                    grounding_sources=grounded_sources,
                )

        except (ConnectionError, TimeoutError) as e:
            if attempt < self.max_retries:
                wait_time = self.retry_delay * (2 ** attempt)
                time.sleep(wait_time)
                return self._generate_with_retries(prediction, processed_news, raw_news, attempt + 1)
            else:
                raise RuntimeError(f"Error de red tras reintentos: {str(e)}") from e
        except Exception as e:
            logger.exception("Error generando evidencia period?stica")
            return self._empty_report(
                f"No se pudo generar evidencia period?stica verificable con Gemini y Google Search Grounding: {type(e).__name__}."
            )

    def _generate_gemini_response(self, prompt: str) -> object:
        configs = [
            {
                "tools": [{"google_search": {}}],
                "response_mime_type": "application/json",
            },
            {
                "tools": [{"google_search": {}}],
            },
        ]

        last_error: Optional[Exception] = None
        for config in configs:
            try:
                return self.client.models.generate_content(
                    model=self.GEMINI_MODEL,
                    contents=prompt,
                    config=config,
                )
            except Exception as exc:
                last_error = exc
                logger.warning("Intento de Gemini fall? con config %s: %s", config, exc)

        raise RuntimeError(f"No se pudo invocar Gemini con Google Search Grounding: {last_error}")

    def _response_text(self, response: object) -> str:
        text = self._read_attr(response, "text")
        if text:
            return str(text)

        candidates = self._read_attr(response, "candidates") or []
        parts_text: list[str] = []
        for candidate in candidates:
            content = self._read_attr(candidate, "content")
            parts = self._read_attr(content, "parts") or []
            for part in parts:
                part_text = self._read_attr(part, "text")
                if part_text:
                    parts_text.append(str(part_text))

        return "\n".join(parts_text).strip()

    @staticmethod
    def _parse_json_response(text: str) -> object:
        cleaned_text = re.sub(r"```json\s*|```", "", text).strip()
        try:
            return json.loads(cleaned_text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", cleaned_text, flags=re.DOTALL)
            if not match:
                raise
            return json.loads(match.group(0))

    def _build_prompt(
        self,
        prediction: MlPrediction,
        raw_news: Optional[RawNews] = None,
        processed_news: Optional[ProcessedNews] = None,
    ) -> str:
        del prediction
        titulo = (raw_news.title_raw or "").strip() if raw_news else ""
        contenido = (raw_news.content_raw or "").strip() if raw_news else ""
        texto_limpio = (processed_news.clean_text or "").strip() if processed_news else ""
        url_original = (raw_news.original_url or "").strip() if raw_news else ""

        if not contenido and texto_limpio:
            contenido = texto_limpio
        elif texto_limpio and texto_limpio not in contenido:
            contenido = f"{contenido}\n\nTexto procesado adicional:\n{texto_limpio}".strip()

        prompt = f"""Act?a como generador de evidencia period?stica para un informe de fact-checking.
Utiliza Google Search Grounding para localizar art?culos period?sticos verificables relacionados con la noticia o publicaci?n indicada.

NOTICIA A INVESTIGAR:
- T?tulo o encabezado: {titulo}
- Contenido o publicaci?n: {contenido}
- URL original, si existe: {url_original}

REGLAS DE B?SQUEDA Y SELECCI?N:
1. Busca evidencia en Internet usando Google Search Grounding.
2. Localiza art?culos period?sticos relacionados con el hecho, declaraci?n o afirmaci?n central.
3. Prioriza medios period?sticos reconocidos: La Rep?blica, El Comercio, Per?21, RPP, Ojo P?blico, Convoca, El B?ho, Epicentro, N60, Gesti?n, Exitosa y Andina.
4. Tambi?n puedes usar verificadores de hechos: Verificador de La Rep?blica, Ojo Bi?nico, AFP Factual, Chequeado, ColombiaCheck o Maldita.es cuando sean pertinentes.
5. No uses como evidencia principal Wikipedia, blogs personales, foros, Reddit, Quora, sitios de contenido generado por usuarios, agregadores autom?ticos, redes sociales ni p?ginas sin autor identificable.
6. Si existen fuentes period?sticas y fuentes no period?sticas, usa ?nicamente las period?sticas.
7. Devuelve URLs directas y limpias del medio; no uses enlaces de Google, Vertex AI Search ni redireccionadores.
8. Si varias fuentes confiables coinciden, dilo en la conclusi?n.
9. Si existen contradicciones entre medios confiables, dilo en la conclusi?n.
10. Si no existe evidencia period?stica suficiente, dilo expl?citamente en la conclusi?n y deja sources vac?o.
11. Todo el JSON debe estar redactado en espa?ol.
12. No traduzcas t?tulos period?sticos. El campo title debe copiar el t?tulo original en espa?ol tal como aparece en el medio o resultado de b?squeda.
13. No inventes ni reformules t?tulos. Si no puedes confirmar el t?tulo exacto, usa el encabezado m?s cercano devuelto por Google Search Grounding en espa?ol.

REGLAS DE REDACCI?N DE LA CONCLUSI?N:
- Debe ser din?mica y basada ?nicamente en las fuentes period?sticas encontradas.
- Debe redactarse de forma impersonal.
- No uses primera persona.
- No menciones al usuario.
- No uses estas expresiones: "encontr?", "busqu?", "verifiqu?", "mi an?lisis", "tu noticia", "tu publicaci?n".
- No generes una conclusi?n gen?rica fija.

FORMATO DE SALIDA:
Responde ?NICAMENTE con un objeto JSON v?lido con esta estructura exacta. No incluyas texto fuera del JSON.

{{
  "sources": [
    {{
      "url": "URL_REAL_DIRECTA_DEL_DIARIO_O_MEDIO",
      "source": "NOMBRE_DEL_MEDIO (ej. La Rep?blica)",
      "title": "T?TULO_REAL_DEL_ART?CULO",
      "excerpt": "FRASE_CORTA QUE RESUMA LA EVIDENCIA RELEVANTE DEL ART?CULO"
    }}
  ],
  "verification_summary": {{
    "supporting_sources": [
      {{
        "source": "NOMBRE_DEL_MEDIO",
        "title": "T?TULO_REAL_DEL_ART?CULO"
      }}
    ],
    "conclusion": "Texto impersonal basado en la evidencia encontrada."
  }}
}}
"""
        return prompt

    def _normalize_report(
        self,
        data: object,
        grounded_urls: Optional[set[str]] = None,
        grounding_sources: Optional[list[dict]] = None,
    ) -> dict:
        if isinstance(data, list):
            data = {"sources": data}
        if not isinstance(data, dict):
            return self._empty_report(
                "No se encontr? evidencia period?stica verificable suficiente en fuentes confiables mediante Google Search Grounding."
            )

        raw_sources = data.get("sources") or []
        sources = [
            self._sanitize_source(source, grounding_sources)
            for source in raw_sources
            if isinstance(source, dict) and self._is_allowed_source(source)
        ]
        sources = [source for source in sources if source]
        if grounded_urls:
            before_grounding_filter = len(sources)
            sources = [
                source for source in sources
                if self._url_was_grounded(source["url"], grounded_urls)
            ]
            if before_grounding_filter and not sources:
                logger.info(
                    "No se aplic? el filtro exacto de grounding porque descartaba todas las fuentes period?sticas."
                )
                sources = [
                    self._sanitize_source(source, grounding_sources)
                    for source in raw_sources
                    if isinstance(source, dict) and self._is_allowed_source(source)
                ]
                sources = [source for source in sources if source]

        if not sources and grounding_sources:
            sources = [
                source
                for source in grounding_sources
                if self._is_allowed_source(source)
            ]

        summary = data.get("verification_summary") or {}
        conclusion = summary.get("conclusion") if isinstance(summary, dict) else None
        if not sources:
            return self._empty_report(
                "No se encontr? evidencia period?stica verificable suficiente en fuentes confiables mediante Google Search Grounding."
            )

        if (
            not conclusion
            or self._has_forbidden_conclusion_terms(conclusion)
            or self._is_insufficient_conclusion(conclusion)
        ):
            conclusion = self._build_default_conclusion(sources)

        return {
            "sources": sources,
            "verification_summary": {
                "supporting_sources": [
                    {"source": source["source"], "title": source["title"]}
                    for source in sources
                ],
                "conclusion": conclusion.strip(),
            },
        }

    def _sanitize_source(
        self,
        source: dict,
        grounding_sources: Optional[list[dict]] = None,
    ) -> Optional[dict]:
        url = str(source.get("url") or "").strip()
        source_name = str(source.get("source") or "").strip()
        title = str(source.get("title") or "").strip()
        excerpt = str(source.get("excerpt") or "").strip()

        if not all([url, source_name, title, excerpt]):
            return None

        if self._looks_english(title):
            title = self._replacement_title(url, grounding_sources) or self._title_from_url(url) or title

        return {
            "url": url,
            "source": source_name,
            "title": title,
            "excerpt": excerpt,
        }

    def _sources_from_grounding(self, response: object) -> list[dict]:
        sources: list[dict] = []
        seen_urls: set[str] = set()
        candidates = self._read_attr(response, "candidates") or []

        for candidate in candidates:
            metadata = self._read_attr(candidate, "grounding_metadata")
            chunks = self._read_attr(metadata, "grounding_chunks") or []
            for chunk in chunks:
                web = self._read_attr(chunk, "web")
                uri = str(self._read_attr(web, "uri") or "").strip()
                title = str(self._read_attr(web, "title") or "").strip()
                if not uri or uri in seen_urls:
                    continue

                source = self._source_name_from_url(uri)
                candidate_source = {
                    "url": uri,
                    "source": source,
                    "title": title or source,
                    "excerpt": (
                        f"Fuente period?stica recuperada por Google Search Grounding: {title}"
                        if title
                        else "Fuente period?stica recuperada por Google Search Grounding."
                    ),
                }
                if self._is_allowed_source(candidate_source):
                    sources.append(candidate_source)
                    seen_urls.add(uri)

        return sources

    def _grounded_urls_from_response(self, response: object) -> set[str]:
        grounded_urls: set[str] = set()
        candidates = self._read_attr(response, "candidates") or []

        for candidate in candidates:
            metadata = self._read_attr(candidate, "grounding_metadata")
            chunks = self._read_attr(metadata, "grounding_chunks") or []
            for chunk in chunks:
                web = self._read_attr(chunk, "web")
                uri = self._read_attr(web, "uri")
                if uri:
                    grounded_urls.add(str(uri).strip())

        return grounded_urls

    def _source_name_from_url(self, url: str) -> str:
        domain = self._domain_from_url(url)
        for source_name, domains in self.JOURNALISTIC_SOURCES.items():
            if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in domains):
                return self._display_source_name(source_name)
        return domain

    def _replacement_title(self, url: str, grounding_sources: Optional[list[dict]]) -> Optional[str]:
        if not grounding_sources:
            return None

        for source in grounding_sources:
            grounded_url = source.get("url", "")
            grounded_title = str(source.get("title") or "").strip()
            if (
                grounded_title
                and not self._looks_english(grounded_title)
                and self._url_was_grounded(url, {grounded_url})
            ):
                return grounded_title

        return None

    @classmethod
    def _title_from_url(cls, url: str) -> Optional[str]:
        path = urlparse(url).path.strip("/")
        if not path:
            return None

        slug = path.split("/")[-1]
        slug = re.sub(r"-noticia/?$", "", slug)
        slug = re.sub(r"\.(html|htm)$", "", slug)
        words = [word for word in slug.split("-") if word]
        if len(words) < 3:
            return None

        small_words = {"a", "al", "ante", "como", "con", "de", "del", "e", "el", "en", "la", "las", "los", "o", "pese", "por", "que", "y"}
        title_words = [
            word if index > 0 and word in small_words else word.capitalize()
            for index, word in enumerate(words)
        ]
        return " ".join(title_words)

    @staticmethod
    def _display_source_name(source_name: str) -> str:
        canonical_names = {
            "andina": "Andina",
            "afp factual": "AFP Factual",
            "chequeado": "Chequeado",
            "colombiacheck": "ColombiaCheck",
            "convoca": "Convoca",
            "el b?ho": "El B?ho",
            "el buho": "El B?ho",
            "el comercio": "El Comercio",
            "epicentro": "Epicentro",
            "exitosa": "Exitosa",
            "gesti?n": "Gesti?n",
            "gestion": "Gesti?n",
            "la rep?blica": "La Rep?blica",
            "la republica": "La Rep?blica",
            "maldita": "Maldita.es",
            "n60": "N60",
            "ojo p?blico": "Ojo P?blico",
            "ojo publico": "Ojo P?blico",
            "ojo bi?nico": "Ojo Bi?nico",
            "ojo bionico": "Ojo Bi?nico",
            "per?21": "Per?21",
            "peru21": "Per?21",
            "rpp": "RPP",
            "verificador": "Verificador de La Rep?blica",
        }
        return canonical_names.get(source_name, source_name.title())

    @staticmethod
    def _read_attr(value: object, attr: str) -> object:
        if value is None:
            return None
        if isinstance(value, dict):
            return value.get(attr)
        return getattr(value, attr, None)

    @classmethod
    def _url_was_grounded(cls, url: str, grounded_urls: set[str]) -> bool:
        normalized_url = cls._normalize_url_for_match(url)
        source_domain = cls._domain_from_url(url)
        return any(
            normalized_url == cls._normalize_url_for_match(grounded_url)
            or source_domain == cls._domain_from_url(grounded_url)
            for grounded_url in grounded_urls
        )

    @staticmethod
    def _normalize_url_for_match(url: str) -> str:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        path = parsed.path.rstrip("/")
        return f"{domain}{path}"

    def _is_allowed_source(self, source: dict) -> bool:
        url = str(source.get("url") or "").strip().lower()
        source_name = str(source.get("source") or "").strip().lower()
        domain = self._domain_from_url(url)

        if not domain or any(domain == blocked or domain.endswith(f".{blocked}") for blocked in self.BLOCKED_DOMAINS):
            return False

        for name, domains in self.JOURNALISTIC_SOURCES.items():
            if name in source_name:
                return True
            if any(domain == allowed or domain.endswith(f".{allowed}") for allowed in domains):
                return True

        return False

    @staticmethod
    def _domain_from_url(url: str) -> str:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    @staticmethod
    def _debug_enabled() -> bool:
        return os.getenv("JUSTIFICATION_DEBUG", "").lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _has_forbidden_conclusion_terms(conclusion: str) -> bool:
        forbidden_terms = (
            "encontr?",
            "busqu?",
            "verifiqu?",
            "mi an?lisis",
            "tu noticia",
            "tu publicaci?n",
        )
        conclusion_lower = conclusion.lower()
        return any(term in conclusion_lower for term in forbidden_terms)

    @staticmethod
    def _looks_english(text: str) -> bool:
        english_markers = {
            " will ",
            " says ",
            " senator-elect",
            " popular renewal",
            " sworn ",
            " i ",
            " as ",
            " the ",
        }
        normalized = f" {text.lower()} "
        return any(marker in normalized for marker in english_markers)

    @staticmethod
    def _is_insufficient_conclusion(conclusion: str) -> bool:
        conclusion_lower = conclusion.lower()
        insufficient_markers = (
            "no se encontr? evidencia",
            "no se encontro evidencia",
            "no existe evidencia",
            "evidencia insuficiente",
            "no hay evidencia",
        )
        return any(marker in conclusion_lower for marker in insufficient_markers)

    @staticmethod
    def _build_default_conclusion(sources: list[dict]) -> str:
        if len(sources) == 1:
            return (
                "La evidencia period?stica disponible se sustenta en un reporte de "
                f"{sources[0]['source']} relacionado con la afirmaci?n analizada."
            )
        source_names = ", ".join(source["source"] for source in sources[:3])
        return (
            "La informaci?n difundida coincide con reportes publicados por varias "
            f"fuentes period?sticas confiables, entre ellas {source_names}, que documentan "
            "elementos relacionados con la afirmaci?n analizada."
        )

    @staticmethod
    def _empty_report(conclusion: str) -> dict:
        return {
            "sources": [],
            "verification_summary": {
                "supporting_sources": [],
                "conclusion": conclusion,
            },
        }

    def clear_cache(self, prediction_id: Optional[int] = None) -> dict:
        if prediction_id is not None:
            existed = prediction_id in self._cache
            self._cache.pop(prediction_id, None)
            return {"cleared": 1 if existed else 0, "cache_size": len(self._cache)}

        cleared = len(self._cache)
        self._cache.clear()
        return {"cleared": cleared, "cache_size": len(self._cache)}

    def get_cache_stats(self) -> dict:
        total_requests = self._cache_stats["hits"] + self._cache_stats["misses"]
        hit_rate = (
            f"{(self._cache_stats['hits'] / total_requests) * 100:.2f}%"
            if total_requests
            else "0.00%"
        )
        return {
            "cache_size": len(self._cache),
            "cache_max_size": self._cache.maxsize,
            "cache_ttl": self.cache_ttl,
            "hits": self._cache_stats["hits"],
            "misses": self._cache_stats["misses"],
            "total_requests": total_requests,
            "hit_rate": hit_rate,
            "model": self.GEMINI_MODEL,
            "max_retries": self.max_retries,
        }
