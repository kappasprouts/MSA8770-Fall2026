# Actual receiving-system outcomes

Captured before disposable schemas/buckets were removed. Model responses are controlled. Object verification compares actual received bytes to registered metadata.

## test_same_batch_drop_twice_has_one_receiver_effect_and_one_dossier_each

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | DOSSIER_READY | 1 | 1 | PUBLISHED | 1 | 5 | True |
| APP_102 | DOSSIER_READY | 2 | 1 | PUBLISHED | 1 | 5 | True |

Intake receipts: 1; generation batches: 1; orphan rows: 1; total objects: 11.

## test_real_batch_interruption_after_one_dossier_resumes_second_from_sections

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | DOSSIER_READY | 1 | 1 | PUBLISHED | 1 | 5 | True |
| APP_102 | DOSSIER_READY | 2 | 1 | PUBLISHED | 1 | 5 | True |

Intake receipts: 1; generation batches: 1; orphan rows: 1; total objects: 11.

## test_completed_intake_missing_report_recovers_artifacts_without_reingestion

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |
| APP_102 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |

Intake receipts: 1; generation batches: 0; orphan rows: 1; total objects: 11.

## test_missing_or_changed_receiving_object_does_not_replay_old_ingestion[missing]

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | READY_FOR_REVIEW | none | 0 | none | 0 | 4 | False |
| APP_102 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |

Intake receipts: 1; generation batches: 0; orphan rows: 1; total objects: 10.

## test_missing_or_changed_receiving_object_does_not_replay_old_ingestion[changed]

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | False |
| APP_102 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |

Intake receipts: 1; generation batches: 0; orphan rows: 1; total objects: 11.

## test_changed_batch_creates_a_new_event

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |
| APP_102 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |

Intake receipts: 2; generation batches: 0; orphan rows: 1; total objects: 11.

## test_intake_without_receiver_receipt_requires_explicit_repair_scope

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |
| APP_102 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |

Intake receipts: 2; generation batches: 0; orphan rows: 1; total objects: 11.

## test_unconfirmed_handoff_cannot_start_generation

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |
| APP_102 | READY_FOR_REVIEW | none | 0 | none | 0 | 5 | True |

Intake receipts: 1; generation batches: 0; orphan rows: 1; total objects: 11.

## test_cross_process_batch_lock_prevents_overlapping_ingestion

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |

Intake receipts: 0; generation batches: 0; orphan rows: 0; total objects: 0.

## test_cli_style_runner_persists_handoff_without_api_summary_wrapper

| Applicant | Final DB status | Run IDs | Dossier rows | Review state | Receipts | MinIO objects | SHA-256 match |
| --- | --- | --- | --- | --- | --- | --- | --- |
| APP_101 | DOSSIER_READY | 1 | 1 | PUBLISHED | 1 | 5 | True |
| APP_102 | DOSSIER_READY | 2 | 1 | PUBLISHED | 1 | 5 | True |

Intake receipts: 1; generation batches: 1; orphan rows: 1; total objects: 11.

