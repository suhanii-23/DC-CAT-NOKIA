from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from .state import SpellCheckState


def verify_correction(state: SpellCheckState) -> SpellCheckState:
    """Verify whether the proposed correction should be accepted."""

    if state.get("is_protected", False):
        return {
            **state,
            "is_valid_correction": False,
            "decision": "reject_protected_term",
        }

    original = state.get("candidate_word", "")
    suggested = state.get("suggested_word", "")

    if not original or not suggested:
        return {
            **state,
            "is_valid_correction": False,
            "decision": "reject_invalid_candidate",
        }

    if original.lower() == suggested.lower():
        return {
            **state,
            "is_valid_correction": False,
            "decision": "reject_no_change",
        }

    return {
        **state,
        "is_valid_correction": True,
        "decision": "accept",
    }


def build_spell_check_graph():
    """Build and compile the spell-check verification graph."""

    builder = StateGraph(SpellCheckState)

    builder.add_node("verify_correction", verify_correction)

    builder.add_edge(START, "verify_correction")
    builder.add_edge("verify_correction", END)

    return builder.compile()


spell_check_graph = build_spell_check_graph()