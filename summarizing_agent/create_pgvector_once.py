"""
create_pgvector_once.py

EAOS - Policy Vector Store (RAG knowledge base)

Pipeline:

riverview_admissions_policy.txt
        ↓
Parse policy document into policy chunks
        ↓
nomic-embed-text through Ollama (768-dim vectors)
        ↓
PostgreSQL + pgvector: policy_chunks table
        ↓
Summarizing Agent retrieves relevant policy chunks

Run once when initially building the policy vector store.
Run again only when the policy TXT file changes.
"""

import os
import re

import psycopg2
import requests


# ============================================================
# CONFIGURATION
# ============================================================

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")
DB_NAME = os.getenv("POSTGRES_DB", "riverview_admissions")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")

OLLAMA_EMBED_URL = os.getenv(
    "OLLAMA_EMBED_URL",
    "http://localhost:11434/api/embed"
)

EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")

# nomic-embed-text produces 768-dimensional vectors.
EMBED_DIMENSIONS = 768


# Policy TXT file.
# Assumes structure:
#
# summarizing_agent/
# ├── setup/
# │   └── create_pgVector_once.py
# └── data/
#     └── riverview_admissions_policy.txt


POLICY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "data",
    "riverview_admissions_policy.txt"
)

POLICY_VERSION = "1.0"

# ============================================================
# EMBEDDINGS
# ============================================================

def embed_texts(texts, task_prefix):
    """
    Embed a list of texts with nomic-embed-text.

    nomic-embed-text expects a task prefix:
        "search_document: " for stored chunks
        "search_query: "    for questions
    """

    response = requests.post(
        OLLAMA_EMBED_URL,
        json={
            "model": EMBED_MODEL,
            "input": [task_prefix + text for text in texts]
        },
        timeout=120
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"Ollama embed returned HTTP {response.status_code}: "
            f"{response.text}"
        )

    return response.json()["embeddings"]


def to_pgvector(vector):
    """Format Python list as a pgvector literal."""

    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"


# ============================================================
# LOAD POLICY TXT
# ============================================================

def load_policy_chunks():
    """
    Read the admissions policy TXT file and create one chunk
    for each bullet-point policy rule.

    Each ### heading becomes the policy category/title.
    Each bullet underneath becomes an individual vector chunk.
    """

    with open(POLICY_FILE, "r", encoding="utf-8") as file:
        lines = file.readlines()

    chunks = []

    current_section = None
    current_title = None
    policy_counter = 1

    for raw_line in lines:

        line = raw_line.strip()

        if not line:
            continue

        # Main section heading
        if line.startswith("## ") and not line.startswith("### "):
            current_section = line.replace("## ", "").strip()
            continue

        # Subsection heading
        if line.startswith("### "):
            current_title = line.replace("### ", "").strip()
            continue

        # Policy bullet
        if line.startswith("* "):

            content = line[2:].strip()

            # Remove markdown bold markers
            content = re.sub(r"\*\*(.*?)\*\*", r"\1", content)

            policy_id = f"POL-{policy_counter:03d}"

            full_content = (
                f"{policy_id} | {current_title}\n"
                f"Section: {current_section}\n"
                f"Policy: {content}"
            )

            chunks.append(
                {
                    "policy_id": policy_id,
                    "title": current_title or "Admissions Policy",
                    "content": full_content
                }
            )

            policy_counter += 1

    if not chunks:
        raise RuntimeError(
            f"No policy chunks were found in {POLICY_FILE}"
        )

    return chunks, POLICY_VERSION


# ============================================================
# CREATE TABLE
# ============================================================

def create_policy_table(connection):

    with connection.cursor() as cursor:

        cursor.execute(
            "CREATE EXTENSION IF NOT EXISTS vector;"
        )

        cursor.execute(
            f"""
            CREATE TABLE IF NOT EXISTS policy_chunks (
                policy_id      VARCHAR(20) PRIMARY KEY,
                title          TEXT NOT NULL,
                content        TEXT NOT NULL,
                policy_version VARCHAR(20),
                embedding      vector({EMBED_DIMENSIONS}) NOT NULL
            );
            """
        )

    connection.commit()

    print("policy_chunks table is ready.")


# ============================================================
# STORE POLICY VECTORS
# ============================================================

def store_policies(connection, chunks, policy_version):

    print(
        f"Generating embeddings for {len(chunks)} policy chunks..."
    )

    embeddings = embed_texts(
        [chunk["content"] for chunk in chunks],
        task_prefix="search_document: "
    )

    with connection.cursor() as cursor:

        # Rebuild the policy vector store.
        cursor.execute(
            "DELETE FROM policy_chunks;"
        )

        for chunk, embedding in zip(chunks, embeddings):

            cursor.execute(
                """
                INSERT INTO policy_chunks
                    (
                        policy_id,
                        title,
                        content,
                        policy_version,
                        embedding
                    )
                VALUES (%s, %s, %s, %s, %s::vector);
                """,
                (
                    chunk["policy_id"],
                    chunk["title"],
                    chunk["content"],
                    policy_version,
                    to_pgvector(embedding)
                )
            )

    connection.commit()

    print(
        f"Stored {len(chunks)} policy chunks "
        f"(version {policy_version})."
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("\n====================================")
    print("EAOS - POLICY VECTOR STORE")
    print("====================================\n")

    print(f"Reading policy file:\n{POLICY_FILE}\n")

    chunks, policy_version = load_policy_chunks()

    print(
        f"Loaded {len(chunks)} policy chunks "
        f"from {POLICY_FILE}\n"
    )

    connection = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

    try:

        create_policy_table(connection)

        store_policies(
            connection,
            chunks,
            policy_version
        )

        print("\nPolicies stored in pgvector:\n")

        with connection.cursor() as cursor:

            cursor.execute(
                """
                SELECT policy_id, title
                FROM policy_chunks
                ORDER BY policy_id;
                """
            )

            for policy_id, title in cursor.fetchall():
                print(f"  {policy_id:<12} {title}")

    finally:

        connection.close()

    print("\nPolicy vector store creation complete.\n")