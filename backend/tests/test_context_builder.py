"""Tests for ContextBuilder — formatting retrieved chunks for the prompt."""
from src.services.retrieval_service import RetrievedChunk
from src.services.context_builder import ContextBuilder


class TestContextBuilder:
    def test_empty_returns_sentinel(self):
        """No chunks → a sentinel so the prompt can instruct graceful fallback."""
        result = ContextBuilder.build([])
        assert "No relevant sources" in result

    def test_formats_bracketed_citations(self):
        """Each chunk renders as '[citation] text', joined by blank lines."""
        chunks = [
            RetrievedChunk(
                text="Actions are judged by intentions.",
                citation="Sahih al-Bukhari 1",
                source_type="hadith",
                score=0.9,
            ),
            RetrievedChunk(
                text="Allah - there is no deity except Him.",
                citation="Quran 2:255",
                source_type="quran",
                score=0.8,
            ),
        ]
        result = ContextBuilder.build(chunks)

        assert "[Sahih al-Bukhari 1] Actions are judged by intentions." in result
        assert "[Quran 2:255] Allah - there is no deity except Him." in result
        # blank-line separated
        assert "\n\n" in result