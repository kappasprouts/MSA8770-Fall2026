"""Create/remove one clearly labeled temporary dossier for browser switching.

Only rsu_live_test is allowed. Never replaces a preexisting APP_014 dossier.
Load the same test environment used for verify_live_pipeline.py first.
"""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ai_agent.summarizing_agent import connect_postgres

MARKER = "TEMPORARY UI SWITCH TEST FIXTURE - no model-generated findings"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["create", "remove"])
    args = parser.parse_args()
    connection = connect_postgres()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            assert cursor.fetchone()[0] == "rsu_live_test", "Test database required"
            if args.action == "create":
                cursor.execute("SELECT 1 FROM applicant_dossier WHERE app_id='APP_014'")
                assert cursor.fetchone() is None, "Refusing to replace a dossier"
                cursor.execute("""
                    INSERT INTO applicant_dossier
                    (app_id, applicant_demographics, academic_profile, engagement_profile,
                     recommendation_profile, supplemental_essay_profile, strengths,
                     review_notes, policy_assessment, holistic_assessment, evidence_map,
                     generated_at, updated_at)
                    VALUES ('APP_014', '{"first_name":"Temporary","last_name":"UI fixture"}',
                            '{}', '{}', '{}', '{}', '[]', '[]', '[]', %s, '[]', now(), now())
                    """, (MARKER,))
            else:
                cursor.execute("DELETE FROM applicant_dossier WHERE app_id='APP_014' AND holistic_assessment=%s", (MARKER,))
                assert cursor.rowcount == 1, "Expected exactly the owned fixture"
        connection.commit()
        print(args.action, "APP_014 temporary UI fixture")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
