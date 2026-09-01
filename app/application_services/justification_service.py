"""
Servicio de fuentes relacionadas usando Gemini con Google Search Grounding.
Fuerza al modelo a generar una respuesta JSON estructurada con fuentes periodísticas reales.
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

import requests
from bs4 import BeautifulSoup
from google import genai
from cachetools import TTLCache
from sqlalchemy.orm import Session

from app.interfaces.justification_service import IJustificationService
from app.processed.models import JustificationSource, MlPrediction, ProcessedNews
from app.raw.models import RawNews
from app.serving.models import PublishedNews

logger = logging.getLogger(__name__)


class GeminiJustificationService(IJustificationService):
    GEMINI_MODEL = "gemini-2.5-flash"
    MAX_DEBUG_TEXT_LENGTH = 4000
    URL_CHECK_TIMEOUT_SECONDS = 8
    URL_CHECK_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    JOURNALISTIC_SOURCES = {
        "andina": ("andina.pe",),
        "afp factual": ("factual.afp.com",),
        "chequeado": ("chequeado.com",),
        "colombiacheck": ("colombiacheck.com",),
        "convoca": ("convoca.pe",),
        "el búho": ("elbuho.pe",),
        "el buho": ("elbuho.pe",),
        "el comercio": ("elcomercio.pe",),
        "epicentro": ("epicentro.tv",),
        "exitosa": ("exitosanoticias.pe",),
        "gestión": ("gestion.pe",),
        "gestion": ("gestion.pe",),
        "la república": ("larepublica.pe",),
        "la republica": ("larepublica.pe",),
        "maldita": ("maldita.es",),
        "n60": ("n60.pe",),
        "ojo público": ("ojo-publico.com",),
        "ojo publico": ("ojo-publico.com",),
        "ojo biónico": ("ojo-publico.com",),
        "ojo bionico": ("ojo-publico.com",),
        "perú21": ("peru21.pe",),
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
        self.model_name = os.getenv("JUSTIFICATION_MODEL", self.GEMINI_MODEL)
        self.max_sources = self._configured_max_sources()

        self._cache: TTLCache = TTLCache(maxsize=1000, ttl=cache_ttl)
        self._cache_stats = {"hits": 0, "misses": 0}

        api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=api_key) if api_key else None
        if self.client:
            logger.info(
                "GeminiJustificationService inicializado como generador de fuentes relacionadas."
            )
        else:
            logger.info("GeminiJustificationService inicializado en modo solo lectura (sin GEMINI_API_KEY).")

    @staticmethod
    def _serialize_source_row(row: JustificationSource) -> dict:
        return {
            "url": row.url,
            "source": row.source,
            "title": row.title,
            "excerpt": row.excerpt,
        }

    def persist_sources(
        self,
        prediction_id: int,
        sources: list[dict],
        model_used: str,
    ) -> list[dict]:
        self.db.query(JustificationSource).filter(
            JustificationSource.prediction_id == prediction_id
        ).delete(synchronize_session=False)

        created_at = datetime.utcnow()
        persisted: list[dict] = []
        for source in sources:
            row = JustificationSource(
                prediction_id=prediction_id,
                url=source["url"],
                source=source["source"],
                title=source["title"],
                excerpt=source["excerpt"],
                model_used=model_used,
                created_at=created_at,
            )
            self.db.add(row)
            persisted.append(source)

        self.db.commit()
        return persisted

    def get_sources_by_prediction_id(self, prediction_id: int) -> list[dict]:
        rows = (
            self.db.query(JustificationSource)
            .filter(JustificationSource.prediction_id == prediction_id)
            .order_by(JustificationSource.justification_source_id)
            .all()
        )
        return [self._serialize_source_row(row) for row in rows]

    def get_sources_by_news_id(self, news_id: int) -> list[dict]:
        news = self.db.query(PublishedNews).filter(PublishedNews.news_id == news_id).first()
        if not news:
            return []

        prediction = (
            self.db.query(MlPrediction)
            .filter(
                MlPrediction.representative_news_processed_id == news.representative_news_processed_id
            )
            .first()
        )
        if not prediction:
            return []

        return self.get_sources_by_prediction_id(prediction.prediction_id)

    def _build_response_from_prediction(
        self,
        prediction: MlPrediction,
        sources: list[dict],
        *,
        from_cache: bool = False,
        generated_at: Optional[datetime] = None,
    ) -> dict:
        return {
            "prediction_id": prediction.prediction_id,
            "sources": sources,
            "ml_prediction": {
                "fake_score": float(prediction.fake_score),
                "sentiment_label": prediction.sentiment_label,
            },
            "from_cache": from_cache,
            "generated_at": (generated_at or datetime.utcnow()).isoformat(),
            "model_used": self.model_name,
        }

    def get_persisted_justification(self, prediction_id: int) -> Optional[dict]:
        return self._load_persisted_response(prediction_id)

    def get_persisted_justification_by_news_id(self, news_id: int) -> Optional[dict]:
        news = self.db.query(PublishedNews).filter(PublishedNews.news_id == news_id).first()
        if not news:
            return None

        prediction = (
            self.db.query(MlPrediction)
            .filter(
                MlPrediction.representative_news_processed_id
                == news.representative_news_processed_id
            )
            .first()
        )
        if not prediction:
            return None
        return self._load_persisted_response(prediction.prediction_id)

    def _load_persisted_response(self, prediction_id: int) -> Optional[dict]:
        prediction = self.db.query(MlPrediction).filter(
            MlPrediction.prediction_id == prediction_id
        ).first()
        if not prediction:
            return None

        rows = (
            self.db.query(JustificationSource)
            .filter(JustificationSource.prediction_id == prediction_id)
            .order_by(JustificationSource.justification_source_id)
            .all()
        )
        if not rows:
            return None

        return self._build_response_from_prediction(
            prediction,
            [self._serialize_source_row(row) for row in rows],
            from_cache=True,
            generated_at=rows[0].created_at,
        )

    def generate_justification_safe(
        self,
        prediction_id: int,
        include_context: bool = True,
        regenerate: bool = False,
    ) -> Optional[dict]:
        try:
            return self.generate_justification(
                prediction_id=prediction_id,
                include_context=include_context,
                regenerate=regenerate,
            )
        except Exception as exc:
            logger.warning(
                "Justificación omitida para predicción %s: %s",
                prediction_id,
                exc,
            )
            return None

    def generate_justification(
        self,
        prediction_id: int,
        include_context: bool = True,
        regenerate: bool = False,
    ) -> dict:
        """
        Busca fuentes periodísticas relacionadas y las devuelve estructuradas en JSON.
        """
        if not regenerate:
            if prediction_id in self._cache:
                self._cache_stats["hits"] += 1
                cached = self._cache[prediction_id].copy()
                cached["from_cache"] = True
                return cached

            persisted = self._load_persisted_response(prediction_id)
            if persisted:
                self._cache[prediction_id] = persisted.copy()
                self._cache_stats["hits"] += 1
                return persisted

        self._cache_stats["misses"] += 1

        prediction = self.db.query(MlPrediction).filter(
            MlPrediction.prediction_id == prediction_id
        ).first()

        if not prediction:
            raise ValueError(f"Predicción con ID {prediction_id} no encontrada")

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

        evidence_report = self._generate_with_retries(
            prediction=prediction,
            processed_news=processed if include_context else None,
            raw_news=raw_news if include_context else None,
        )

        sources = evidence_report["sources"]
        self.persist_sources(prediction_id, sources, self.model_name)

        response = self._build_response_from_prediction(prediction, sources, from_cache=False)
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
                raise ValueError("Respuesta vacía de Gemini")

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
                    excluded_urls=self._excluded_original_urls(raw_news, prediction),
                )
            except json.JSONDecodeError:
                # Si por alguna razón no es JSON válido, intentamos limpiar bloques markdown si los hay.
                cleaned_text = re.sub(r"```json\s*|```", "", texto_generado).strip()
                return self._normalize_report(
                    self._parse_json_response(cleaned_text),
                    grounded_urls=grounded_urls,
                    grounding_sources=grounded_sources,
                    excluded_urls=self._excluded_original_urls(raw_news, prediction),
                )

        except (ConnectionError, TimeoutError) as e:
            if attempt < self.max_retries:
                wait_time = self.retry_delay * (2 ** attempt)
                time.sleep(wait_time)
                return self._generate_with_retries(prediction, processed_news, raw_news, attempt + 1)
            else:
                raise RuntimeError(f"Error de red tras reintentos: {str(e)}") from e
        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("Error generando fuentes periodísticas relacionadas")
            raise RuntimeError(
                f"No se pudieron generar fuentes periodísticas con Gemini: {type(e).__name__}."
            ) from e

    def _generate_gemini_response(self, prompt: str) -> object:
        if self.client is None:
            raise RuntimeError("GEMINI_API_KEY no configurada para generar justificaciones.")

        config = {"tools": [{"google_search": {}}]}

        try:
            return self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            message = str(exc)
            if "429" in message or "RESOURCE_EXHAUSTED" in message:
                raise RuntimeError(
                    "Cuota de Gemini agotada. Espera unos minutos o revisa tu plan en Google AI Studio."
                ) from exc
            raise RuntimeError(
                f"No se pudo invocar Gemini con Google Search Grounding: {exc}"
            ) from exc

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

        prompt = f"""Actúa como asistente de investigación periodística para una aplicación de alfabetización informativa.
