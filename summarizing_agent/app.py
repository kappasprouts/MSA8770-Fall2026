import html
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
import streamlit as st


# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

UI_DIR = Path(__file__).resolve().parent
AUDIT_DIR = UI_DIR / "audit_logs"
AUDIT_FILE = AUDIT_DIR / "officer_actions.jsonl"

AUDIT_DIR.mkdir(parents=True, exist_ok=True)


# ------------------------------------------------------------
# Database
# ------------------------------------------------------------

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "riverview_admissions")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


# ------------------------------------------------------------
# Content model
# ------------------------------------------------------------

PROFILE_ORDER = [
    "applicant_demographics",
    "academic_profile",
    "engagement_profile",
    "recommendation_profile",
    "supplemental_essay_profile",
]

SECTION_ICONS = {
    "applicant_demographics": "🪪",
    "academic_profile": "🎓",
    "engagement_profile": "🤝",
    "recommendation_profile": "✉️",
    "supplemental_essay_profile": "📝",
}

SPECIAL_KEYS = {
    "app_id",
    "strengths",
    "policy_assessment",
    "review_notes",
    "holistic_assessment",
    "evidence_map",
    "generated_at",
    "updated_at",
}

STATUS_STYLES = {
    "READY_FOR_REVIEW": (
        "success",
        "AI review completed and validated. Human decision required."
    ),
    "DOSSIER_READY": (
        "success",
        "AI dossier complete and validated. Human decision required."
    ),
    "HUMAN_REVIEW_AI_FAILED": (
        "danger",
        "Human review required: one or more AI-generated sections "
        "failed validation."
    ),
    "INCOMPLETE": (
        "warning",
        "Application is incomplete and awaiting materials."
    ),
}

ALERT_ICONS = {
    "success": "✅",
    "warning": "⚠️",
    "danger": "🛑",
    "info": "ℹ️"
}

ALIGNMENT_BADGES = {
    "aligned": ("success", "✅ Aligned"),
    "partially_aligned": ("warning", "⚠️ Partially aligned"),
    "not_aligned": ("danger", "🛑 Not aligned"),
}


# ------------------------------------------------------------
# Styling
# ------------------------------------------------------------

CUSTOM_CSS = """
<style>
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
[data-testid="stToolbar"] { display: none; }

.block-container {
    padding-top: 2rem;
    padding-bottom: 2rem;
}

.rsu-banner {
    background: linear-gradient(135deg, #0F1F3D 0%, #1E3A66 100%);
    padding: 1.75rem 2rem;
    border-radius: 16px;
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 18px rgba(15, 31, 61, 0.18);
}
.rsu-banner-title {
    color: #FFFFFF;
    font-size: 1.65rem;
    font-weight: 700;
    margin: 0;
}
.rsu-banner-sub {
    color: rgba(255, 255, 255, 0.78);
    font-size: 0.95rem;
    margin-top: 0.3rem;
}

.rsu-alert {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.75rem 1.1rem;
    border-radius: 10px;
    font-weight: 600;
    font-size: 0.92rem;
    margin: 0.6rem 0 1.1rem 0;
    border-left: 4px solid transparent;
}
.rsu-alert.success { background: #E8F6EE; color: #146C43; border-left-color: #2DA86B; }
.rsu-alert.warning { background: #FFF6DE; color: #8A6400; border-left-color: #D9A400; }
.rsu-alert.danger  { background: #FDEAEA; color: #B42318; border-left-color: #D64545; }
.rsu-alert.info    { background: #E8EFFC; color: #1E4FA3; border-left-color: #3D6FD6; }

.rsu-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.3rem 0.75rem;
    border-radius: 999px;
    font-weight: 600;
    font-size: 0.8rem;
    white-space: nowrap;
}
.rsu-badge.success { background: #E8F6EE; color: #146C43; }
.rsu-badge.warning { background: #FFF6DE; color: #8A6400; }
.rsu-badge.danger  { background: #FDEAEA; color: #B42318; }
.rsu-badge.info    { background: #E8EFFC; color: #1E4FA3; }

.rsu-metric {
    background: #FFFFFF;
    border: 1px solid #E3E6EC;
    border-radius: 12px;
    padding: 0.9rem 1.1rem;
}
.rsu-metric-label {
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    color: #6B7280;
}
.rsu-metric-value {
    font-size: 1.55rem;
    font-weight: 700;
    color: #122A52;
    margin-top: 0.2rem;
}

.rsu-hero {
    background: #FBF8EF;
    border: 1px solid #ECD98F;
    border-left: 5px solid #C9A227;
    border-radius: 12px;
    padding: 1.1rem 1.3rem;
    margin-bottom: 1.1rem;
}
.rsu-hero-label {
    font-weight: 700;
    color: #8A6400;
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    margin-bottom: 0.4rem;
}
.rsu-hero-text {
    color: #2B2B2B;
    line-height: 1.55;
}

.rsu-quote {
    border-left: 3px solid #C9A227;
    background: #FBF8EF;
    padding: 0.55rem 0.9rem;
    border-radius: 0 8px 8px 0;
    margin: 0.4rem 0;
    font-size: 0.88rem;
    color: #3A3A3A;
}

.rsu-sidebar-note {
    background: rgba(255, 255, 255, 0.08);
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 10px;
    padding: 0.7rem 0.9rem;
    font-size: 0.85rem;
    color: rgba(255, 255, 255, 0.82);
    line-height: 1.5;
}
.rsu-sidebar-note b {
    color: #E3C25E;
}

[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #0F1F3D 0%, #1E3A66 100%);
}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4,
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] span,
[data-testid="stSidebar"] label {
    color: #FFFFFF !important;
}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * {
    color: rgba(255, 255, 255, 0.65) !important;
}
[data-testid="stSidebar"] hr {
    border-color: rgba(255, 255, 255, 0.2) !important;
}
[data-testid="stSidebar"] [data-baseweb="select"] * {
    color: #1B2434 !important;
}

.stTabs [data-baseweb="tab-list"] {
    gap: 0.35rem;
}
</style>
"""


