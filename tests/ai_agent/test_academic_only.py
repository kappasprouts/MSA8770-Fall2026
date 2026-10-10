

import json
import sys
from pathlib import Path

# Add the repository root to Python's import path
PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from ai_agent.summarizing_agent import (
    connect_postgres,
    connect_minio,
    get_applicant,
    normalize_document,
    split_documents,
    load_pages,
    section_pages,
    build_image_prompt,
    run_section,
    restricted_values,
)


def main():
    app_id = "APP_012"
    connection = connect_postgres()

    try:
        applicant = get_applicant(connection, app_id)
        if applicant is None:
            raise RuntimeError(f"{app_id} not found")

        documents = [
            normalize_document(d)
            for d in (applicant.get("documents") or [])
        ]
        allowed, _ = split_documents(documents)

        minio_client = connect_minio()
        pages, problems = load_pages(minio_client, allowed)

        if problems:
            raise RuntimeError(f"Document loading errors: {problems}")

        images = section_pages(pages, "academic")
        print(f"Academic pages: {len(images)}")

        locations = {
            (p["filename"], p["page_number"]): p["text"]
            for p in images
        }

        guards = {
            "restricted": restricted_values(applicant),
            "essay_shingles": set(),
        }

        log = []
        output, errors, attempts = run_section(
            "academic",
            build_image_prompt("academic", applicant, images),
            images,
            locations,
            set(),
            guards,
            log,
        )

        print(f"\nAttempts: {attempts}")
        print(f"Validation errors: {errors}")
        print(json.dumps(output, indent=2, default=str))

    finally:
        connection.close()


if __name__ == "__main__":
    main()
