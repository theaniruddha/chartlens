"""Patient Investigator: a bounded LangGraph supervisor over specialist nodes.

Topology:
    load_context -> scan_signals -> make_hypotheses -> supervisor
    supervisor -> (investigate_trend | investigate_plan | investigate_coverage) -> supervisor
    supervisor -> finalize (deferral suppression + evidence gate + emit)

Budgets are enforced in state, not prompts: max 9 tool calls, max depth 2 per
hypothesis, max 3 investigated hypotheses (parallel branches). The supervisor
is the only routing node and routing is deterministic (typed hypotheses have a
fixed priority), so model calls are reserved for semantic verification needs.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from app.analytics.trends import DEFAULT_SLOPE_THRESHOLD, SLOPE_THRESHOLDS
from app.db.repository import ChartRepository
from app.note_review.engine import TOPIC_LABELS
from app.note_review.extract import extract_note_facts
from app.schemas.items import DEFAULT_LIMITATIONS, ReviewItem, validate_item
from app.timeutil import utc_iso
from app.tools.semantic_tools import TOOLS

MAX_TOOL_CALLS = 9
MAX_DEPTH = 2
MAX_BRANCHES = 3
MAX_ITEMS = 4

_PRIORITY = {"trend": 0, "unresolved_plan": 1, "coverage_gap": 2, "symptom_followup": 3}


class InvestigatorState(TypedDict, total=False):
    patient_id: str
    current_note: str
    hypotheses: list[dict]
    findings: list[dict]
    deferred_topics: dict[str, dict]
    replanned_topics: list[str]
    tool_calls_used: int
    branches_used: int
    steps: list[dict]
    stop_reason: str | None
    next_hypothesis: int | None
    snapshots: list[dict]
    draft_deferred_topics: list[str]
    items: list[dict]
    coverage_report: dict
    signal_synthesis: dict | None


class ToolRunner:
    """Budget-enforcing tool executor shared by all nodes in one run."""

    def __init__(self, repo: ChartRepository):
        self.repo = repo

    def call(self, state: InvestigatorState, node: str, tool: str, **kwargs) -> dict | None:
        if state["tool_calls_used"] >= MAX_TOOL_CALLS:
            state["stop_reason"] = "budget_exhausted"
            return None
        tool_fn: Any = TOOLS[tool]
        result = tool_fn(self.repo, **kwargs)
        state["tool_calls_used"] += 1
        state["steps"].append(
            {
                "node": node,
                "action": tool,
                "detail": str(kwargs) if kwargs else None,
                "payload": result,
            }
        )
        return result


def build_graph(repo: ChartRepository, provider: Any = None):
    tools = ToolRunner(repo)

    def load_context(state: InvestigatorState) -> InvestigatorState:
        state.setdefault("tool_calls_used", 0)
        state.setdefault("branches_used", 0)
        state.setdefault("steps", [])
        state.setdefault("findings", [])
        state.setdefault("hypotheses", [])
        state.setdefault("stop_reason", None)
        tools.call(state, "load_context", "get_patient_brief")
        tools.call(state, "load_context", "get_coverage")
        now = datetime.now(UTC)
        state["deferred_topics"] = {
            d.topic: {
                "evidence_id": d.source_resource_id,
                "note_id": d.evidence_note_id,
                "deferred_until": utc_iso(d.deferred_until),
                "reason": d.reason,
            }
            for d in repo.active_deferrals()
            if d.deferred_until is None or d.deferred_until > now
        }
        facts = extract_note_facts(state.get("current_note") or "")
        state["replanned_topics"] = [p.topic for p in facts.plan_items if p.topic]
        state["draft_deferred_topics"] = [d.topic for d in facts.deferrals if d.topic]
        return state

    def scan_signals(state: InvestigatorState) -> InvestigatorState:
        snaps = tools.call(state, "scan_signals", "get_metric_snapshots") or {"snapshots": []}
        state["snapshots"] = snaps["snapshots"]
        return state

    def make_hypotheses(state: InvestigatorState) -> InvestigatorState:
        hyps: list[dict] = []

        for snap in state.get("snapshots", []):
            slope = snap.get("slope_per_month")
            n = snap.get("n_points") or 0
            if slope is None or n < 3:
                continue
            threshold = SLOPE_THRESHOLDS.get(snap["metric_code"], DEFAULT_SLOPE_THRESHOLD)
            if abs(slope) > threshold:
                hyps.append(
                    {
                        "type": "trend",
                        "metric_code": snap["metric_code"],
                        "display": snap["display"],
                        "snapshot": snap,
                        "status": "pending",
                        "depth": 0,
                    }
                )

        plans = tools.call(state, "make_hypotheses", "get_recent_plan_candidates")
        seen_topics: set[str] = set()
        for cand in (plans or {"candidates": []})["candidates"]:
            topic = cand["topic"]
            if not topic or topic in seen_topics:
                continue
            seen_topics.add(topic)
            if topic in state["replanned_topics"]:
                continue
            if topic in state.get("draft_deferred_topics", []):
                # The draft note itself defers this topic: suppressed, and no
                # chart-deferral item is emitted (there is no chart evidence).
                hyps.append(
                    {"type": "plan", "topic": topic, "candidate": cand,
                     "status": "suppressed_draft", "depth": 0}
                )
                continue
            if topic in state["deferred_topics"]:
                hyps.append(
                    {"type": "plan", "topic": topic, "candidate": cand, "status": "suppressed",
                     "depth": 0}
                )
                continue
            hyps.append(
                {"type": "plan", "topic": topic, "candidate": cand, "status": "pending",
                 "depth": 0}
            )

        facts = extract_note_facts(state.get("current_note") or "")
        covered = {s["metric_code"] for s in state.get("snapshots", [])}
        for claim in facts.metric_claims:
            if claim.metric_code not in covered:
                hyps.append(
                    {
                        "type": "coverage",
                        "metric_code": claim.metric_code,
                        "raw_term": claim.raw_term,
                        "qualifier": claim.qualifier,
                        "status": "pending",
                        "depth": 0,
                    }
                )

        # Symptom mentions (prior notes via the tool payload + the draft note)
        # become hypotheses unless a plan item already addresses them.
        plan_texts = " ".join(
            [c["plan_text"].lower() for c in (plans or {"candidates": []})["candidates"]]
            + [pitem.text.lower() for pitem in facts.plan_items]
        )
        seen_symptoms: set[str] = set()
        prior_symptoms = (plans or {}).get("symptoms", [])
        for sym in prior_symptoms + [
            {"term": m.term, "category": m.category, "evidence_id": None, "note_time": None}
            for m in facts.symptoms
        ]:
            if sym["category"] in seen_symptoms:
                continue
            seen_symptoms.add(sym["category"])
            if sym["term"] in plan_texts:
                continue  # already addressed by a plan item
            hyps.append(
                {
                    "type": "symptom",
                    "term": sym["term"],
                    "symptom_category": sym["category"],
                    "evidence_id": sym.get("evidence_id"),
                    "note_time": sym.get("note_time"),
                    "status": "pending",
                    "depth": 0,
                }
            )

        hyps.sort(key=lambda h: _PRIORITY.get(_hyp_kind(h), 9))
        state["hypotheses"] = hyps
        state["steps"].append(
            {
                "node": "make_hypotheses",
                "action": "typed_hypotheses",
                "detail": None,
                "payload": {
                    "hypotheses": [
                        {k: v for k, v in h.items() if k not in ("snapshot", "candidate")}
                        for h in hyps
                    ]
                },
            }
        )
        return state

    def supervisor(state: InvestigatorState) -> InvestigatorState:
        state["next_hypothesis"] = None
        if state["stop_reason"] == "budget_exhausted":
            return state
        if len(state["findings"]) >= MAX_ITEMS:
            state["stop_reason"] = "evidence_sufficient"
            return state
        if state["tool_calls_used"] >= MAX_TOOL_CALLS:
            state["stop_reason"] = "budget_exhausted"
            return state
        pending = [
            (i, h) for i, h in enumerate(state["hypotheses"]) if h["status"] == "pending"
        ]
        if not pending:
            state["stop_reason"] = state["stop_reason"] or (
                "no_hypotheses" if not state["hypotheses"] else "completed"
            )
            return state
        if state["branches_used"] >= MAX_BRANCHES:
            state["stop_reason"] = "branch_budget_exhausted"
            for _, h in pending:
                h["status"] = "skipped"
            return state
        idx, hyp = pending[0]
        hyp["status"] = "investigating"
        state["branches_used"] += 1
        state["next_hypothesis"] = idx
        state["steps"].append(
            {
                "node": "supervisor",
                "action": "route",
                "detail": _hyp_kind(hyp),
                "payload": {"hypothesis_index": idx, "type": hyp["type"]},
            }
        )
        return state

    def route(state: InvestigatorState) -> str:
        if state["next_hypothesis"] is None:
            return "finalize"
        hyp = state["hypotheses"][state["next_hypothesis"]]
        return {
            "trend": "investigate_trend",
            "plan": "investigate_plan",
            "coverage": "investigate_coverage",
            "symptom": "investigate_symptom",
        }[hyp["type"]]

    def investigate_trend(state: InvestigatorState) -> InvestigatorState:
        assert state["next_hypothesis"] is not None
        hyp = state["hypotheses"][state["next_hypothesis"]]
        code = hyp["metric_code"]
        series = tools.call(
            state, "investigate_trend", "get_metric_series", metric_code=code
        )
        hyp["depth"] = 1
        evidence = [p["evidence_id"] for p in (series or {"points": []})["points"][-3:]]
        related_aligned = None
        if state["tool_calls_used"] < MAX_TOOL_CALLS and hyp["depth"] < MAX_DEPTH:
            related = tools.call(
                state, "investigate_trend", "get_related_metric_snapshots", metric_code=code
            )
            hyp["depth"] = 2
            snap = hyp["snapshot"]
            for rel in (related or {"related": []})["related"]:
                rel_n = rel.get("n_points") or 0
                rel_slope = rel.get("slope_per_month")
                if rel_slope is None or rel_n < 3:
                    continue
                rel_threshold = SLOPE_THRESHOLDS.get(rel["metric_code"], DEFAULT_SLOPE_THRESHOLD)
                same_direction = (rel_slope > rel_threshold and snap["slope_per_month"] > 0) or (
                    rel_slope < -rel_threshold and snap["slope_per_month"] < 0
                )
                if same_direction:
                    related_aligned = rel
                    break
        hyp["status"] = "done"
        snap = hyp["snapshot"]
        if related_aligned:
            for other in state["hypotheses"]:
                if (
                    other["type"] == "trend"
                    and other["status"] == "pending"
                    and other["metric_code"] == related_aligned["metric_code"]
                ):
                    other["status"] = "merged"
            state["findings"].append(
                {
                    "category": "dual_trend",
                    "metric_code": snap["metric_code"],
                    "related_code": related_aligned["metric_code"],
                    "snapshot": snap,
                    "related_snapshot": related_aligned,
                    "evidence_ids": [
                        snap["evidence_id"],
                        related_aligned["evidence_id"],
                        *evidence,
                    ],
                    "source_dates": [
                        d
                        for d in [snap.get("latest_time"), related_aligned.get("latest_time")]
                        if d
                    ],
                }
            )
        else:
            state["findings"].append(
                {
                    "category": "trend",
                    "metric_code": snap["metric_code"],
                    "snapshot": snap,
                    "series_points": (series or {"points": []})["points"],
                    "evidence_ids": [snap["evidence_id"], *evidence],
                    "source_dates": [d for d in [snap.get("latest_time")] if d],
                }
            )
        return state

    def investigate_plan(state: InvestigatorState) -> InvestigatorState:
        assert state["next_hypothesis"] is not None
        hyp = state["hypotheses"][state["next_hypothesis"]]
        cand = hyp["candidate"]
        resolution = tools.call(
            state,
            "investigate_plan",
            "get_followup_resolution",
            topic=hyp["topic"],
            since=cand["note_time"],
        )
        hyp["depth"] = 1
        hyp["status"] = "done"
        if resolution is None:
            return state
        if not resolution["resolved"]:
            state["findings"].append(
                {
                    "category": "unresolved_plan",
                    "topic": hyp["topic"],
                    "plan_text": cand["plan_text"],
                    "evidence_ids": [cand["evidence_id"]],
                    "source_dates": [cand["note_time"]] if cand["note_time"] else [],
                }
            )
        return state

    def investigate_coverage(state: InvestigatorState) -> InvestigatorState:
        assert state["next_hypothesis"] is not None
        hyp = state["hypotheses"][state["next_hypothesis"]]
        hits = tools.call(
            state, "investigate_coverage", "search_prior_notes", query=hyp["raw_term"]
        )
        hyp["depth"] = 1
        hyp["status"] = "done"
        prior_mention = None
        if hits and hits["found"]:
            prior_mention = hits["hits"][0]
        state["findings"].append(
            {
                "category": "coverage_gap",
                "metric_code": hyp["metric_code"],
                "raw_term": hyp["raw_term"],
                "qualifier": hyp.get("qualifier"),
                "prior_mention": prior_mention,
                "evidence_ids": [
                    prior_mention["evidence_id"] if prior_mention else _fallback_evidence(repo)
                ],
                "source_dates": [prior_mention["time"]] if prior_mention else [],
            }
        )
        return state

    def investigate_symptom(state: InvestigatorState) -> InvestigatorState:
        assert state["next_hypothesis"] is not None
        hyp = state["hypotheses"][state["next_hypothesis"]]
        hits = tools.call(
            state, "investigate_symptom", "search_prior_notes", query=hyp["term"]
        )
        hyp["depth"] = 1
        hyp["status"] = "done"
        evidence = [h["evidence_id"] for h in (hits or {"hits": []})["hits"][:2]]
        dates = [h["time"] for h in (hits or {"hits": []})["hits"][:2] if h.get("time")]
        if not evidence and hyp.get("evidence_id"):
            evidence = [hyp["evidence_id"]]
            dates = [hyp["note_time"]] if hyp.get("note_time") else []
        if not evidence:
            evidence = [_fallback_evidence(repo)]
        state["findings"].append(
            {
                "category": "symptom_followup",
                "term": hyp["term"],
                "symptom_category": hyp["symptom_category"],
                "evidence_ids": evidence,
                "source_dates": dates,
            }
        )
        return state

    def finalize(state: InvestigatorState) -> InvestigatorState:
        items: list[ReviewItem] = []
        for topic, deferral in state["deferred_topics"].items():
            was_raised = any(
                h["type"] == "plan" and h.get("topic") == topic and h["status"] == "suppressed"
                for h in state["hypotheses"]
            )
            if was_raised:
                label = TOPIC_LABELS.get(topic, topic)
                evidence = [deferral["evidence_id"]]
                if deferral.get("note_id"):
                    evidence.append(deferral["note_id"])
                until = (deferral.get("deferred_until") or "")[:10]
                items.append(
                    ReviewItem(
                        item_id=f"item-{uuid.uuid4().hex[:10]}",
                        category="deferred_topic",
                        title=f"Topic appears deferred: {label}",
                        message=(
                            f"This topic appears to have been deferred: {label}"
                            + (f", deferred until {until}" if until else "")
                            + ". Available records include a documented deferral. "
                            "Consider reviewing timing before revisiting it."
                        ),
                        confidence="high",
                        evidence_ids=evidence,
                        source_dates=[until] if until else [],
                        limitations=DEFAULT_LIMITATIONS,
                        deferral_state="active",
                    )
                )
        for f in state["findings"]:
            items.append(_finding_to_item(f))
        validated = []
        for item in items[:MAX_ITEMS]:
            validated.append(validate_item(item))
        state["items"] = [i.model_dump() for i in validated]
        state["coverage_report"] = _build_coverage_report(repo, state)
        state["signal_synthesis"] = _synthesize_signal_links(provider, state, repo)
        if not state["stop_reason"]:
            state["stop_reason"] = "completed"
        state["steps"].append(
            {
                "node": "finalize",
                "action": "emit",
                "detail": state["stop_reason"],
                "payload": {
                    "item_count": len(state["items"]),
                    "coverage_report": state["coverage_report"],
                    "signal_synthesis_present": state["signal_synthesis"] is not None,
                },
            }
        )
        return state

    graph = StateGraph(InvestigatorState)
    graph.add_node("load_context", load_context)
    graph.add_node("scan_signals", scan_signals)
    graph.add_node("make_hypotheses", make_hypotheses)
    graph.add_node("supervisor", supervisor)
    graph.add_node("investigate_trend", investigate_trend)
    graph.add_node("investigate_plan", investigate_plan)
    graph.add_node("investigate_coverage", investigate_coverage)
    graph.add_node("investigate_symptom", investigate_symptom)
    graph.add_node("finalize", finalize)

    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "scan_signals")
    graph.add_edge("scan_signals", "make_hypotheses")
    graph.add_edge("make_hypotheses", "supervisor")
    graph.add_conditional_edges(
        "supervisor",
        route,
        {
            "investigate_trend": "investigate_trend",
            "investigate_plan": "investigate_plan",
            "investigate_coverage": "investigate_coverage",
            "investigate_symptom": "investigate_symptom",
            "finalize": "finalize",
        },
    )
    graph.add_edge("investigate_trend", "supervisor")
    graph.add_edge("investigate_plan", "supervisor")
    graph.add_edge("investigate_coverage", "supervisor")
    graph.add_edge("investigate_symptom", "supervisor")
    graph.add_edge("finalize", END)
    return graph.compile()


def _hyp_kind(hyp: dict) -> str:
    return {
        "trend": "trend",
        "plan": "unresolved_plan",
        "coverage": "coverage_gap",
        "symptom": "symptom_followup",
    }[hyp["type"]]


def _build_coverage_report(repo: ChartRepository, state: InvestigatorState) -> dict:
    """Deterministic completeness check: proves which record domains were
    pulled in for this run, with counts and staleness, so the reviewer can see
    nothing was silently skipped."""
    from app.analytics.trends import is_stale

    snaps = state.get("snapshots", [])
    stale = [
        s["metric_code"]
        for s in snaps
        if is_stale(
            s["metric_code"],
            datetime.fromisoformat(s["latest_time"]) if s.get("latest_time") else None,
        )
    ]
    return {
        "domains": {
            "conditions": len(repo.active_conditions()),
            "medications_active": len(repo.medications()),
            "medications_all": len(repo.medications(active_only=False)),
            "allergies": len(repo.allergies()),
            "metrics_tracked": len(snaps),
            "observations_metrics": len(repo.distinct_metric_codes()),
            "notes": len(repo.notes(limit=10)),
            "care_plans": len(repo.care_plans()),
            "orders": len(repo.orders()),
            "procedures": len(repo.procedures()),
            "active_deferrals": len(state.get("deferred_topics", {})),
        },
        "stale_metrics": stale,
        "hypotheses_total": len(state.get("hypotheses", [])),
        "hypotheses_investigated": sum(
            1 for h in state.get("hypotheses", []) if h["status"] in ("done", "merged")
        ),
        "hypotheses_suppressed": sum(
            1
            for h in state.get("hypotheses", [])
            if h["status"] in ("suppressed", "suppressed_draft")
        ),
        "hypotheses_skipped": sum(
            1 for h in state.get("hypotheses", []) if h["status"] == "skipped"
        ),
        "tools_used": sorted({s["action"] for s in state.get("steps", []) if s["action"] in TOOLS}),
        "limitations": "Coverage reflects connected synthetic records only.",
    }


def _synthesize_signal_links(
    provider: Any, state: InvestigatorState, repo: ChartRepository
) -> dict | None:
    """One stateless, compact model call linking the deterministic signals.

    Only derived signals (slopes, categories, evidence IDs) are passed — never
    raw notes or full records — and nothing persists between calls. The output
    is evidence-gated: metric references that don't map to known snapshot
    evidence are dropped, and forbidden wording voids the synthesis entirely.
    """
    if provider is None or getattr(provider, "name", "mock") == "mock":
        return None
    findings = state.get("findings", [])
    snaps = state.get("snapshots", [])
    if not findings or not snaps:
        return None

    from app.providers.gateway import link_signals

    compact_signals = [
        {
            "evidence_id": s["evidence_id"],
            "metric_code": s["metric_code"],
            "slope_per_month": s.get("slope_per_month"),
            "delta": s.get("delta"),
            "n_points": s.get("n_points"),
            "unit": s.get("unit"),
        }
        for s in snaps
    ]
    compact_findings = [
        {
            "category": f["category"],
            "metric_code": f.get("metric_code"),
            "topic": f.get("topic"),
            "symptom": f.get("term"),
            "evidence_ids": f.get("evidence_ids", [])[:3],
        }
        for f in findings
    ]
    compact_conditions = [
        {"evidence_id": c.source_resource_id, "display": c.display}
        for c in repo.active_conditions()[:5]
    ]
    result = link_signals(provider, compact_signals, compact_findings, compact_conditions)
    if result is None:
        return None
    return {
        "provider": provider.name,
        "links": result["links"],
        "limitations": (
            "Model-generated synthesis over derived signals only; verify against "
            "the linked evidence before relying on it."
        ),
    }


def _fallback_evidence(repo: ChartRepository) -> str:
    encounters = repo.encounters(limit=1)
    if encounters:
        return encounters[0].source_resource_id
    notes = repo.notes(limit=1)
    return notes[0].source_resource_id if notes else f"patient:{repo.patient_id}"


def _finding_to_item(f: dict) -> ReviewItem:
    item_id = f"item-{uuid.uuid4().hex[:10]}"
    dates = [d[:10] for d in f.get("source_dates", []) if d]
    if f["category"] == "trend":
        snap = f["snapshot"]
        pts = f.get("series_points", [])
        # Describe only the windowed points that produced the slope.
        windowed = pts[-(snap.get("n_points") or len(pts)):] if pts else []
        span = (
            f" from {windowed[0]['value']} to {windowed[-1]['value']} {snap.get('unit') or ''}"
            if len(windowed) >= 2
            else ""
        )
        return ReviewItem(
            item_id=item_id,
            category="trend",
            title=f"{snap['display']} trend in available records",
            message=(
                f"Available records show {snap['display']} changing{span} across "
                f"{snap['n_points']} results (about {round(snap['slope_per_month'], 2)} "
                f"{snap.get('unit') or ''} per month). Consider reviewing this trend."
            ),
            confidence="high",
            evidence_ids=f["evidence_ids"],
            source_dates=dates,
            limitations=DEFAULT_LIMITATIONS,
        )
    if f["category"] == "dual_trend":
        snap, rel = f["snapshot"], f["related_snapshot"]
        return ReviewItem(
            item_id=item_id,
            category="dual_trend",
            title=f"{snap['display']} and {rel['display']} moving together",
            message=(
                f"Available records show {snap['display']} (about "
                f"{round(snap['slope_per_month'], 2)} {snap.get('unit') or ''}/month) and "
                f"{rel['display']} (about {round(rel['slope_per_month'], 2)} "
                f"{rel.get('unit') or ''}/month) moving in the same direction over the same "
                f"period. Consider reviewing these together."
            ),
            confidence="high",
            evidence_ids=f["evidence_ids"],
            source_dates=dates,
            limitations=DEFAULT_LIMITATIONS,
        )
    if f["category"] == "unresolved_plan":
        label = TOPIC_LABELS.get(f["topic"], f["topic"])
        when = (f["source_dates"][0][:10]) if f.get("source_dates") else ""
        return ReviewItem(
            item_id=item_id,
            category="unresolved_plan",
            title=f"Earlier plan item may be unresolved: {label}",
            message=(
                f"A prior note{' from ' + when if when else ''} includes a plan item about "
                f"{label}, and no matching completion was found in connected records since "
                f"that date. Consider reviewing its status."
            ),
            confidence="high",
            evidence_ids=f["evidence_ids"],
            source_dates=dates,
            limitations=DEFAULT_LIMITATIONS,
        )
    if f["category"] == "symptom_followup":
        from app.note_review.extract import SYMPTOM_LABELS

        label = SYMPTOM_LABELS.get(f["symptom_category"], f["term"])
        return ReviewItem(
            item_id=item_id,
            category="symptom_followup",
            title=f"Symptom mentioned without follow-up: {label}",
            message=(
                f"Available records mention {label} and no related follow-up item was "
                f"found in connected records. Consider reviewing whether this topic "
                f"needs a follow-up entry."
            ),
            confidence="medium",
            evidence_ids=f["evidence_ids"],
            source_dates=dates,
            limitations=DEFAULT_LIMITATIONS,
        )
    # coverage_gap
    return ReviewItem(
        item_id=item_id,
        category="coverage_gap",
        title=f"{f['raw_term'].capitalize()} result not found in connected records",
        message=(
            f"The draft note references {f['raw_term']}"
            + (f" as '{f['qualifier']}'" if f.get("qualifier") else "")
            + ", but no matching result was found in connected records. "
            "Consider reviewing whether this value is documented elsewhere."
        ),
        confidence="high",
        evidence_ids=f["evidence_ids"],
        source_dates=dates,
        limitations=DEFAULT_LIMITATIONS,
    )