Utiliza Google Search Grounding para localizar artículos periodísticos verificables relacionados con la noticia o publicación indicada.
El objetivo NO es emitir un veredicto final, sino ofrecer al usuario fuentes útiles para investigar por su cuenta.

NOTICIA A INVESTIGAR:
- Título o encabezado: {titulo}
- Contenido o publicación: {contenido}
- URL original, si existe: {url_original}

REGLAS DE BÚSQUEDA Y SELECCIÓN:
1. Busca evidencia en Internet usando Google Search Grounding.
2. Localiza artículos periodísticos relacionados con el hecho, declaración o afirmación central.
3. Prioriza medios periodísticos reconocidos del país o región mencionados en el texto. Para Perú, prioriza La República, El Comercio, Perú21, RPP, Ojo Público, Convoca, El Búho, Epicentro, N60, Gestión, Exitosa y Andina.
4. También puedes usar verificadores de hechos: Verificador de La República, Ojo Biónico, AFP Factual, Chequeado, ColombiaCheck o Maldita.es cuando sean pertinentes.
5. No uses como evidencia principal Wikipedia, blogs personales, foros, Reddit, Quora, sitios de contenido generado por usuarios, agregadores automáticos, redes sociales ni páginas sin autor identificable.
6. Si existen fuentes periodísticas y fuentes no periodísticas, usa únicamente las periodísticas.
7. Devuelve URLs directas y limpias del medio; no uses enlaces de Google, Vertex AI Search ni redireccionadores.
8. No incluyas la URL original indicada arriba como fuente relacionada. Busca otras coberturas, contexto o verificaciones independientes.
9. Selecciona entre 1 y {self.max_sources} fuentes como máximo. Prefiere diversidad de medios antes que repetir la misma cobertura.
10. Si no existe evidencia periodística suficiente o los resultados no están claramente relacionados, deja sources vacío.
11. Cada excerpt debe explicar de forma neutral por qué esa fuente ayuda a investigar el tema, sin afirmar que la publicación original es verdadera o falsa.
12. Todo el JSON debe estar redactado en español.
13. No traduzcas títulos periodísticos. El campo title debe copiar el título original en español tal como aparece en el medio o resultado de búsqueda.
14. No inventes ni reformules títulos. Si no puedes confirmar el título exacto, usa el encabezado más cercano devuelto por Google Search Grounding en español.

