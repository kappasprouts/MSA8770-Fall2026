"""
2_create_simulated_postgres.py   (setup step 2)

Creates one simulated PostgreSQL applicant record (default APP_001)
for testing the EAOS summarizing agent. Values are loaded from
data/applicant_data_09302026_V3.csv so the database matches the CSV.
Status is set to COMPLETE, as if the completeness check had passed.

This script is independent of the ingestion pipeline.

MinIO bucket already created:
    applicant-documents

MinIO objects already created (by setup step 1):
    APP_001/<all 10 files in data/sample_docs/APP_001>
"""

import csv
import os
from pathlib import Path

import psycopg2
from psycopg2.extras import Json


# ============================================================
# SOURCE OF TRUTH: APPLICANT CSV
# ============================================================

# The record is loaded from the team's applicant flat file so the
# database matches it exactly (no hand-typed or truncated values).
CSV_FILE = Path(__file__).resolve().parent.parent / "data" / "applicant_data_09302026_V3.csv"

APP_ID = os.getenv("APP_ID", "APP_001")


# ============================================================
# POSTGRESQL CONFIGURATION
# ============================================================

DB_HOST = os.getenv("POSTGRES_HOST", "localhost")
DB_PORT = os.getenv("POSTGRES_PORT", "5432")

# CHANGE THESE DEFAULTS IF YOUR DOCKER CONTAINER
# USES DIFFERENT VALUES.
DB_NAME = os.getenv("POSTGRES_DB", "riverview_admissions")
DB_USER = os.getenv("POSTGRES_USER", "postgres")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")


# ============================================================
# CONNECT TO POSTGRESQL
# ============================================================

def connect_to_postgres():

    print("Connecting to PostgreSQL...")

    connection = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )

    print("Connected successfully.")

    return connection


# ============================================================
# CREATE SIMULATED TABLE
# ============================================================

def create_applicant_table(connection):

    create_table_sql = """
    CREATE TABLE IF NOT EXISTS simulated_applicant_data (

        App_ID VARCHAR(10) PRIMARY KEY,

        First_Name VARCHAR(40),
        Last_Name VARCHAR(40),

        Date_Of_Birth DATE,

        Mailing_Address VARCHAR(200),
        Primary_Phone_Number VARCHAR(20),
        Email_Address VARCHAR(254),

        Gender VARCHAR(30),
        Ethnicity VARCHAR(100),

        Name_of_HS VARCHAR(150),
        Counselor_Name VARCHAR(100),

        Country VARCHAR(100),
        Region VARCHAR(100),

        Intended_Major VARCHAR(200),

        Superscored_SAT_Score INTEGER,
        Superscored_ACT_Score INTEGER,

        Unweighted_GPA NUMERIC(5,3),
        Weighted_GPA NUMERIC(5,3),

        Rank VARCHAR(20),

        AP_Courses JSONB,
        Total_APs INTEGER,

        IB_Courses VARCHAR(50),
        Total_IBs INTEGER,

        Activities JSONB,
        Awards JSONB,
        Hooks JSONB,

        Documents JSONB,

        Admission_Year INTEGER,
        Admission_Term CHAR(1),

        Create_Date_Time TIMESTAMPTZ,
        Last_Updated TIMESTAMPTZ,

        Review_Ctr INTEGER DEFAULT 0,

        Application_status VARCHAR(15),

        Final_Decision VARCHAR(10)
    );
    """

    # The team schema (M2 PDF p.54) is too narrow for the CSV:
    # e.g. Email VARCHAR(20) fits 0 of 60 rows, and Rank INTEGER
    # cannot hold values like "1/16". Widen any existing table.
    widen_sql = """
    ALTER TABLE simulated_applicant_data
        ALTER COLUMN Email_Address TYPE VARCHAR(254),
        ALTER COLUMN Gender TYPE VARCHAR(30),
        ALTER COLUMN Ethnicity TYPE VARCHAR(100),
        ALTER COLUMN Name_of_HS TYPE VARCHAR(150),
        ALTER COLUMN Counselor_Name TYPE VARCHAR(100),
        ALTER COLUMN Country TYPE VARCHAR(100),
        ALTER COLUMN Region TYPE VARCHAR(100),
        ALTER COLUMN Intended_Major TYPE VARCHAR(200),
        ALTER COLUMN Mailing_Address TYPE VARCHAR(200),
        ALTER COLUMN Primary_Phone_Number TYPE VARCHAR(20),
        ALTER COLUMN Rank TYPE VARCHAR(20);
    """

    with connection.cursor() as cursor:
        cursor.execute(create_table_sql)
        cursor.execute(widen_sql)

    connection.commit()

    print("simulated_applicant_data table is ready.")


