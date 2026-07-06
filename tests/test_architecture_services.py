import unittest
from unittest.mock import Mock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.application_services.auth_service import AuthService
from app.application_services.clustering_service import ClusteringService
from app.application_services.pipeline_orchestrator import PipelineOrchestrator
from app.application_services.preprocessing_service import PreprocessingService
from app.application_services.publishing_service import PublishingService
from app.db.database import Base, apply_sqlite_schema_translation
from app.ml.pipeline import ModelNotReadyError
from app.processed.models import ClusterMember, MlPrediction, NewsCluster, Summary
from app.processed.summarizers import LocalModelSummarizer
from app.raw.models import IngestionLog, RawNews, Source
from app.serving.repository import NewsRepository


class ArchitectureServicesTests(unittest.TestCase):
    def setUp(self):
        self.engine = apply_sqlite_schema_translation(
            create_engine(
                "sqlite:///:memory:",
                connect_args={"check_same_thread": False},
            )
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        Base.metadata.create_all(bind=self.engine)
        self.db = self.SessionLocal()

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_auth_service_registers_and_verifies_password(self):
        service = AuthService(self.db)

        user = service.register("alice", "alice@example.com", "super-secret")

        self.assertNotEqual(user.password_hash, "super-secret")
        self.assertTrue(service.verifyPassword("super-secret", user.password_hash))
        self.assertEqual(service.login("alice@example.com", "super-secret").user_id, user.user_id)

    def test_preprocess_cluster_and_publish_pipeline_snapshot(self):
        source = Source(name="Fuente Test", base_url="https://example.com", type="web")
        source.register()
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)

        log = IngestionLog(source_id=source.source_id, ingestion_type="web", status="running")
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)

        raw_items = [
            RawNews(
                source_id=source.source_id,
                log_id=log.log_id,
                platform="web",
                source_account="fuente-test",
                original_url="https://example.com/1",
                title_raw="Congreso aprueba reforma politica",
                content_raw=(
                    "Congreso aprueba reforma politica y debate financiamiento de partidos. "
                    "La medida incluye transparencia de aportes, fiscalizacion electoral, "
                    "rendicion de cuentas, sanciones administrativas, supervision ciudadana, "
                    "informes tecnicos, cronograma parlamentario, reglas para campanas, "
                    "autoridades electorales y nuevas obligaciones para organizaciones politicas. "
                    "Tambien incorpora debates publicos, mecanismos de control, criterios "
                    "de implementacion gradual y evaluaciones periodicas de cumplimiento."
                ),
                status="pending",
            ),
            RawNews(
                source_id=source.source_id,
                log_id=log.log_id,
                platform="web",
                source_account="fuente-test",
                original_url="https://example.com/2",
                title_raw="Reforma politica aprobada por el Congreso",
                content_raw=(
                    "La reforma politica fue aprobada por el Congreso con cambios en "
                    "financiamiento de partidos. El texto plantea transparencia de aportes, "
                    "fiscalizacion electoral, rendicion de cuentas, sanciones administrativas, "
                    "supervision ciudadana, informes tecnicos, reglas para campanas, "
                    "autoridades electorales y obligaciones para organizaciones politicas. "
                    "Tambien incorpora debates publicos, mecanismos de control, criterios "
                    "de implementacion gradual y evaluaciones periodicas de cumplimiento."
                ),
                status="pending",
            ),
            RawNews(
                source_id=source.source_id,
                log_id=log.log_id,
                platform="web",
                source_account="fuente-test",
                original_url="https://example.com/3",
                title_raw="Equipo local gana amistoso",
                content_raw=(
                    "El equipo local gano un amistoso sin relacion con politica. "
                    "El entrenador destaco la preparacion fisica, las variantes tacticas, "
                    "la rotacion de juveniles, el trabajo defensivo, la presion alta, "
                    "la recuperacion de lesionados, los entrenamientos dobles, el analisis "
                    "de video y el calendario deportivo del proximo torneo. Tambien se "
                    "evaluaron juveniles, rutinas de resistencia, jugadas preparadas y "
                    "planes de viaje para los proximos partidos."
                ),
                status="pending",
            ),
        ]
        self.db.add_all(raw_items)
        self.db.commit()

        preprocessing = PreprocessingService(self.db)
        processed_items = [preprocessing.preprocess(item.news_raw_id) for item in raw_items]

        clustering = ClusteringService(self.db, similarity_threshold=0.30)
        clusters = clustering.clusterProcessedNews(source.source_id)
        members = self.db.query(ClusterMember).all()

        self.assertEqual(len(processed_items), 3)
        self.assertEqual(len(clusters), 2)
        self.assertEqual(len(members), 3)

        representative_id = max(
            [cluster.representative_news_processed_id for cluster in clusters if cluster.representative_news_processed_id],
            key=lambda item: item,
        )

        summary = Summary(
            representative_news_processed_id=representative_id,
            summary_text="Resumen de prueba",
            model_version="local-test",
        )
        prediction = MlPrediction(
            representative_news_processed_id=representative_id,
            sentiment_label="discuss",
            sentiment_score=0.77,
            fake_score=0.18,
            model_version="dedicated-components-test",
            fake_label="mostly-true",
            fake_bucket="real",
            raw_probabilities={"stance": {"discuss": 0.77}, "fake_news": {"mostly-true": 0.82}},
        )
        self.db.add(summary)
        self.db.add(prediction)
        self.db.commit()

        publishing = PublishingService(self.db, NewsRepository(self.db))
        published = publishing.publishRepresentative(representative_id)

        self.assertTrue(published.isPublished())
        self.assertEqual(published.summary, "Resumen de prueba")
        self.assertEqual(published.sentiment_label, "discuss")
        self.assertAlmostEqual(float(published.fake_score), 0.18)

    def test_local_model_summarizer_reuses_existing_summary_until_forced(self):
        source = Source(name="Fuente Resumen", base_url="https://resumen.test", type="web")
        source.register()
        self.db.add(source)
        self.db.commit()
        self.db.refresh(source)

        log = IngestionLog(source_id=source.source_id, ingestion_type="web", status="running")
        self.db.add(log)
        self.db.commit()
        self.db.refresh(log)

        content = (
            "Carlos Pareja asumio el cargo en una ceremonia oficial en Palacio de Gobierno. "
            "La Cancilleria anuncio que el nuevo ministro coordinara la agenda diplomatica, "
            "las reuniones bilaterales, la atencion consular, la cooperacion regional, "
            "la representacion ante organismos multilaterales, la seguridad fronteriza, "
            "la integracion comercial y la estrategia internacional del Ejecutivo durante "
            "las proximas semanas de crisis politica y reorganizacion ministerial."
        )
        raw_news = RawNews(
            source_id=source.source_id,
            log_id=log.log_id,
            platform="web",
            source_account="resumen-test",
            original_url="https://resumen.test/1",
            title_raw="Carlos Pareja jura como nuevo ministro de Relaciones Exteriores",
            content_raw=content,
            status="pending",
        )
        self.db.add(raw_news)
        self.db.commit()
        self.db.refresh(raw_news)

        processed = PreprocessingService(self.db).preprocess(raw_news.news_raw_id)
        existing = Summary(
            representative_news_processed_id=processed.news_processed_id,
            summary_text="Resumen existente",
            model_version="local-test",
        )
        self.db.add(existing)
        self.db.commit()
        self.db.refresh(existing)

        summarizer = LocalModelSummarizer(self.db)

        with patch.object(
            LocalModelSummarizer,
            "runInference",
            side_effect=AssertionError("No deberia regenerar un summary existente."),
        ):
            reused = summarizer.generateSummary(processed.news_processed_id)

        self.assertEqual(reused.summary_id, existing.summary_id)
        self.assertEqual(reused.summary_text, "Resumen existente")

        with patch.object(
            LocalModelSummarizer,
            "runInference",
            return_value="Resumen regenerado",
        ) as mock_run_inference:
            regenerated = summarizer.generateSummary(
                processed.news_processed_id,
                force=True,
            )

        self.assertEqual(regenerated.summary_id, existing.summary_id)
        self.assertEqual(regenerated.summary_text, "Resumen regenerado")
        mock_run_inference.assert_called_once()

    def test_pipeline_orchestrator_continues_when_classifier_checkpoint_is_missing(self):
        cluster = NewsCluster(representative_news_processed_id=42, source_id=1)
        cluster.cluster_id = 7

        ingestion = Mock()
        ingestion.ingestFromSource.return_value = []
        preprocessing = Mock()
        clustering = Mock()
        clustering.clusterProcessedNews.return_value = [cluster]
        summarization = Mock()
        prediction = Mock()
        prediction.predictAll.side_effect = ModelNotReadyError("checkpoint missing")
        publishing = Mock()

        published_item = Mock()
        published_item.news_id = 101
        publishing.publishRepresentative.return_value = published_item

        orchestrator = PipelineOrchestrator(
            ingestion,
            preprocessing,
            clustering,
            summarization,
            prediction,
            publishing,
        )

        result = orchestrator.run_source_pipeline(1)

        summarization.generateSummary.assert_called_once_with(42)
        prediction.predictAll.assert_called_once_with(42)
        publishing.publishRepresentative.assert_called_once_with(42)
        self.assertEqual(result["published_count"], 1)
        self.assertEqual(result["published_news_ids"], [101])

    def test_clustering_groups_related_news_across_sources(self):
        source_rpp = Source(name="RPP", base_url="https://rpp.test", type="web")
        source_peru21 = Source(name="Peru21", base_url="https://peru21.test", type="web")
        for source in (source_rpp, source_peru21):
            source.register()
            self.db.add(source)
        self.db.commit()
        self.db.refresh(source_rpp)
        self.db.refresh(source_peru21)

        log_rpp = IngestionLog(source_id=source_rpp.source_id, ingestion_type="web", status="running")
        log_peru21 = IngestionLog(source_id=source_peru21.source_id, ingestion_type="web", status="running")
        self.db.add_all([log_rpp, log_peru21])
        self.db.commit()
        self.db.refresh(log_rpp)
        self.db.refresh(log_peru21)

        related_content_a = (
            "Carlos Pareja asumio la Cancilleria despues de jurar en Palacio de Gobierno. "
            "El Ejecutivo dijo que coordinara embajadas, consulados, comercio exterior, "
            "foros multilaterales, seguridad fronteriza, reuniones bilaterales, cooperacion "
            "regional, agenda diplomatica, dialogo politico, viajes oficiales y la respuesta "
            "institucional frente a la crisis ministerial durante las proximas semanas."
        )
        related_content_b = (
            "La Cancilleria informo que Carlos Pareja juro como nuevo ministro de Relaciones "
            "Exteriores y asumira el servicio exterior, las misiones permanentes, los tratados "
            "internacionales, la proteccion consular, la coordinacion bilateral, la presencia "
            "en cumbres regionales, la representacion multilateral, la politica fronteriza y "
            "la reorganizacion diplomatica del gabinete tras la reciente renuncia ministerial."
        )
        unrelated_content = (
            "El equipo local preparo un amistoso internacional con entrenamientos dobles, "
            "variantes tacticas, recuperacion fisica, sesiones de video, trabajos de pelota "
            "parada, planificacion de viajes, evaluacion medica, observacion de juveniles y "
            "ajustes defensivos antes del partido programado para el fin de semana."
        )

        raw_items = [
            RawNews(
                source_id=source_rpp.source_id,
                log_id=log_rpp.log_id,
                platform="web",
                source_account="rpp-test",
                original_url="https://rpp.test/pareja",
                title_raw="Carlos Pareja jura como nuevo ministro de Relaciones Exteriores",
                content_raw=related_content_a,
                status="pending",
            ),
            RawNews(
                source_id=source_peru21.source_id,
                log_id=log_peru21.log_id,
                platform="web",
                source_account="peru21-test",
                original_url="https://peru21.test/pareja",
                title_raw="Cancilleria: Carlos Pareja juro como nuevo ministro de Relaciones Exteriores",
                content_raw=related_content_b,
                status="pending",
            ),
            RawNews(
                source_id=source_peru21.source_id,
                log_id=log_peru21.log_id,
                platform="web",
                source_account="peru21-test",
                original_url="https://peru21.test/deportes",
                title_raw="Equipo local gana amistoso internacional antes del fin de semana",
                content_raw=unrelated_content,
                status="pending",
            ),
        ]
        self.db.add_all(raw_items)
        self.db.commit()

        preprocessing = PreprocessingService(self.db)
        processed_items = [preprocessing.preprocess(item.news_raw_id) for item in raw_items]

        clustering = ClusteringService(self.db)
        clusters = clustering.clusterProcessedNews(source_rpp.source_id, crossSource=True)
        members = self.db.query(ClusterMember).all()
        cluster_by_processed = {
            member.news_processed_id: member.cluster_id
            for member in members
        }

        self.assertEqual(len(clusters), 2)
        self.assertEqual(len(members), 3)
        self.assertEqual(
            cluster_by_processed[processed_items[0].news_processed_id],
            cluster_by_processed[processed_items[1].news_processed_id],
        )
        self.assertNotEqual(
            cluster_by_processed[processed_items[0].news_processed_id],
            cluster_by_processed[processed_items[2].news_processed_id],
        )


if __name__ == "__main__":
    unittest.main()
