from src.services.retrieval_service import RetrievedChunk


class ContextBuilder:
    """Formats retrieved chunks into a prompt-ready context block.

    Single responsibility: presentation of grounded evidence for the LLM.
    Kept separate from RetrievalService (which fetches) and ConversationChain
    (which orchestrates) so citation formatting can evolve independently.
    """

    @staticmethod
    def build(chunks: list[RetrievedChunk]) -> str:
        """Render chunks as bracketed, citable evidence lines.

        Produces, e.g.:
            [Quran 2:255] Allah - there is no deity except Him...
            [Sahih al-Bukhari 1] Actions are judged by intentions...

        The bracketed citation is what the model reuses inline in its answer.
        Returns a sentinel string when there is no grounding, so the prompt can
        instruct the model to fall back gracefully instead of fabricating.
        """
        if not chunks:
            return "(No relevant sources were found in the knowledge base.)"

        return "\n\n".join(f"[{c.citation}] {c.text}" for c in chunks)