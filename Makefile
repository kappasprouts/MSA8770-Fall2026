.PHONY: check test

check:
	@./ingestion/run_check.sh data/batches/batch_01

test:
	@pytest tests/test_ingestion_and_gate.py -v
