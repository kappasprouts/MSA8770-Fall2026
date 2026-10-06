import json
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st


# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

UI_DIR = Path(__file__).resolve().parent
DATA_DIR = UI_DIR / "sample_data"
AUDIT_DIR = UI_DIR / "audit_logs"
AUDIT_FILE = AUDIT_DIR / "officer_actions.jsonl"

AUDIT_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# Data loading
# ------------------------------------------------------------

@st.cache_data
def load_dossier(path):
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)


def save_officer_action(app_id, previous_status, action, notes):
    record = {
        "applicant_id": app_id,
        "previous_status": previous_status,
        "officer_action": action,
        "officer_note": notes,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    with open(AUDIT_FILE, "a", encoding="utf-8") as file:
        file.write(json.dumps(record) + "\n")

    return record


def display_section(title, section):
    st.subheader(title.replace("_", " ").title())

    if not isinstance(section, dict):
        st.write(section)
        return

    summary = section.get("summary")

    if summary:
        st.write(summary)

    evidence = section.get("evidence", [])

    details = {
        key: value
        for key, value in section.items()
        if key not in {"summary", "evidence"}
    }

    if details:
        with st.expander("View section details"):
            st.json(details)

    if evidence:
        with st.expander(f"View evidence citations ({len(evidence)})"):
            for item in evidence:
                document = item.get("document", "Unknown document")
                page = item.get("page", "?")
                quote = item.get("quote", "")

                st.markdown(
                    f"**{document}, page {page}**  \n"
                    f"> {quote}"
                )


# ------------------------------------------------------------
# Page configuration
# ------------------------------------------------------------

st.set_page_config(
    page_title="Riverview Admissions Review",
    page_icon="🎓",
    layout="wide"
)

st.title("Riverview State University")
st.caption("AI-Assisted Admissions Officer Review Portal")

dossier_files = sorted(DATA_DIR.glob("*_dossier.json"))

if not dossier_files:
    st.error(f"No dossier files were found in {DATA_DIR}.")
    st.stop()

selected_file = st.sidebar.selectbox(
    "Select application",
    dossier_files,
    format_func=lambda path: path.stem.replace("_dossier", "")
)

data = load_dossier(selected_file)
run = data.get("run", {})

app_id = run.get("app_id", "Unknown applicant")
run_status = run.get("run_status", "UNKNOWN")
validation = run.get("validation", {})
failed_output = run.get("failed_output", {})

complete_dossier = data.get("applicant_dossier")
completed_sections = failed_output.get("completed_sections", {})
failed_sections = failed_output.get("failed_sections", {})

if complete_dossier:
    displayed_sections = complete_dossier
else:
    displayed_sections = completed_sections

total_sections = len(completed_sections) + len(failed_sections)

st.sidebar.markdown("---")
st.sidebar.write("**Prototype mode**")
st.sidebar.caption("Reading local synthetic dossier output")


# ------------------------------------------------------------
# Applicant header and status
# ------------------------------------------------------------

st.header(app_id)

if run_status == "READY_FOR_REVIEW":
    st.success("AI review completed and validated. Human decision required.")
elif run_status == "HUMAN_REVIEW_AI_FAILED":
    st.error(
        "Human review required: one or more AI-generated sections "
        "failed validation."
    )
elif run_status == "INCOMPLETE":
    st.warning("Application is incomplete and awaiting materials.")
else:
    st.warning(f"Current workflow status: {run_status}")

metric_1, metric_2, metric_3, metric_4 = st.columns(4)

metric_1.metric(
    "Runtime",
    f"{run.get('runtime_seconds', 0):.1f} sec"
)

metric_2.metric(
    "Model Calls",
    run.get("attempts", 0)
)

metric_3.metric(
    "Policies Retrieved",
    len(run.get("policies_retrieved", []))
)

metric_4.metric(
    "Validated Sections",
    (
        f"{len(completed_sections)}/{total_sections}"
        if total_sections
        else "Complete"
    )
)


# ------------------------------------------------------------
# Main tabs
# ------------------------------------------------------------

summary_tab, validation_tab, documents_tab, policies_tab, action_tab = st.tabs(
    [
        "Applicant Review",
        "Validation",
        "Documents",
        "Policies",
        "Officer Action"
    ]
)


# ------------------------------------------------------------
# Applicant review tab
# ------------------------------------------------------------

with summary_tab:

    st.subheader("Validated AI Summaries")

    if displayed_sections:
        for section_name, section_content in displayed_sections.items():
            display_section(section_name, section_content)
            st.divider()
    else:
        st.info("No validated AI summaries are available.")

    if failed_sections:
        st.subheader("Sections Requiring Human Review")

        for section_name, failure in failed_sections.items():
            with st.expander(
                f"⚠️ {section_name.replace('_', ' ').title()} — validation failed"
            ):
                for error in failure.get("errors", []):
                    st.error(error)

                st.markdown("**Unvalidated draft output**")
                st.json(failure.get("output", {}))

        st.caption(
            "Draft output is displayed for troubleshooting only and must not "
            "be treated as verified applicant information."
        )


# ------------------------------------------------------------
# Validation tab
# ------------------------------------------------------------

with validation_tab:

    passed = validation.get("passed", False)

    if passed:
        st.success("All generated sections passed validation.")
    else:
        st.error("The complete AI dossier did not pass validation.")

    st.subheader("Validation failures")

    validation_failures = validation.get("failed_sections", {})

    if validation_failures:
        for section, errors in validation_failures.items():
            st.markdown(f"**{section.title()}**")

            for error in errors:
                st.write(f"- {error}")
    else:
        st.write("No validation failures were recorded.")

    st.subheader("Model-call metrics")

    call_rows = []

    for call in validation.get("calls", []):
        usage = call.get("usage", {})

        call_rows.append(
            {
                "Section": call.get("section"),
                "Attempt": call.get("attempt"),
                "Prompt tokens": usage.get("prompt_tokens"),
                "Output tokens": usage.get("output_tokens"),
                "Seconds": usage.get("seconds"),
                "Errors": len(call.get("errors", []))
            }
        )

    if call_rows:
        st.dataframe(call_rows, use_container_width=True, hide_index=True)


# ------------------------------------------------------------
# Documents tab
# ------------------------------------------------------------

with documents_tab:

    st.subheader("Documents processed by AI")

    sent_rows = []

    for document, pages in run.get("documents_sent", {}).items():
        sent_rows.append(
            {
                "Document": document,
                "Pages processed": ", ".join(map(str, pages)),
                "AI access": "Allowed"
            }
        )

    if sent_rows:
        st.dataframe(sent_rows, use_container_width=True, hide_index=True)

    st.subheader("Documents withheld from AI")

    withheld_rows = []

    for document, reason in run.get("documents_withheld", {}).items():
        withheld_rows.append(
            {
                "Document": document,
                "AI access": "Withheld",
                "Reason": reason,
                "Officer access": "Human review permitted"
            }
        )

    if withheld_rows:
        st.dataframe(withheld_rows, use_container_width=True, hide_index=True)

    st.info(
        "The Common App and personal statement remain available for direct "
        "admissions-officer review but are not summarized by the AI."
    )


# ------------------------------------------------------------
# Policies tab
# ------------------------------------------------------------

with policies_tab:

    st.subheader("Admissions policies retrieved")

    policy_rows = []

    for policy in run.get("policies_retrieved", []):
        similarity = policy.get("similarity")

        policy_rows.append(
            {
                "Policy ID": policy.get("policy_id"),
                "Title": policy.get("title"),
                "Similarity": (
                    round(similarity, 3)
                    if isinstance(similarity, (int, float))
                    else "Required"
                ),
                "Retrieval query": policy.get("query")
            }
        )

    if policy_rows:
        st.dataframe(policy_rows, use_container_width=True, hide_index=True)


# ------------------------------------------------------------
# Officer-action tab
# ------------------------------------------------------------

with action_tab:

    st.subheader("Human-in-the-loop review")

    st.write(
        "The AI output is advisory. An authorized admissions officer "
        "must determine the next workflow action."
    )

    action = st.selectbox(
        "Select an action",
        [
            "Continue Manual Review",
            "Send to Second Reader",
            "Request Additional Materials",
            "Escalate to Counselor Review",
            "Return for AI Reprocessing"
        ]
    )

    officer_notes = st.text_area(
        "Officer notes",
        placeholder="Explain the reason for this action."
    )

    confirm = st.checkbox(
        "I reviewed the available AI output and validation warnings."
    )

    if st.button("Record Officer Action", type="primary"):

        if not confirm:
            st.warning("Confirm that you reviewed the validation warnings.")
        elif not officer_notes.strip():
            st.warning("Enter an officer note before recording the action.")
        else:
            record = save_officer_action(
                app_id=app_id,
                previous_status=run_status,
                action=action,
                notes=officer_notes.strip()
            )

            st.success("Officer action recorded.")
            st.json(record)

    if AUDIT_FILE.exists():
        with st.expander("View recorded audit log"):
            audit_records = []

            with open(AUDIT_FILE, "r", encoding="utf-8") as file:
                for line in file:
                    if line.strip():
                        audit_records.append(json.loads(line))

            st.dataframe(
                audit_records,
                use_container_width=True,
                hide_index=True
            )