FORMATO DE SALIDA:
Responde ÚNICAMENTE con un objeto JSON válido con esta estructura exacta. No incluyas texto fuera del JSON.
No generes conclusiones, resúmenes narrativos ni texto adicional fuera de las fuentes.

{{
  "sources": [
    {{
      "url": "URL_REAL_DIRECTA_DEL_DIARIO_O_MEDIO",
      "source": "NOMBRE_DEL_MEDIO (ej. La República)",
      "title": "TÍTULO_REAL_DEL_ARTÍCULO",
      "excerpt": "FRASE_CORTA QUE RESUMA LA EVIDENCIA RELEVANTE DEL ARTÍCULO"
    }}
  ]
}}
"""
        return prompt

    def _normalize_report(
        self,
        data: object,
        grounded_urls: Optional[set[str]] = None,
        grounding_sources: Optional[list[dict]] = None,
        excluded_urls: Optional[set[str]] = None,
    ) -> dict:
        if isinstance(data, list):
            data = {"sources": data}
        if not isinstance(data, dict):
            return self._empty_report()

        raw_sources = data.get("sources") or []
        sources = [
            self._sanitize_source(source, grounding_sources)
            for source in raw_sources
            if isinstance(source, dict) and self._is_allowed_source(source)
        ]
        sources = [source for source in sources if source]
        sources = self._exclude_original_sources(sources, excluded_urls)
        sources = self._filter_reachable_sources(sources)
        if grounded_urls:
            before_grounding_filter = len(sources)
            sources = [
                source for source in sources
                if self._url_was_grounded(source["url"], grounded_urls)
            ]
            if before_grounding_filter and not sources:
                logger.info(
                    "No se aplicó el filtro exacto de grounding porque descartaba todas las fuentes periodísticas."
                )
                sources = [
                    self._sanitize_source(source, grounding_sources)
                    for source in raw_sources
                    if isinstance(source, dict) and self._is_allowed_source(source)
                ]
                sources = [source for source in sources if source]
                sources = self._exclude_original_sources(sources, excluded_urls)
                sources = self._filter_reachable_sources(sources)

        if not sources and grounding_sources:
            sources = [
                source
                for source in grounding_sources
                if self._is_allowed_source(source)
            ]
            sources = self._exclude_original_sources(sources, excluded_urls)
            sources = self._filter_reachable_sources(sources)

        if not sources:
            return self._empty_report()

        return {"sources": sources[: self.max_sources]}

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

        grounded_match = self._matching_grounding_source(url, title, grounding_sources)
        if grounded_match:
            url = grounded_match["url"]
            source_name = grounded_match.get("source") or source_name
            grounded_title = str(grounded_match.get("title") or "").strip()
            if grounded_title and not self._looks_english(grounded_title):
                title = grounded_title

        if self._looks_english(title):
            title = self._replacement_title(url, grounding_sources) or self._title_from_url(url) or title

        return {
            "url": url,
            "source": source_name,
            "title": title,
            "excerpt": excerpt,
        }

    def _filter_reachable_sources(self, sources: list[dict]) -> list[dict]:
        if os.getenv("JUSTIFICATION_VALIDATE_URLS", "true").lower() not in {
            "1",
            "true",
            "yes",
            "on",
        }:
            return sources

        reachable: list[dict] = []
        seen_urls: set[str] = set()
        for source in sources:
            url = source["url"]
            normalized = self._normalize_url_for_match(url)
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            if self._is_valid_source_url(url, source["title"]):
                reachable.append(source)
            else:
                logger.info("Fuente descartada por URL no verificable: %s", url)
        return reachable

    @classmethod
    def _is_valid_source_url(cls, url: str, expected_title: str) -> bool:
        response = cls._fetch_source_response(url)
        if response is None:
            return False

        status = response.status_code
        if status in {401, 403}:
            return True
        if not 200 <= status < 400:
            return False

        actual_title = cls._extract_page_title(response.text)
        if not actual_title:
            return True

        return cls._title_overlap(expected_title, actual_title) >= 0.35

    @classmethod
    def _fetch_source_response(cls, url: str) -> Optional[requests.Response]:
        try:
            response = requests.get(
                url,
                allow_redirects=True,
                timeout=cls.URL_CHECK_TIMEOUT_SECONDS,
                headers=cls.URL_CHECK_HEADERS,
                stream=True,
            )
            response._content = response.raw.read(120_000, decode_content=True)
            return response
        except requests.RequestException:
            return None

    @staticmethod
    def _extract_page_title(html: str) -> str:
        soup = BeautifulSoup(html or "", "html.parser")
        for selector in (
            'meta[property="og:title"]',
            'meta[name="twitter:title"]',
            "h1",
            "title",
        ):
            element = soup.select_one(selector)
            if not element:
                continue
            value = element.get("content") if element.name == "meta" else element.get_text(" ")
            value = re.sub(r"\s+", " ", value or "").strip()
            if value:
                return value
        return ""

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
                        f"Fuente periodística recuperada por Google Search Grounding: {title}"
                        if title
                        else "Fuente periodística recuperada por Google Search Grounding."
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

    def _matching_grounding_source(
        self,
        url: str,
        title: str,
        grounding_sources: Optional[list[dict]],
    ) -> Optional[dict]:
        if not grounding_sources:
            return None

        normalized_url = self._normalize_url_for_match(url)
        domain = self._domain_from_url(url)
        best_source = None
        best_score = 0.0
        for source in grounding_sources:
            grounded_url = str(source.get("url") or "").strip()
            if not grounded_url:
                continue
            if normalized_url == self._normalize_url_for_match(grounded_url):
                return source
            if domain != self._domain_from_url(grounded_url):
                continue
            score = self._title_overlap(title, str(source.get("title") or ""))
            if score > best_score:
                best_score = score
                best_source = source

        if best_source and best_score >= 0.45:
            return best_source
        return None

    @staticmethod
    def _title_overlap(left: str, right: str) -> float:
        left_tokens = {
            token
            for token in re.findall(r"\w+", (left or "").casefold(), flags=re.UNICODE)
            if len(token) >= 4
        }
        right_tokens = {
            token
            for token in re.findall(r"\w+", (right or "").casefold(), flags=re.UNICODE)
            if len(token) >= 4
        }
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / max(len(left_tokens), 1)

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
            "el búho": "El Búho",
            "el buho": "El Búho",
            "el comercio": "El Comercio",
            "epicentro": "Epicentro",
            "exitosa": "Exitosa",
            "gestión": "Gestión",
            "gestion": "Gestión",
            "la república": "La República",
            "la republica": "La República",
            "maldita": "Maldita.es",
            "n60": "N60",
            "ojo público": "Ojo Público",
            "ojo publico": "Ojo Público",
            "ojo biónico": "Ojo Biónico",
            "ojo bionico": "Ojo Biónico",
            "perú21": "Perú21",
            "peru21": "Perú21",
            "rpp": "RPP",
            "verificador": "Verificador de La República",
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
        return any(
            normalized_url == cls._normalize_url_for_match(grounded_url)
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

    def _excluded_original_urls(
        self,
        raw_news: Optional[RawNews],
        prediction: MlPrediction,
    ) -> set[str]:
        urls: set[str] = set()
        if raw_news is not None and raw_news.original_url:
            urls.add(raw_news.original_url.strip())

        published = (
            self.db.query(PublishedNews)
            .filter(
                PublishedNews.representative_news_processed_id
                == prediction.representative_news_processed_id
            )
            .first()
        )
        if published is not None and published.original_url:
            urls.add(published.original_url.strip())

        return urls

    @classmethod
    def _exclude_original_sources(
        cls,
        sources: list[dict],
        excluded_urls: Optional[set[str]],
    ) -> list[dict]:
        if not excluded_urls:
            return sources
        return [
            source
            for source in sources
            if not any(cls._same_url(source["url"], excluded_url) for excluded_url in excluded_urls)
        ]

    @classmethod
    def _same_url(cls, left: str, right: str) -> bool:
        return cls._normalize_url_for_match(left) == cls._normalize_url_for_match(right)

    @staticmethod
    def _configured_max_sources() -> int:
        raw_value = os.getenv("JUSTIFICATION_MAX_SOURCES", "4")
        try:
            value = int(raw_value)
        except ValueError:
            logger.warning(
                "JUSTIFICATION_MAX_SOURCES inválido (%s); usando 4.",
                raw_value,
            )
            return 4
        return max(1, min(value, 8))

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
    def _empty_report() -> dict:
        return {"sources": []}

    def clear_cache(self, prediction_id: Optional[int] = None) -> dict:
        db_cleared = 0
        if prediction_id is not None:
            existed = prediction_id in self._cache
            self._cache.pop(prediction_id, None)
            db_cleared = (
                self.db.query(JustificationSource)
                .filter(JustificationSource.prediction_id == prediction_id)
                .delete(synchronize_session=False)
            )
            self.db.commit()
            return {
                "cleared": 1 if existed else 0,
                "db_cleared": db_cleared,
                "cache_size": len(self._cache),
            }

        cleared = len(self._cache)
        self._cache.clear()
        db_cleared = self.db.query(JustificationSource).delete(synchronize_session=False)
        self.db.commit()
        return {
            "cleared": cleared,
            "db_cleared": db_cleared,
            "cache_size": len(self._cache),
        }

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
            "model": self.model_name,
            "max_sources": self.max_sources,
            "max_retries": self.max_retries,
        }