# ============================================================
# MINIO DOCUMENT REFERENCES
# ============================================================

def create_documents():

    """
    These are NOT the PDFs themselves.

    These are references to the PDF objects that already exist
    in the MinIO bucket named applicant-documents.
    """

    # All 10 files in data/sample_docs/<APP_ID>, the same set
    # Danny's ingestion attaches. The personal statement and the
    # Common App copy are listed on purpose: the summarizing agent
    # must withhold them itself, not rely on this list.

    files = [
        ("application_form", "application_form.pdf"),
        ("common_app", "common_app_application.pdf"),
        ("transcript", "transcript.pdf"),
        ("recommendation", "recommendation_letter_1.pdf"),
        ("recommendation", "recommendation_letter_2.pdf"),
        ("standardized_test_score", "standardized_test_score.pdf"),
        ("activities_and_awards", "activities_and_awards.pdf"),
        ("advanced_coursework", "advanced_coursework_and_ap_scores.pdf"),
        ("university_supplement", "university_supplement.pdf"),
        ("personal_statement", "personal_statement.pdf"),
    ]

    documents = [
        {
            "type": document_type,
            "filename": filename,
            "object_key": f"{APP_ID}/{filename}"
        }
        for document_type, filename in files
    ]

    return documents


# ============================================================
# CSV HELPERS
# ============================================================

def load_csv_row(app_id):

    with open(CSV_FILE, "r", encoding="utf-8-sig") as file:
        for row in csv.DictReader(file):
            if row["App_ID"].strip() == app_id:
                return {key.strip(): (value or "").strip() for key, value in row.items()}

    raise ValueError(f"{app_id} not found in {CSV_FILE.name}")


def split_list(value):

    return [item.strip() for item in value.split(",") if item.strip()]


def blank_to_none(value):

    return value if value else None


def to_int(value):

    return int(float(value)) if value else None


def to_float(value):

    return float(value) if value else None


# ============================================================
# INSERT APPLICANT FROM CSV
# ============================================================

