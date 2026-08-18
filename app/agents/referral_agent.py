"""V2: Referral Agent.

Determines whether seeking a referral makes sense for a given job, using
deterministic heuristics over company type, match score, and known
contacts. Never automatically sends referral messages - only drafts text
for the user to review and send themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

STARTUP_HINTS = {"startup", "seed", "series a", "series b", "yc "}


@dataclass
class ReferralAssessment:
    potential: str  # HIGH | MEDIUM | LOW
    reasoning: str
    draft_message: Optional[str] = None


def assess_referral_potential(
    job: dict[str, Any],
    candidate_profile: dict[str, Any],
    known_contacts_at_company: bool = False,
) -> ReferralAssessment:
    match_score = job.get("match_score") or 0
    company_description = (job.get("description") or "").lower()
    is_startup = any(hint in company_description for hint in STARTUP_HINTS)

    score = 0
    reasons = []

    if match_score >= 85:
        score += 2
        reasons.append("Strong match score")
    elif match_score >= 70:
        score += 1
        reasons.append("Decent match score")

    if is_startup:
        score += 1
        reasons.append("Company appears to be a startup (often referral-friendly)")

    if known_contacts_at_company:
        score += 2
        reasons.append("Candidate has known contacts at this company")

    if score >= 4:
        potential = "HIGH"
    elif score >= 2:
        potential = "MEDIUM"
    else:
        potential = "LOW"

    reasoning = "; ".join(reasons) if reasons else "No strong referral signals found."

    draft_message = None
    if potential in ("HIGH", "MEDIUM"):
        name = candidate_profile.get("name", "there")
        draft_message = (
            f"Hi! I'm {name} and I'm very interested in the {job.get('title')} role at "
            f"{job.get('company')}. Would you be open to referring me or sharing any advice "
            f"about the process? Happy to share my resume. Thanks so much!"
        )

    return ReferralAssessment(potential=potential, reasoning=reasoning, draft_message=draft_message)
