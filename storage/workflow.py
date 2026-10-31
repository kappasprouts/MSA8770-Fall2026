"""Preserve human review progress when automated processing updates a packet."""


def application_status(processing_status, officer_recommendation=None, final_decision=None):
    if final_decision is not None:
        return "FINAL_DECISION_RECORDED"
    if officer_recommendation is not None:
        return "REVIEWED"
    return processing_status
