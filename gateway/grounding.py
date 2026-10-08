"""Policy Grounding Engine for Local Model Gateway Inference.

Injects Riverview State University admissions policies and grounding rules into
model prompts to ensure adherence to institutional guidelines and bias mitigation.
"""

from typing import Any, Dict, List, Optional
from config import load_policies


class PolicyGrounder:
    """Manages policy grounding for LLM inference prompts."""

    def __init__(self, config_path: Optional[Any] = None):
        self.policies_cfg = load_policies(config_path)
        self.operational_policies = self.policies_cfg.get("policies", [])

    def get_grounding_system_prompt(self) -> str:
        """Construct system instructions embedding core admissions governance policies."""
        prompt = (
            "You are the Riverview State University Admissions Advisory AI assistant.\n"
            "Your role is to compile objective candidate dossiers and factual findings for human review.\n\n"
            "STRICT OPERATIONAL DIRECTIVES:\n"
            "1. ADVISORY AUTHORITY ONLY (POL-HUMAN-01): You must NEVER emit an admissions decision "
            "(Accept, Decline, Waitlist). All final decisions are reserved for authorized admissions officers.\n"
            "2. ESSAY EVALUATION BYPASS (POL-ESSAY-01): You must not evaluate personal statements or essays. "
            "Essays are evaluated exclusively by human officers to prevent algorithmic bias.\n"
            "3. EVIDENCE-BASED FACTUALITY (POL-EVID-01): Every factual finding must cite its source document. "
            "If information is missing, ambiguous, or unconfirmed, you must explicitly state 'unknown'—never infer.\n"
            "4. HIGH SCHOOL RIGOR IN CONTEXT (POL-AP-01): Evaluate AP/honors coursework strictly in the context "
            "of the applicant's high school profile offerings. Lack of AP offerings must not be penalized.\n"
            "5. TEST-OPTIONAL REVIEW (POL-TEST-01): Standardized test scores (SAT/ACT) are optional. Do not penalize "
            "for missing scores.\n\n"
            "INSTITUTIONAL POLICIES REFERENCE:\n"
        )

        for pol in self.operational_policies:
            prompt += f"- [{pol.get('id')}]: {pol.get('title')} — {pol.get('rule')}\n"

        prompt += (
            "\nProduce output in valid JSON format summarizing findings, factual highlights, "
            "and policy citations."
        )
        return prompt

    def get_applicable_policies(self, application_type: str = "first_year") -> List[Dict[str, Any]]:
        """Retrieve policies applicable to the given applicant type."""
        return self.operational_policies