def insert_applicant(connection):

    # --------------------------------------------------------
    # LOAD THE ROW FROM THE CSV
    # --------------------------------------------------------

    row = load_csv_row(APP_ID)

    # Comma-separated CSV cells become Python lists.
    # Json(...) below converts them to JSON before insertion.
    # PostgreSQL stores them as JSONB.

    ap_courses = split_list(row["AP_Courses"])
    activities = split_list(row["Activities"])
    awards = split_list(row["Awards"])
    hooks = split_list(row["Hooks"])

    documents = create_documents()


    # --------------------------------------------------------
    # SQL INSERT
    # --------------------------------------------------------

    insert_sql = """
    INSERT INTO simulated_applicant_data (

        App_ID,

        First_Name,
        Last_Name,
        Date_Of_Birth,

        Mailing_Address,
        Primary_Phone_Number,
        Email_Address,

        Gender,
        Ethnicity,

        Name_of_HS,
        Counselor_Name,

        Country,
        Region,

        Intended_Major,

        Superscored_SAT_Score,
        Superscored_ACT_Score,

        Unweighted_GPA,
        Weighted_GPA,

        Rank,

        AP_Courses,
        Total_APs,

        IB_Courses,
        Total_IBs,

        Activities,
        Awards,
        Hooks,

        Documents,

        Admission_Year,
        Admission_Term,

        Create_Date_Time,
        Last_Updated,

        Review_Ctr,

        Application_status,

        Final_Decision
    )

    VALUES (

        %(App_ID)s,

        %(First_Name)s,
        %(Last_Name)s,
        %(Date_Of_Birth)s,

        %(Mailing_Address)s,
        %(Primary_Phone_Number)s,
        %(Email_Address)s,

        %(Gender)s,
        %(Ethnicity)s,

        %(Name_of_HS)s,
        %(Counselor_Name)s,

        %(Country)s,
        %(Region)s,

        %(Intended_Major)s,

        %(Superscored_SAT_Score)s,
        %(Superscored_ACT_Score)s,

        %(Unweighted_GPA)s,
        %(Weighted_GPA)s,

        %(Rank)s,

        %(AP_Courses)s,
        %(Total_APs)s,

        %(IB_Courses)s,
        %(Total_IBs)s,

        %(Activities)s,
        %(Awards)s,
        %(Hooks)s,

        %(Documents)s,

        %(Admission_Year)s,
        %(Admission_Term)s,

        %(Create_Date_Time)s,
        %(Last_Updated)s,

        %(Review_Ctr)s,

        %(Application_status)s,

        %(Final_Decision)s
    )

    ON CONFLICT (App_ID)

    DO UPDATE SET

        First_Name =
            EXCLUDED.First_Name,

        Last_Name =
            EXCLUDED.Last_Name,

        Date_Of_Birth =
            EXCLUDED.Date_Of_Birth,

        Mailing_Address =
            EXCLUDED.Mailing_Address,

        Primary_Phone_Number =
            EXCLUDED.Primary_Phone_Number,

        Email_Address =
            EXCLUDED.Email_Address,

        Gender =
            EXCLUDED.Gender,

        Ethnicity =
            EXCLUDED.Ethnicity,

        Name_of_HS =
            EXCLUDED.Name_of_HS,

        Counselor_Name =
            EXCLUDED.Counselor_Name,

        Country =
            EXCLUDED.Country,

        Region =
            EXCLUDED.Region,

        Intended_Major =
            EXCLUDED.Intended_Major,

        Superscored_SAT_Score =
            EXCLUDED.Superscored_SAT_Score,

        Superscored_ACT_Score =
            EXCLUDED.Superscored_ACT_Score,

        Unweighted_GPA =
            EXCLUDED.Unweighted_GPA,

        Weighted_GPA =
            EXCLUDED.Weighted_GPA,

        Rank =
            EXCLUDED.Rank,

        AP_Courses =
            EXCLUDED.AP_Courses,

        Total_APs =
            EXCLUDED.Total_APs,

        IB_Courses =
            EXCLUDED.IB_Courses,

        Total_IBs =
            EXCLUDED.Total_IBs,

        Activities =
            EXCLUDED.Activities,

        Awards =
            EXCLUDED.Awards,

        Hooks =
            EXCLUDED.Hooks,

        Documents =
            EXCLUDED.Documents,

        Admission_Year =
            EXCLUDED.Admission_Year,

        Admission_Term =
            EXCLUDED.Admission_Term,

        Last_Updated =
            EXCLUDED.Last_Updated,

        Review_Ctr =
            EXCLUDED.Review_Ctr,

        Application_status =
            EXCLUDED.Application_status,

        Final_Decision =
            EXCLUDED.Final_Decision;
    """


    # --------------------------------------------------------
    # APPLICANT VALUES - EXACTLY AS IN THE CSV
    # --------------------------------------------------------

    applicant = {
        "App_ID": row["App_ID"],
        "First_Name": row["First_Name"],
        "Last_Name": row["Last_Name"],
        "Date_Of_Birth": blank_to_none(row["Date_Of_Birth"]),
        "Mailing_Address": row["Mailing_Address"],
        "Primary_Phone_Number": row["Primary_Phone_Number"],
        "Email_Address": row["Email_Address"],
        "Gender": row["Gender"],
        "Ethnicity": row["Ethnicity"],
        "Name_of_HS": row["Name_of_HS"],
        "Counselor_Name": row["Counselor_Name"],
        "Country": row["Country"],
        "Region": row["Region"],
        "Intended_Major": row["Intended_Major"],
        "Superscored_SAT_Score": to_int(row["Superscored_SAT_Score"]),
        "Superscored_ACT_Score": to_int(row["Superscored_ACT_Score"]),
        "Unweighted_GPA": to_float(row["Unweighted_GPA"]),
        "Weighted_GPA": to_float(row["Weighted_GPA"]),
        "Rank": blank_to_none(row["Rank"]),

        # Python list -> JSON -> PostgreSQL JSONB
        "AP_Courses": Json(ap_courses),
        "Total_APs": to_int(row["Total_APs"]),
        "IB_Courses": blank_to_none(row["IB_Courses"]),
        "Total_IBs": to_int(row["Total_IBs"]),
        "Activities": Json(activities),
        "Awards": Json(awards),
        "Hooks": Json(hooks),

        # References to MinIO objects.
        "Documents": Json(documents),

        "Admission_Year": to_int(row["Admission_Year"]),
        "Admission_Term": blank_to_none(row["Admission_Term"]),
        "Create_Date_Time": blank_to_none(row["Create_Date_Time"]),
        "Last_Updated": blank_to_none(row["Last_Updated"]),
        "Review_Ctr": to_int(row["Review_Ctr"]) or 0,

        # Simulates a successful completeness check (the CSV leaves
        # this blank; Danny's gate sets it in the real pipeline).
        "Application_status": "COMPLETE",

        "Final_Decision": blank_to_none(row["Final_Decision"]),
    }


    # --------------------------------------------------------
    # EXECUTE
    # --------------------------------------------------------

    with connection.cursor() as cursor:

        cursor.execute(
            insert_sql,
            applicant
        )

    connection.commit()

    print(f"{APP_ID} inserted from {CSV_FILE.name}.")


