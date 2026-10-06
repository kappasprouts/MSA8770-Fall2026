from pathlib import Path
from minio import Minio
from minio.error import S3Error


# ============================================================
# CONFIGURATION
# ============================================================

MINIO_ENDPOINT = "localhost:9000"

# Change these if your docker-compose.yml uses different values
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"

BUCKET_NAME = "applicant-documents"

# PDFs live in summarizing_agent/data/sample_docs/<APP_ID>/
SAMPLE_DOCUMENTS_DIR = (
    Path(__file__).resolve().parent.parent / "data" / "sample_docs"
)


# ============================================================
# CONNECT TO MINIO
# ============================================================

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)


# ============================================================
# CREATE BUCKET
# ============================================================

def ensure_bucket():

    if client.bucket_exists(BUCKET_NAME):

        print(
            f"Bucket already exists: {BUCKET_NAME}"
        )

    else:

        client.make_bucket(BUCKET_NAME)

        print(
            f"Created bucket: {BUCKET_NAME}"
        )


# ============================================================
# UPLOAD SAMPLE DOCUMENTS
# ============================================================

def upload_documents():

    # Make sure sample_documents exists
    if not SAMPLE_DOCUMENTS_DIR.exists():

        raise FileNotFoundError(
            f"Folder not found: "
            f"{SAMPLE_DOCUMENTS_DIR}"
        )

    # Loop through applicant folders:
    #
    # APP_001/
    # APP_002/
    # etc.

    for applicant_folder in SAMPLE_DOCUMENTS_DIR.iterdir():

        if not applicant_folder.is_dir():
            continue

        application_id = applicant_folder.name

        print(
            f"\nProcessing applicant: "
            f"{application_id}"
        )

        # Loop through documents belonging to applicant
        for file_path in applicant_folder.iterdir():

            if not file_path.is_file():
                continue

            filename = file_path.name

            # --------------------------------------------
            # GENERATE MINIO OBJECT KEY
            #
            # Example:
            #
            # APP_001/transcript.pdf
            # --------------------------------------------

            object_key = (
                f"{application_id}/{filename}"
            )

            try:

                client.fput_object(
                    bucket_name=BUCKET_NAME,
                    object_name=object_key,
                    file_path=str(file_path)
                )

                print(
                    f"  Uploaded:"
                    f" {filename}"
                )

                print(
                    f"  Object key:"
                    f" {object_key}"
                )

            except S3Error as error:

                print(
                    f"ERROR uploading "
                    f"{filename}: {error}"
                )


# ============================================================
# SHOW WHAT IS IN MINIO
# ============================================================

def list_objects():

    print(
        f"\nObjects in bucket "
        f"'{BUCKET_NAME}':"
    )

    objects = client.list_objects(
        BUCKET_NAME,
        recursive=True
    )

    for obj in objects:

        print(
            f"  {obj.object_name}"
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print(
        "\n=============================="
    )

    print(
        "EAOS - MINIO TEST DATA SEED"
    )

    print(
        "==============================\n"
    )

    try:

        ensure_bucket()

        upload_documents()

        list_objects()

        print(
            "\nMinIO seed completed successfully."
        )

    except Exception as error:

        print(
            f"\nMinIO seed failed: {error}"
        )

        raise