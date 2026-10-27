import unittest
from unittest.mock import Mock

from app.application_services.ingestion_service import IngestionService
from app.raw.ingestion_strategies import TwitterApiIngestion


class TwitterIngestionTests(unittest.TestCase):
    def test_recent_search_maps_author_media_and_query(self):
        response = Mock()
        response.json.return_value = {
            "data": [
                {
                    "id": "123",
                    "text": "Congreso anuncia una medida importante",
                    "author_id": "42",
                    "conversation_id": "123",
                    "created_at": "2026-08-28T18:00:00Z",
                    "attachments": {"media_keys": ["photo-key"]},
                    "referenced_tweets": [{"type": "quoted", "id": "99"}],
                }
            ],
            "includes": {
                "users": [
                    {"id": "42", "username": "cuenta_peruana"},
                    {"id": "7", "username": "medio_oficial"},
                ],
                "tweets": [
                    {
                        "id": "99",
                        "text": "Texto de la noticia que fue citada",
                        "author_id": "7",
                        "created_at": "2026-08-28T17:00:00Z",
                    }
                ],
                "media": [
                    {
                        "media_key": "photo-key",
                        "type": "photo",
                        "url": "https://pbs.twimg.com/media/photo.jpg",
                    }
                ],
            },
        }
        http_client = Mock()
        http_client.get.return_value = response
        service = TwitterApiIngestion(Mock(), apiKey="test-token", httpClient=http_client)

        items = service.searchRecentPosts("Perú Congreso lang:es -is:retweet")

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["account"], "cuenta_peruana")
        self.assertEqual(items[0]["image_url"], "https://pbs.twimg.com/media/photo.jpg")
        self.assertEqual(items[0]["url"], "https://x.com/cuenta_peruana/status/123")
        self.assertEqual(items[0]["social_context"]["conversationId"], "123")
        self.assertEqual(items[0]["social_context"]["completeness"], "referenced_posts_available")
        self.assertEqual(items[0]["social_context"]["references"][0]["type"], "quoted")
        self.assertEqual(
            items[0]["social_context"]["references"][0]["text"],
            "Texto de la noticia que fue citada",
        )
        self.assertEqual(
            http_client.get.call_args.kwargs["params"]["query"],
            "Perú Congreso lang:es -is:retweet",
        )
        self.assertEqual(http_client.get.call_args.kwargs["params"]["max_results"], 10)
        self.assertIn(
            "referenced_tweets",
            http_client.get.call_args.kwargs["params"]["tweet.fields"],
        )
        self.assertIn(
            "referenced_tweets.id",
            http_client.get.call_args.kwargs["params"]["expansions"],
        )

    def test_recent_search_rejects_a_query_over_512_characters(self):
        service = TwitterApiIngestion(Mock(), apiKey="test-token", httpClient=Mock())

        with self.assertRaisesRegex(ValueError, "512"):
            service.searchRecentPosts("x" * 513)

    def test_recent_search_reports_invalid_bearer_token_without_full_url(self):
        response = Mock(status_code=401)
        http_client = Mock()
        http_client.get.return_value = response
        service = TwitterApiIngestion(Mock(), apiKey="invalid-token", httpClient=http_client)

        with self.assertRaisesRegex(ValueError, "401 Unauthorized") as raised:
            service.searchRecentPosts("Perú Congreso lang:es")

        self.assertNotIn("https://api.x.com", str(raised.exception))

    def test_ingestion_failure_message_fits_database_column(self):
        message = IngestionService._bounded_failure_message(RuntimeError("x" * 900))

        self.assertLessEqual(len(message), 500)
        self.assertTrue(message.startswith("RuntimeError: "))


if __name__ == "__main__":
    unittest.main()