# ============================================================
# VERIFY THE RECORD
# ============================================================

def verify_applicant(connection):

    verify_sql = """
    SELECT

        App_ID,
        First_Name,
        Last_Name,

        Intended_Major,

        Superscored_SAT_Score,

        Unweighted_GPA,
        Weighted_GPA,

        AP_Courses,
        Total_APs,

        Activities,
        Awards,
        Hooks,

        Documents,

        Application_status

    FROM simulated_applicant_data

    WHERE App_ID = %s;
    """

    with connection.cursor() as cursor:

        cursor.execute(
            verify_sql,
            (APP_ID,)
        )

        row = cursor.fetchone()


    if row is None:

        print(f"ERROR: {APP_ID} was not found.")

        return


    print("\n====================================")
    print(f"{APP_ID} POSTGRESQL RECORD")
    print("====================================")

    print(f"App ID:        {row[0]}")
    print(f"Name:          {row[1]} {row[2]}")
    print(f"Major:         {row[3]}")
    print(f"SAT:           {row[4]}")
    print(f"Unweighted:    {row[5]}")
    print(f"Weighted:      {row[6]}")
    print(f"AP Courses:    {row[7]}")
    print(f"Total APs:     {row[8]}")
    print(f"Activities:    {row[9]}")
    print(f"Awards:        {row[10]}")
    print(f"Hooks:         {row[11]}")
    print(f"Status:        {row[13]}")


    print("\nMinIO document references:")

    documents = row[12]

    for document in documents:

        print(
            f"  {document['type']:<15} "
            f"-> {document['object_key']}"
        )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print("\n====================================")
    print("EAOS - SIMULATED POSTGRESQL")
    print("====================================\n")

    connection = None

    try:

        connection = connect_to_postgres()

        create_applicant_table(
            connection
        )

        insert_applicant(
            connection
        )

        verify_applicant(
            connection
        )

        print(
            "\nPostgreSQL simulation "
            "completed successfully."
        )

    except Exception as error:

        if connection:
            connection.rollback()

        print(
            f"\nPostgreSQL simulation failed:\n"
            f"{error}"
        )

        raise

    finally:

        if connection:
            connection.close()