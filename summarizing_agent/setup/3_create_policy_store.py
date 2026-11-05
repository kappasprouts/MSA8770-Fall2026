"""
create_policy_store.py

EAOS - Policy Vector Store (RAG knowledge base)

Pipeline:

policies.yaml (11 policy rules with IDs)
        ↓
One text chunk per policy:
    "POL-ID | title | rule | system action"
        ↓
nomic-embed-text through Ollama (768-dim vectors)
        ↓
PostgreSQL + pgvector: policy_chunks table

The summarizing agent searches this table to find the
policies relevant to each applicant and cites their IDs.

The handbook PDF is intentionally NOT indexed (team decision:
policies.yaml is the single source of truth for now).

Run once, and again whenever policies.yaml changes.
"""

import os

import psycopg2
import requests
import yaml


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

# The team's policy file (same as MSA8770-danny/config/policies.yaml).
POLICY_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "policies.yaml"
)


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

    """Format a Python list as a pgvector literal: '[0.1,0.2,...]'."""

    return "[" + ",".join(f"{value:.7f}" for value in vector) + "]"


# ============================================================
# LOAD POLICIES
# ============================================================

def load_policy_chunks():

    with open(POLICY_FILE, "r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    chunks = []

    for policy in config.get("policies", []):

        content = (
            f"{policy['id']} | {policy['title']}\n"
            f"Rule: {policy['rule']}\n"
            f"System action: {policy['system_action']}"
        )

        chunks.append(
            {
                "policy_id": policy["id"],
                "title": policy["title"],
                "content": content
            }
        )

    return chunks, config.get("policy_version", "unknown")


# ============================================================
# CREATE TABLE AND STORE VECTORS
# ============================================================

def create_policy_table(connection):

    with connection.cursor() as cursor:

        cursor.execute("CREATE EXTENSION IF NOT EXISTS vector;")

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


def store_policies(connection, chunks, policy_version):

    embeddings = embed_texts(
        [chunk["content"] for chunk in chunks],
        task_prefix="search_document: "
    )

    with connection.cursor() as cursor:

        # Rebuild from scratch so removed policies do not linger.
        cursor.execute("DELETE FROM policy_chunks;")

        for chunk, embedding in zip(chunks, embeddings):

            cursor.execute(
                """
                INSERT INTO policy_chunks
                    (policy_id, title, content, policy_version, embedding)
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

    print(f"Stored {len(chunks)} policy chunks (version {policy_version}).")


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("\n====================================")
    print("EAOS - POLICY VECTOR STORE")
    print("====================================\n")

    chunks, policy_version = load_policy_chunks()

    print(f"Loaded {len(chunks)} policies from {POLICY_FILE}")

    connection = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

    try:

        create_policy_table(connection)

        store_policies(connection, chunks, policy_version)

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT policy_id, title FROM policy_chunks ORDER BY policy_id;"
            )
            for policy_id, title in cursor.fetchall():
                print(f"  {policy_id:<12} {title}")

    finally:

        connection.close()
