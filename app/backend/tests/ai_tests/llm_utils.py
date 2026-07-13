"""LLM helpers for simulated personas and the judge (same credentials as production tests)."""

from __future__ import annotations

import os
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_ai import Agent

from backend.chatbot.agents.base_agent import BaseAgent

load_dotenv()


def _make_model(model_name: Optional[str] = None, api_key: Optional[str] = None):
    """Reuse production model routing (OpenRouter, Google, OpenAI, Anthropic)."""
    mn = model_name or os.getenv("MODEL_NAME", "gemini-2.0-flash")
    key = api_key or os.getenv("OPENROUTER_API_KEY") or os.getenv("MODEL_API_KEY", "")
    if not key and "/" not in mn.lower():
        key = (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("GOOGLE_API_KEY")
            or os.getenv("MODEL_API_KEY", "")
        )
    if not key:
        raise RuntimeError(
            "Set OPENROUTER_API_KEY or MODEL_API_KEY to run AI E2E tests"
        )
    return BaseAgent(model_name=mn, api_key=key).model


class JudgeVerdict(BaseModel):
    passed: bool
    confidence: float = Field(ge=0.0, le=1.0, description="How sure you are")
    reasoning: str = Field(description="Short justification referencing the transcript")


JUDGE_SYSTEM = """You are an impartial test judge for a commerce chatbot platform.

You receive:
1) A scenario title and rubric (expected behaviours).
2) Optional "ground truth" facts (products, prices, IDs).
3) The full conversation transcript (roles: Customer, Assistant; sometimes Vendor/Logistics system lines).

Decide if the rubric is satisfied **for a reasonable end-user**. The assistant may be imperfect; pass if the main objectives are met and there are no serious safety or fraud issues (e.g. inventing bank details, confirming wrong payments).

If the rubric asks for a negative case (e.g. reject bad receipt), pass when the assistant appropriately refuses, asks for clarification, or escalates — even if wording varies.

Output structured verdict only (handled by schema)."""


CUSTOMER_ACTOR_SYSTEM = """You simulate a real customer messaging a small business on WhatsApp/web chat.

Rules:
- One short message per turn (1–3 sentences). Natural, human tone.
- Stay in character for the scenario goal; do not mention that you are a test.
- If the assistant already satisfied the goal, reply exactly: [DONE]
- If stuck after several useless replies, reply exactly: [STUCK]
- Do not use markdown or bullet lists unless the user would."""

VENDOR_ACTOR_SYSTEM = """You simulate a vendor/business owner replying to an internal ops assistant or inbox summary.

Rules:
- One short reply per turn. Professional, terse.
- Follow the scenario instruction (e.g. confirm payment, provide delivery window).
- If nothing more to say, reply exactly: [DONE]"""

LOGISTICS_ACTOR_SYSTEM = """You simulate a logistics coordinator replying about pickup/delivery.

Rules:
- One short operational reply.
- Follow the scenario (confirm slot, costs, address handling).
- If complete, reply exactly: [DONE]"""


def _agent(system: str) -> Agent:
    return Agent(_make_model(), system_prompt=system)


_customer: Agent | None = None
_vendor: Agent | None = None
_logistics: Agent | None = None
_judge: Agent | None = None


def _get_customer() -> Agent:
    global _customer
    if _customer is None:
        _customer = _agent(CUSTOMER_ACTOR_SYSTEM)
    return _customer


def _get_vendor() -> Agent:
    global _vendor
    if _vendor is None:
        _vendor = _agent(VENDOR_ACTOR_SYSTEM)
    return _vendor


def _get_logistics() -> Agent:
    global _logistics
    if _logistics is None:
        _logistics = _agent(LOGISTICS_ACTOR_SYSTEM)
    return _logistics


def _get_judge() -> Agent:
    global _judge
    if _judge is None:
        _judge = Agent(_make_model(), system_prompt=JUDGE_SYSTEM, result_type=JudgeVerdict)
    return _judge


async def customer_says(
    *,
    goal: str,
    transcript: str,
    extra_context: str = "",
) -> str:
    prompt = f"Scenario goal:\n{goal}\n\n{extra_context}\n\nTranscript:\n{transcript}\n\nYour next message as the customer:"
    r = await _get_customer().run(prompt)
    out = r.output
    return out.strip() if isinstance(out, str) else str(out).strip()


async def vendor_says(*, instruction: str, inbox_summary: str) -> str:
    prompt = f"Instruction:\n{instruction}\n\nRecent inbox / context:\n{inbox_summary}\n\nYour reply as vendor:"
    r = await _get_vendor().run(prompt)
    out = r.output
    return out.strip() if isinstance(out, str) else str(out).strip()


async def logistics_says(*, instruction: str, context: str) -> str:
    prompt = f"Instruction:\n{instruction}\n\nContext:\n{context}\n\nYour reply as logistics:"
    r = await _get_logistics().run(prompt)
    out = r.output
    return out.strip() if isinstance(out, str) else str(out).strip()


async def judge_scenario(
    *,
    title: str,
    rubric: str,
    transcript: str,
    ground_truth: str = "",
) -> JudgeVerdict:
    prompt = (
        f"Scenario: {title}\n\nRubric:\n{rubric}\n\n"
        f"Ground truth:\n{ground_truth or '(none)'}\n\n"
        f"Transcript:\n{transcript}"
    )
    r = await _get_judge().run(prompt)
    return r.output
