import unittest
from unittest.mock import Mock

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
                    "created_at": "2026-08-28T18:00:00Z",
                    "attachments": {"media_keys": ["photo-key"]},
                }
            ],
            "includes": {
                "users": [{"id": "42", "username": "cuenta_peruana"}],
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
        self.assertEqual(
            http_client.get.call_args.kwargs["params"]["query"],
            "Perú Congreso lang:es -is:retweet",
        )
        self.assertEqual(http_client.get.call_args.kwargs["params"]["max_results"], 10)

    def test_recent_search_rejects_a_query_over_512_characters(self):
        service = TwitterApiIngestion(Mock(), apiKey="test-token", httpClient=Mock())

        with self.assertRaisesRegex(ValueError, "512"):
            service.searchRecentPosts("x" * 513)


if __name__ == "__main__":
    unittest.main()
