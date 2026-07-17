"""Provider-neutral LLM gateway.

All providers speak the OpenAI-compatible /chat/completions API except
MockProvider, which is fully deterministic and used whenever no provider is
configured (tests, offline dev).

The only model use in ChartLens is bounded semantic verification: given a
question and structured context, return a small JSON verdict. Raw prompts and
raw completions never leave this module except as the parsed verdict.
"""

import json
import re
from typing import Any, Protocol

import httpx

from app.config import Settings, get_settings
from app.tracing import traced


class LLMProvider(Protocol):
    name: str

    def complete_json(self, system: str, user: str) -> dict[str, Any]: ...


class MockProvider:
    """Deterministic offline provider.

    Verification prompts embed structured context; the mock answers "unsure"
    so that only deterministic findings survive. This keeps fixture
    expectations independent of any model.
    """

    name = "mock"

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        return {"answer": "unsure", "rationale": "mock provider: no semantic model configured"}


class OpenAICompatProvider:
    def __init__(self, name: str, base_url: str, model: str, api_key: str = ""):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key

    @traced("chartlens.llm.complete_json", run_type="llm")
    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            resp = httpx.post(
                f"{self.base_url}/chat/completions", json=payload, headers=headers, timeout=30
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            return _parse_json_object(content)
        except Exception as exc:  # noqa: BLE001 - any provider failure degrades to "unsure"
            return {"answer": "unsure", "rationale": f"provider error: {type(exc).__name__}"}


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return {"answer": "unsure", "rationale": "unparseable model output"}


def build_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    kind = s.llm_provider.lower()
    if kind == "ollama":
        return OpenAICompatProvider("ollama", f"{s.ollama_local_base_url}/v1", s.ollama_model)
    if kind == "ollama_cloud" and s.ollama_cloud_api_key:
        return OpenAICompatProvider(
            "ollama_cloud", f"{s.ollama_base_url}/v1", s.ollama_model, s.ollama_cloud_api_key
        )
    if kind == "groq" and s.groq_api_key:
        return OpenAICompatProvider(
            "groq", "https://api.groq.com/openai/v1", s.groq_model, s.groq_api_key
        )
    return MockProvider()


@traced("chartlens.link_signals")
def build_lint_provider(settings: Settings | None = None) -> LLMProvider:
    """Provider for the inline lint pass; LINT_MODEL overrides the model."""
    s = settings or get_settings()
    provider = build_provider(s)
    if s.lint_model and isinstance(provider, OpenAICompatProvider):
        return OpenAICompatProvider(provider.name, provider.base_url, s.lint_model,
                                    provider.api_key)
    return provider


def link_signals(
    provider: LLMProvider,
    signals: list[dict],
    findings: list[dict],
    conditions: list[dict] | None = None,
) -> dict[str, Any] | None:
    """Single stateless call: relate derived signals, findings, and conditions.

    Every input row carries its evidence_id; the model must cite those ids and
    the caller drops any link citing unknown ids. Only derived/compact data is
    passed — never raw notes."""
    from app.schemas.items import contains_forbidden_wording

    known_ids: set[str] = set()
    for row in signals + findings + (conditions or []):
        for eid in row.get("evidence_ids", []) or []:
            known_ids.add(eid)
        if row.get("evidence_id"):
            known_ids.add(row["evidence_id"])

    system = (
        "You relate derived signals from SYNTHETIC clinical records. "
        "Given metric movements, detected findings (trends, unresolved plans, "
        "symptom mentions), and active conditions, point out which items are "
        "clinically related or move together. "
        'Respond with JSON: {"links": [{"note": "<one neutral sentence>", '
        '"evidence_ids": ["<id>", ...]}]} with at most 3 links. '
        "Cite only the provided evidence_id values. Start each note with "
        "'Available records show'. Never suggest what to do next. "
        "Do not use any of these words: diagnosis, diagnose, treat, treatment, "
        "prescribe, order, urgent, critical."
    )
    user = json.dumps(
        {"signals": signals, "findings": findings, "conditions": conditions or []},
        default=str,
    )
    result = provider.complete_json(system, user)
    links = result.get("links")
    if not isinstance(links, list):
        return None
    clean = []
    for link in links[:3]:
        if not isinstance(link, dict):
            continue
        note = str(link.get("note", ""))[:300]
        cited = link.get("evidence_ids")
        if not note or not isinstance(cited, list):
            continue
        valid = [str(e) for e in cited if str(e) in known_ids][:6]
        if not valid or contains_forbidden_wording(note):
            continue
        clean.append({"note": note, "evidence_ids": valid})
    return {"links": clean} if clean else None


@traced("chartlens.semantic_verify")
def semantic_verify(
    provider: LLMProvider, question: str, context: dict[str, Any]
) -> dict[str, Any]:
    """Ask the model a bounded yes/no/unsure question about structured context."""
    system = (
        "You verify possible documentation conflicts in SYNTHETIC clinical data. "
        "Answer only from the provided context. "
        'Respond with JSON: {"answer": "yes"|"no"|"unsure", "rationale": "<one sentence>"}. '
        "Never diagnose, never recommend treatment."
    )
    user = json.dumps({"question": question, "context": context}, default=str)
    result = provider.complete_json(system, user)
    answer = str(result.get("answer", "unsure")).lower()
    if answer not in ("yes", "no", "unsure"):
        answer = "unsure"
    return {"answer": answer, "rationale": str(result.get("rationale", ""))[:300]}
