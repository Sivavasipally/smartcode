"""Live, graphical pipeline view for the CLI — the terminal twin of the
Electron flow diagram (``ui/renderer/app.js``).

Renders the nine-stage StateGraph as a row of coloured node boxes joined by
arrows, with a Repair loop underneath, a legend, and a scrolling event
timeline. Node states advance live off the same ``on_event`` stream the
``--verbose`` line trace uses, so the picture stays honest with the run:

    PENDING -> RUNNING -> DONE | FAILED | SKIPPED   (+ Repair LOOP xN)

Usage from the CLI::

    view = PipelineView(console)
    with view:                         # starts the Live display
        agent = CodeAgent(..., on_event=view.handle)
        ...                            # HITL prompts run inside view.paused()

The view falls back to a no-op (plain line trace) when stdout is not a TTY.
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Optional

from rich.box import ROUNDED
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ---------------------------------------------------------------------------
# pipeline model — mirrors NODES / REPAIR / NODE_COLORS in app.js
# ---------------------------------------------------------------------------
NODES = [
    ("classify_intent", "Classify", "intent · skills"),
    ("select_targets",  "Targets",  "scan · propose"),
    ("retriever",       "Retrieve", "symbols · budget"),
    ("planner",         "Plan",     "bounded steps"),
    ("coder",           "Code",     "structured edits"),
    ("verifier",        "Verify",   "AST · lint · tests"),
    ("critic",          "Critique", "LLM judge"),
    ("hitl_gate",       "Gate",     "write approval"),
    ("finalize",        "Finalize", "write · evidence"),
]
REPAIR = ("repair", "Repair", "feedback loop")
CHAIN = [n[0] for n in NODES]  # canonical order; repair sits off-chain

NODE_COLOR = {
    "classify_intent": "#6ea8e8", "select_targets": "#8fb8d8",
    "retriever": "#5db0d0", "planner": "#a58fe0", "coder": "#7bc47b",
    "verifier": "#d9b04a", "critic": "#e08a8a", "repair": "#e0a35d",
    "hitl_gate": "#d3c25b", "finalize": "#69c9a1",
}

# state -> (marker, unicode marker, label, style)
_STATES = {
    "pending": ("o", "○", "PENDING", "grey42"),
    "active":  ("*", "◆", "RUNNING", "bold {color}"),
    "done":    ("+", "✔", "DONE",    "green"),
    "fail":    ("x", "✘", "FAILED",  "bold red"),
    "skip":    ("-", "·", "SKIPPED", "grey30"),
    "loop":    ("~", "↻", "LOOP",    "dark_orange"),
}


class PipelineView:
    """Stateful, live-updating pipeline renderer.

    ``handle(event)`` is the ``on_event`` callback; it advances node states and
    refreshes the Live display. ``paused()`` yields the raw console so
    interactive HITL prompts can run without fighting the Live region.
    """

    TITLE = "PIPELINE"

    def __init__(self, console: Console, *, timeline_rows: int = 10):
        self.console = console
        self.unicode = self._detect_unicode(console)
        self.arrow = "─▶" if self.unicode else "->"
        self.timeline_rows = timeline_rows
        self.state = {nid: "pending" for nid, _, _ in NODES}
        self.state["repair"] = "pending"
        self.badge = {nid: "" for nid in self.state}
        self.events: list[dict] = []
        self.intent = "new"
        self.revisions = 0
        self.elapsed = 0.0
        self._live: Optional[Live] = None

    # -- lifecycle ---------------------------------------------------------
    @staticmethod
    def _detect_unicode(console: Console) -> bool:
        enc = (getattr(console.file, "encoding", "") or "").lower()
        return "utf" in enc

    @property
    def enabled(self) -> bool:
        """The graph is only useful on an interactive terminal."""
        return self.console.is_terminal

    def __enter__(self) -> "PipelineView":
        if self.enabled:
            self._live = Live(self._render(), console=self.console,
                              refresh_per_second=12, transient=False)
            self._live.__enter__()
        return self

    def __exit__(self, *exc) -> None:
        if self._live is not None:
            self._live.update(self._render())
            self._live.__exit__(*exc)
            self._live = None

    @contextmanager
    def paused(self):
        """Stop the Live region for the duration of an interactive prompt,
        then resume with a fresh frame beneath whatever the user typed."""
        live, self._live = self._live, None
        if live is not None:
            live.__exit__(None, None, None)
        try:
            yield self.console
        finally:
            if live is not None and self.enabled:
                self._live = Live(self._render(), console=self.console,
                                  refresh_per_second=12, transient=False)
                self._live.__enter__()

    # -- event handling ----------------------------------------------------
    def handle(self, event: dict) -> None:
        self.events.append(event)
        self.elapsed = event.get("elapsed_s", self.elapsed)
        self._advance(event)
        if self._live is not None:
            self._live.update(self._render())

    def _advance(self, ev: dict) -> None:
        """Port of ``advanceFlow`` in app.js: mark the emitting node, sweep
        skipped predecessors, and light up the predicted next node."""
        node = ev.get("node", "")
        msg = ev.get("message", "") or ""

        if node == "repair":
            m = re.search(r"revision (\d+)", msg)
            if m:
                self.revisions = int(m.group(1))
                self.badge["repair"] = f"×{m.group(1)}"
            self.state["repair"] = "loop"
            # the loop re-runs code -> finalize; reset that tail to pending
            for nid in ("verifier", "critic", "hitl_gate", "finalize"):
                self.state[nid] = "pending"
            self._activate("coder")
            return

        if node == "proposal_gate":
            decision = ev.get("decision") or ""
            if decision == "approve" or "approved" in msg:
                self.state["select_targets"] = "done"
                self._activate("retriever")
            elif decision == "revise" or "revise" in msg:
                m = re.search(r"round (\d+)", msg)
                if m:
                    self.badge["select_targets"] = f"×{m.group(1)}"
                self.state["select_targets"] = "active"
            else:  # reject
                self.state["select_targets"] = "fail"
                self._activate("finalize")
            return

        if node not in self.state:
            return

        # did this node fail?
        failed = (
            (node == "verifier" and ev.get("ok") is False)
            or (node == "hitl_gate" and "rejected" in msg)
            or (node == "finalize" and "rejected" in msg)
            or msg.startswith("failed:") or "failed:" in msg
            or "insufficient context" in msg or "invalid" in msg
            or "no valid targets" in msg or "no source files" in msg
        )
        self.state[node] = "fail" if failed else "done"

        # everything before this node on the chain that never ran was skipped
        self._sweep_skipped(node)

        # contract violation / dead-end -> straight to finalize
        if failed and node in ("classify_intent", "retriever", "hitl_gate",
                               "finalize"):
            if node != "finalize":
                self._activate("finalize")
            return

        # predict the next running node — branches match app.js::advanceFlow
        if node == "classify_intent":
            m = re.search(r"intent=(\w+)", msg)
            self.intent = m.group(1) if m else "new"
            # workspace runs surface a select_targets event of their own; from
            # classify we optimistically route to the single-repo next node and
            # let that event correct us if it arrives.
            if self.intent == "new":
                self.state["select_targets"] = "skip"
                self.state["retriever"] = "skip"
                self._activate("planner")
            else:  # modify / review both go through retrieval first
                self.state["select_targets"] = "skip"
                self._activate("retriever")
        elif node == "select_targets":
            # proposal_gate decides what runs next; keep it live meanwhile
            self.state["select_targets"] = "active"
        elif node == "retriever":
            self._activate("critic" if self.intent == "review" else "planner")
        elif node == "verifier" and ev.get("ok") is False:
            self._activate("repair")
        elif node == "critic":
            if self.intent == "review":
                self.state["hitl_gate"] = "skip"
                self._activate("finalize")
            elif ev.get("revise"):
                self._activate("repair")
            else:
                self._activate("hitl_gate")
        else:
            self._activate_next(node)

    def _activate(self, nid: str) -> None:
        if self.state.get(nid) in (None,):
            return
        if self.state.get(nid) != "done":
            self.state[nid] = "active"

    def _activate_next(self, node: str) -> None:
        try:
            idx = CHAIN.index(node)
        except ValueError:
            return
        if idx + 1 < len(CHAIN):
            self._activate(CHAIN[idx + 1])

    def _sweep_skipped(self, node: str) -> None:
        try:
            idx = CHAIN.index(node)
        except ValueError:
            return
        for nid in CHAIN[:idx]:
            if self.state[nid] == "pending":
                self.state[nid] = "skip"

    # -- rendering ---------------------------------------------------------
    def _marker(self, state: str, color: str) -> tuple[str, str]:
        ascii_m, uni_m, label, style = _STATES[state]
        marker = uni_m if self.unicode else ascii_m
        return marker, style.format(color=color)

    def _node_panel(self, nid: str, title: str, sub: str) -> Panel:
        state = self.state[nid]
        color = NODE_COLOR[nid]
        marker, style = self._marker(state, color)
        _, _, label, _ = _STATES[state]
        badge = self.badge.get(nid) or ""

        head = Text()
        head.append("● " if self.unicode else "* ", style=color)
        head.append(title, style="bold" if state != "pending" else "grey58")
        if badge:
            head.append(f"  {badge}", style="dark_orange")

        inner = self._box_w - 4  # borders + padding
        body = Group(
            head,
            Text(sub[:inner], style="grey42", no_wrap=True),
            Text(f"{marker} {label}", style=style),
        )
        border = color if state in ("active", "loop") else (
            "green" if state == "done" else
            "red" if state == "fail" else "grey30")
        return Panel(body, box=ROUNDED, border_style=border,
                     padding=(0, 1), width=self._box_w)

    _box_w = 22

    def _node_row(self, items: list[tuple[str, str, str]]) -> Table:
        grid = Table.grid()
        arrow = Text("\n\n " + self.arrow, style="grey42")
        cells: list[RenderableType] = []
        for i, (nid, title, sub) in enumerate(items):
            cells.append(self._node_panel(nid, title, sub))
            if i < len(items) - 1:
                cells.append(arrow)
        for _ in cells:
            grid.add_column()
        grid.add_row(*cells)
        return grid

    def _repair_row(self) -> RenderableType:
        panel = self._node_panel(*REPAIR)
        note = Text("\n\n  ↺ Verify / Critique failure  →  feed back  →  Code"
                    if self.unicode else
                    "\n\n  <- Verify / Critique failure -> feed back -> Code",
                    style="grey42")
        grid = Table.grid()
        grid.add_column(); grid.add_column()
        grid.add_row(panel, note)
        return grid

    def _legend(self) -> Text:
        t = Text()
        for key in ("pending", "active", "done", "fail", "skip", "loop"):
            ascii_m, uni_m, label, style = _STATES[key]
            m = uni_m if self.unicode else ascii_m
            st = style.format(color="white") if "{color}" in style else style
            t.append(f"{m} {label}   ", style=st)
        return t

    def _timeline(self) -> RenderableType:
        if not self.events:
            return Text("waiting for events…", style="grey42")
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="right", style="grey42", no_wrap=True)
        table.add_column(no_wrap=True)
        table.add_column(overflow="ellipsis")
        for ev in self.events[-self.timeline_rows:]:
            node = ev.get("node", "?")
            color = NODE_COLOR.get(node, "white")
            table.add_row(
                f"{ev.get('elapsed_s', 0):.1f}s",
                Text(node, style=color),
                Text((ev.get("message") or "")[:96], style="grey62"),
            )
        return table

    def _render(self) -> RenderableType:
        width = max(self.console.width, 40)
        per_row = max(1, (width - 2) // (self._box_w + len(self.arrow) + 2))
        rows: list[RenderableType] = []
        for i in range(0, len(NODES), per_row):
            rows.append(self._node_row(NODES[i:i + per_row]))
        rows.append(Text(""))
        rows.append(self._repair_row())
        rows.append(Text(""))
        rows.append(self._legend())
        rule = "─" if self.unicode else "-"
        rows.append(Text(rule * min(width - 8, 100), style="grey30"))
        rows.append(self._timeline())

        head = Text()
        head.append(self.TITLE, style="bold grey74")
        head.append(f"    {self.elapsed:.1f}s", style="grey42")
        if self.revisions:
            head.append(f"   revisions ×{self.revisions}", style="dark_orange")

        return Panel(Group(*rows), title=head, title_align="left",
                     box=ROUNDED, border_style="grey35", padding=(1, 2))
