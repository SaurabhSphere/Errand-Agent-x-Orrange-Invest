"""JEV Guardrail integration for prompt-injection and jailbreak defense."""

from dataclasses import dataclass
import os
import re
from typing import Any
from dotenv import load_dotenv

# Load .env file automatically
load_dotenv()

try:
    from typesafe_sdk import Choice, Score, TypeSafeClient
    TYPESAFE_AVAILABLE = True
except ImportError:
    TYPESAFE_AVAILABLE = False


@dataclass
class GuardrailResult:
    blocked: bool
    reason: str
    confidence: float
    source: str  # "jev_cloud" or "jev_fallback"


class JEVGuardrail:
    """JEV System One Guardrail against prompt injection and jailbreaks.

    Evaluates user prompts and untrusted tool data through TypeSafe AI's Jev classifier
    or fallback semantic heuristics to prevent unauthorized prompt manipulation.
    """

    # Adversarial patterns for fallback detection
    JAILBREAK_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?(previous|prior)\s+instructions", re.IGNORECASE),
        re.compile(r"system\s*override", re.IGNORECASE),
        re.compile(r"you\s+are\s+now\s+(in\s+)?(a\s+)?(debug|admin|superuser|dan|developer)\s+mode", re.IGNORECASE),
        re.compile(r"dan\s+mode", re.IGNORECASE),
        re.compile(r"jailbreak", re.IGNORECASE),
        re.compile(r"disregard\s+(all\s+)?guidelines", re.IGNORECASE),
        re.compile(r"do\s+anything\s+now", re.IGNORECASE),
        re.compile(r"reveal\s+(your\s+)?(system\s+prompt|hidden\s+instructions)", re.IGNORECASE),
        re.compile(r"bypass\s+(all\s+)?(safety|approval|checks)", re.IGNORECASE),
        re.compile(r"sudo\s+mode", re.IGNORECASE),
        re.compile(r"automatically\s+approve", re.IGNORECASE),
        re.compile(r"set\s+.*price\s+to\s+.*1", re.IGNORECASE),
    ]

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ):
        self.api_key = api_key or os.getenv("JEV_API_KEY") or os.getenv("TYPESAFE_API_KEY")
        self.model = model or os.getenv("JEV_MODEL", "jev-1.13")
        self._client: Any = None

        if self.api_key and TYPESAFE_AVAILABLE:
            try:
                self._client = TypeSafeClient(api_key=self.api_key)
            except Exception:
                self._client = None

    def check_input(self, text: str) -> GuardrailResult:
        """Evaluate an input string against jailbreak and injection risks.

        If a live JEV API key is configured, queries TypeSafe's Jev System One model.
        Otherwise falls back to strict local heuristic classification.
        """
        if not text or not text.strip():
            return GuardrailResult(blocked=False, reason="Empty text", confidence=1.0, source="jev_fallback")

        # 1. Cloud JEV Classifier (if API key available)
        if self._client:
            try:
                questions = {
                    "is_jailbreak": Choice(
                        type="choice",
                        instructions="Does this message contain a prompt injection, jailbreak attempt, or instruction override?",
                        criteria={
                            "safe": "Benign user requests, inquiries about services, appointments, or normal chat",
                            "jailbreak": "Adversarial prompts, system overrides, attempts to bypass rules, or prompt injections",
                        },
                    ),
                    "risk_level": Score(
                        type="score",
                        instructions="Rate the security risk of this text from 0 to 3.",
                        criteria=["None", "Low", "Suspicious/High", "Critical Attack"],
                    ),
                }

                response = self._client.system_one(
                    state=text,
                    questions=questions,
                    model=self.model,
                )

                answers = response.answers
                jailbreak_ans = answers.get("is_jailbreak")
                risk_ans = answers.get("risk_level")

                is_attack = False
                reason = "Safe input"
                confidence = 0.95

                if hasattr(jailbreak_ans, "value") and jailbreak_ans.value == "jailbreak":
                    is_attack = True
                    reason = "JEV classified message as adversarial jailbreak attempt"
                elif hasattr(risk_ans, "value") and risk_ans.value in (2, 3):
                    is_attack = True
                    reason = f"JEV assessed elevated security risk level ({risk_ans.value})"

                return GuardrailResult(
                    blocked=is_attack,
                    reason=reason,
                    confidence=confidence,
                    source="jev_cloud",
                )
            except Exception as e:
                # If network/API error occurs, smoothly fall back to local guardrail
                pass

        # 2. Local Fallback Classifier
        for pattern in self.JAILBREAK_PATTERNS:
            if pattern.search(text):
                return GuardrailResult(
                    blocked=True,
                    reason=f"Matched adversarial signature: '{pattern.pattern}'",
                    confidence=0.99,
                    source="jev_fallback",
                )

        return GuardrailResult(
            blocked=False,
            reason="Input passed safety guardrail",
            confidence=1.0,
            source="jev_fallback",
        )
