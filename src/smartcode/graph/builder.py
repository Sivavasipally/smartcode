"""Assemble the compiled StateGraph from nodes + supervisor routing."""
from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from ..config import Settings
from .nodes import GraphNodes
from .state import State
from .supervisor import (
    make_route_after_critic,
    make_route_after_verify,
    route_after_classify,
    route_after_retrieve,
)


def build_graph(nodes: GraphNodes, settings: Settings, checkpointer=None):
    g = StateGraph(State)

    g.add_node("classify_intent", nodes.classify_intent)
    g.add_node("retriever", nodes.retriever)
    g.add_node("planner", nodes.planner)
    g.add_node("coder", nodes.coder)
    g.add_node("verifier", nodes.verifier)
    g.add_node("critic", nodes.critic)
    g.add_node("repair", nodes.repair)
    g.add_node("hitl_gate", nodes.hitl_gate)
    g.add_node("finalize", nodes.finalize)

    g.add_edge(START, "classify_intent")
    g.add_conditional_edges("classify_intent", route_after_classify,
                            ["planner", "retriever", "finalize"])
    g.add_conditional_edges("retriever", route_after_retrieve,
                            ["planner", "critic", "finalize"])
    g.add_edge("planner", "coder")
    g.add_edge("coder", "verifier")
    g.add_conditional_edges("verifier", make_route_after_verify(settings),
                            ["critic", "repair", "finalize"])
    g.add_conditional_edges("critic", make_route_after_critic(settings),
                            ["repair", "hitl_gate", "finalize"])
    g.add_edge("repair", "coder")
    g.add_edge("hitl_gate", "finalize")
    g.add_edge("finalize", END)

    return g.compile(checkpointer=checkpointer)
