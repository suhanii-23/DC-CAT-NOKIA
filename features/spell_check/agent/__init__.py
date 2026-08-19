from .graph import verify_correction, build_spell_check_graph, spell_check_graph


def verify_candidate(
    original: str,
    suggestion: str,
    protected: bool = False,
) -> bool:
    """Run one spelling candidate through the LangGraph verification layer."""

    result = spell_check_graph.invoke(
        {
            "original_sentence": "",
            "corrected_sentence": "",
            "candidate_word": original,
            "suggested_word": suggestion,
            "is_protected": protected,
            "is_valid_correction": False,
            "decision": "",
        }
    )

    return result["is_valid_correction"]