"""Tests for RetrievalService — mapping the KB response into domain objects."""
from unittest.mock import MagicMock, patch

from src.services.retrieval_service import RetrievalService, RetrievedChunk


# A representative bedrock-agent-runtime `retrieve` response.
_FAKE_RESPONSE = {
    "retrievalResults": [
        {
            "content": {"text": "Actions are judged by intentions."},
            "metadata": {
                "citation": "Sahih al-Bukhari 1",
                "source_type": "hadith",
            },
            "score": 0.91,
        },
        {
            "content": {"text": "Allah - there is no deity except Him."},
            "metadata": {"citation": "Quran 2:255", "source_type": "quran"},
            "score": 0.82,
        },
    ]
}


class TestRetrievalService:
    def setup_method(self):
        # Reset the singleton so each test injects its own mock client.
        RetrievalService._client = None

    @patch("src.services.retrieval_service.boto3")
    def test_maps_results_to_chunks(self, mock_boto3):
        mock_client = MagicMock()
        mock_client.retrieve.return_value = _FAKE_RESPONSE
        mock_boto3.client.return_value = mock_client

        chunks = RetrievalService.retrieve("reward of deeds")

        assert len(chunks) == 2
        assert all(isinstance(c, RetrievedChunk) for c in chunks)
        first = chunks[0]
        assert first.citation == "Sahih al-Bukhari 1"
        assert first.source_type == "hadith"
        assert first.text == "Actions are judged by intentions."
        assert first.score == 0.91

    @patch("src.services.retrieval_service.boto3")
    def test_source_type_filter_is_sent(self, mock_boto3):
        """A source_type argument must become an equals filter on the query."""
        mock_client = MagicMock()
        mock_client.retrieve.return_value = {"retrievalResults": []}
        mock_boto3.client.return_value = mock_client

        RetrievalService.retrieve("prayer", source_type="quran", top_k=3)

        _, kwargs = mock_client.retrieve.call_args
        vector_cfg = kwargs["retrievalConfiguration"]["vectorSearchConfiguration"]
        assert vector_cfg["numberOfResults"] == 3
        assert vector_cfg["filter"] == {
            "equals": {"key": "source_type", "value": "quran"}
        }

    @patch("src.services.retrieval_service.boto3")
    def test_missing_fields_default_safely(self, mock_boto3):
        """A malformed result must not raise — fields default, not crash."""
        mock_client = MagicMock()
        mock_client.retrieve.return_value = {"retrievalResults": [{}]}
        mock_boto3.client.return_value = mock_client

        chunks = RetrievalService.retrieve("x")

        assert len(chunks) == 1
        assert chunks[0].text == ""
        assert chunks[0].citation == ""
        assert chunks[0].score == 0.0