def alert(kind, message):
    icon = ALERT_ICONS.get(kind, "ℹ️")
    st.markdown(
        f'<div class="rsu-alert {kind}">{icon} {html.escape(message)}</div>',
        unsafe_allow_html=True
    )


def badge_html(kind, text):
    return f'<span class="rsu-badge {kind}">{html.escape(text)}</span>'


# ------------------------------------------------------------
# Data loading
# ------------------------------------------------------------

@st.cache_data(ttl=30)
def list_applicants():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT app_id FROM applicant_dossier ORDER BY app_id;")
            return [row[0] for row in cursor.fetchall()]


@st.cache_data(ttl=30)
def load_dossier(app_id):
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                "SELECT * FROM applicant_dossier WHERE app_id = %s;",
                (app_id,)
            )
            dossier_row = cursor.fetchone()

            cursor.execute(
                """
                SELECT * FROM dossier_generation_runs
                WHERE app_id = %s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (app_id,)
            )
            run_row = cursor.fetchone()

    run = dict(run_row) if run_row else {}
    run["app_id"] = app_id
    run["runtime_seconds"] = float(run.get("runtime_seconds") or 0)

    # Postgres stores these as NULL (not an absent key) when unset, so
    # `.get(key, default)` downstream would return None instead of default.
    run["documents_sent"] = run.get("documents_sent") or {}
    run["documents_withheld"] = run.get("documents_withheld") or {}
    run["policies_retrieved"] = run.get("policies_retrieved") or []
    run["validation"] = run.get("validation") or {}
    run["failed_output"] = run.get("failed_output") or {}

    applicant_dossier = dict(dossier_row) if dossier_row else None

    return {"run": run, "applicant_dossier": applicant_dossier}


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


def format_timestamp(value):
    try:
        return datetime.fromisoformat(value).strftime("%b %d, %Y · %I:%M %p UTC")
    except (TypeError, ValueError):
        return value


# ------------------------------------------------------------
# Rendering helpers
# ------------------------------------------------------------

def render_evidence(item):
    document = html.escape(str(item.get("document", "Unknown document")))
    page = html.escape(str(item.get("page", "?")))
    quote = html.escape(item.get("quote", ""))

    st.markdown(
        f'<div class="rsu-quote"><b>{document}, page {page}</b><br/>"{quote}"</div>',
        unsafe_allow_html=True
    )


def render_profile_card(key, section):
    icon = SECTION_ICONS.get(key, "📌")
    title = key.replace("_", " ").title()

    with st.container(border=True):
        st.markdown(f"#### {icon} {title}")

        if not isinstance(section, dict):
            st.write(section)
            return

        summary = section.get("summary")

        if summary:
            st.write(summary)

        evidence = section.get("evidence", [])
        details = {
            k: v
            for k, v in section.items()
            if k not in {"summary", "evidence"}
        }

        detail_col, evidence_col = st.columns(2)

        if details:
            with detail_col:
                with st.expander("View section details"):
                    st.json(details)

        if evidence:
            with evidence_col:
                with st.expander(f"View evidence citations ({len(evidence)})"):
                    for item in evidence:
                        render_evidence(item)


def render_strengths_card(strengths):
    with st.container(border=True):
        st.markdown("#### 💪 Key Strengths")

        for idx, item in enumerate(strengths, start=1):
            if isinstance(item, dict):
                text = item.get("strength", "")
                evidence = item.get("evidence", [])
            else:
                text, evidence = str(item), []

            st.markdown(f"**{idx}.** {text}")

            if evidence:
                with st.expander(f"Evidence ({len(evidence)}) — strength {idx}"):
                    for ev in evidence:
                        render_evidence(ev)


def render_policy_assessment(items):
    for item in items:
        policy_id = item.get("policy_id", "—")
        criterion = item.get("criterion", "")
        alignment = item.get("alignment", "")
        findings = item.get("findings", "")
        evidence = item.get("evidence", [])

        kind, label = ALIGNMENT_BADGES.get(
            alignment,
            ("info", alignment.replace("_", " ").title() or "—")
        )

        with st.container(border=True):
            head_col, badge_col = st.columns([4, 1])
            head_col.markdown(f"**{policy_id}** — {criterion}")
            badge_col.markdown(badge_html(kind, label), unsafe_allow_html=True)

            if findings:
                st.write(findings)

            if evidence:
                with st.expander(f"Evidence ({len(evidence)})"):
                    for ev in evidence:
                        render_evidence(ev)


# ------------------------------------------------------------
# Page configuration
# ------------------------------------------------------------

st.set_page_config(
    page_title="Riverview Admissions Review",
    page_icon="🎓",
    layout="wide"
)

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

st.markdown(
    '''
    <div class="rsu-banner">
        <p class="rsu-banner-title">🎓 Riverview State University</p>
        <p class="rsu-banner-sub">AI-Assisted Admissions Officer Review Portal</p>
    </div>
    ''',
    unsafe_allow_html=True
)

try:
    applicant_ids = list_applicants()
except psycopg2.OperationalError as exc:
    alert(
        "danger",
        f"Could not reach PostgreSQL at {DB_HOST}:{DB_PORT}/{DB_NAME}. "
        f"Make sure the database container is running. ({exc})"
    )
    st.stop()

if not applicant_ids:
    alert("danger", "No applicants with a generated dossier were found in applicant_dossier.")
    st.stop()

with st.sidebar:
    st.markdown("### 🎓 Riverview Admissions")
    st.caption("Officer Review Console")
    st.markdown("---")

    selected_app_id = st.selectbox("Select application", applicant_ids)

    st.markdown("---")
    st.markdown(
        '<div class="rsu-sidebar-note">🗄️ <b>Live mode</b><br/>'
        f"Reading applicant_dossier from PostgreSQL ({DB_HOST}:{DB_PORT}/{DB_NAME}).</div>",
        unsafe_allow_html=True
    )

data = load_dossier(selected_app_id)
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


# ------------------------------------------------------------
# Applicant header and status
# ------------------------------------------------------------

st.markdown(f"## {app_id}")

kind, message = STATUS_STYLES.get(
    run_status,
    ("warning", f"Current workflow status: {run_status.replace('_', ' ').title()}")
)
alert(kind, message)

metric_cols = st.columns(4)

metric_items = [
    ("⏱️", "Runtime", f"{run.get('runtime_seconds', 0):.1f} sec"),
    ("🔁", "Model Calls", run.get("attempts", 0)),
    ("📚", "Policies Retrieved", len(run.get("policies_retrieved", []))),
    (
        "✅",
        "Validated Sections",
        (
            f"{len(completed_sections)}/{total_sections}"
            if total_sections
            else "Complete"
        )
    ),
]

for col, (icon, label, value) in zip(metric_cols, metric_items):
    col.markdown(
        f'''
        <div class="rsu-metric">
            <div class="rsu-metric-label">{icon} {label}</div>
            <div class="rsu-metric-value">{value}</div>
        </div>
        ''',
        unsafe_allow_html=True
    )


# ------------------------------------------------------------
# Main tabs
# ------------------------------------------------------------

summary_tab, validation_tab, documents_tab, policies_tab, action_tab = st.tabs(
    [
        "📋 Applicant Review",
        "✅ Validation",
        "📄 Documents",
        "📚 Policies",
        "🖊️ Officer Action"
    ]
)


# ------------------------------------------------------------
# Applicant review tab
# ------------------------------------------------------------

with summary_tab:

    generated_at = complete_dossier.get("generated_at") if complete_dossier else None
    updated_at = complete_dossier.get("updated_at") if complete_dossier else None

    timestamp_parts = []

    if generated_at:
        timestamp_parts.append(f"Generated {format_timestamp(generated_at)}")

    if updated_at:
        timestamp_parts.append(f"Updated {format_timestamp(updated_at)}")

    if timestamp_parts:
        st.caption(" · ".join(timestamp_parts))

    holistic = complete_dossier.get("holistic_assessment") if complete_dossier else None

    if holistic:
        st.markdown(
            f'''
            <div class="rsu-hero">
                <div class="rsu-hero-label">🧭 Holistic Assessment</div>
                <div class="rsu-hero-text">{html.escape(holistic)}</div>
            </div>
            ''',
            unsafe_allow_html=True
        )

    strengths = complete_dossier.get("strengths") if complete_dossier else None

    if strengths:
        render_strengths_card(strengths)

    rendered_any = False

    if displayed_sections:
        for key in PROFILE_ORDER:
            section = displayed_sections.get(key)

            if section is not None:
                render_profile_card(key, section)
                rendered_any = True

        extra_keys = [
            key for key in displayed_sections
            if key not in PROFILE_ORDER and key not in SPECIAL_KEYS
        ]

        for key in extra_keys:
            render_profile_card(key, displayed_sections[key])
            rendered_any = True

    if not rendered_any:
        st.info("No validated AI summaries are available.")

    review_notes = complete_dossier.get("review_notes") if complete_dossier else None

    if review_notes:
        with st.container(border=True):
            st.markdown("#### 🗒️ Reviewer Notes")

            for note in review_notes:
                st.write(f"- {note}")

    evidence_map = complete_dossier.get("evidence_map") if complete_dossier else None

    if evidence_map:
        with st.expander(f"🔎 Full evidence index ({len(evidence_map)} citations)"):
            evidence_rows = [
                {
                    "Section": item.get("section"),
                    "Document": item.get("document"),
                    "Page": item.get("page"),
                    "Quote": item.get("quote")
                }
                for item in evidence_map
            ]

            st.dataframe(evidence_rows, use_container_width=True, hide_index=True)

    if failed_sections:
        st.markdown("#### ⚠️ Sections Requiring Human Review")

        for section_name, failure in failed_sections.items():
            with st.container(border=True):
                st.markdown(
                    f"**{section_name.replace('_', ' ').title()}** — validation failed"
                )

                for error in failure.get("errors", []):
                    st.markdown(badge_html("danger", error), unsafe_allow_html=True)

                with st.expander("Unvalidated draft output"):
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
        alert("success", "All generated sections passed validation.")
    else:
        alert("danger", "The complete AI dossier did not pass validation.")

    st.markdown("#### Validation Failures")

    validation_failures = validation.get("failed_sections", {})

    if validation_failures:
        for section, errors in validation_failures.items():
            with st.container(border=True):
                st.markdown(f"**{section.title()}**")

                for error in errors:
                    st.write(f"- {error}")
    else:
        st.write("No validation failures were recorded.")

    st.markdown("#### Model-Call Metrics")

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

    st.markdown("#### 📨 Documents Processed by AI")

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

    st.markdown("#### 🔒 Documents Withheld from AI")

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

    alert(
        "info",
        "The Common App and personal statement remain available for direct "
        "admissions-officer review but are not summarized by the AI."
    )


# ------------------------------------------------------------
# Policies tab
# ------------------------------------------------------------

with policies_tab:

    st.markdown("#### 📚 Admissions Policies Retrieved")

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

    policy_assessment = (
        complete_dossier.get("policy_assessment") if complete_dossier else None
    )

    if policy_assessment:
        st.markdown("#### 🔍 Policy Alignment Assessment")
        render_policy_assessment(policy_assessment)


# ------------------------------------------------------------
# Officer-action tab
# ------------------------------------------------------------

with action_tab:

    st.markdown("#### 🖊️ Human-in-the-Loop Review")

    st.write(
        "The AI output is advisory. An authorized admissions officer "
        "must determine the next workflow action."
    )

    with st.container(border=True):

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

        if st.button("Record Officer Action", type="primary", use_container_width=True):

            if not confirm:
                alert("warning", "Confirm that you reviewed the validation warnings.")
            elif not officer_notes.strip():
                alert("warning", "Enter an officer note before recording the action.")
            else:
                record = save_officer_action(
                    app_id=app_id,
                    previous_status=run_status,
                    action=action,
                    notes=officer_notes.strip()
                )

                alert("success", "Officer action recorded.")
                st.json(record)

    if AUDIT_FILE.exists():
        with st.expander("📜 View recorded audit log"):
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
