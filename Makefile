.PHONY: check test

check:
	@./run_check.sh batch_01

test:
	@pytest tests/test_ingestion_and_gate.py -v
