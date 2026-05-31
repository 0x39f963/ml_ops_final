# Generated at: 2026-05-31 20:37:33 MSK

.PHONY: data test up down leak-check

PYTHON ?= python3

data:
	$(PYTHON) -m src.gen_synthetic --rows 40000 --out data/sample_synth.parquet

test:
	@if find tests \( -name 'test_*.py' -o -name '*_test.py' \) | grep -q .; then \
		$(PYTHON) -m pytest -q; \
	else \
		echo "no tests yet"; \
	fi

up:
	# TODO b09: docker-compose services are added in the infra branch.
	docker compose up -d

down:
	docker compose down

leak-check:
	@set -eu; \
	echo "checking gitignore gates"; \
	for path in data/real.parquet models/model.pkl .env mlruns/; do \
		if ! git check-ignore -q -- "$$path"; then \
			echo "$$path must be ignored"; \
			exit 1; \
		fi; \
	done; \
	if git check-ignore -q -- data/sample_synth.parquet; then \
		echo "data/sample_synth.parquet must be allowed in git"; \
		exit 1; \
	fi; \
	echo "checking tracked and staged file list"; \
	bad_files="$$(git ls-files --cached --others --exclude-standard | grep -E '(^|/)(mlruns|airflow_home|logs)(/|$$)|(^|/)models/|\.pkl$$|\.joblib$$|^data/.+\.parquet$$' | grep -v '^data/sample_synth.parquet$$' | grep -v '^models/.gitkeep$$' || true)"; \
	if [ -n "$$bad_files" ]; then \
		echo "forbidden files detected:"; \
		printf '%s\n' "$$bad_files"; \
		exit 1; \
	fi; \
	files="$$(git ls-files --cached --others --exclude-standard | grep -v '^data/sample_synth.parquet$$' | grep -Ev '\.(parquet|png|jpg|jpeg|gif|pdf)$$' || true)"; \
	if [ -n "$${FORBIDDEN_COMPANY_NAME:-}" ] && [ -n "$$files" ]; then \
		echo "checking FORBIDDEN_COMPANY_NAME"; \
		if printf '%s\n' "$$files" | xargs grep -In -- "$$FORBIDDEN_COMPANY_NAME"; then \
			echo "forbidden company name detected"; \
			exit 1; \
		fi; \
	fi; \
	if [ -n "$$files" ]; then \
		raw_marker="product""_raw"; \
		id_pattern='(^|[^0-9.])[0-9]{10,12}([^0-9.]|$$)'; \
		if printf '%s\n' "$$files" | xargs grep -EIn "$$raw_marker|$$id_pattern"; then \
			echo "forbidden raw product marker or id-like number detected"; \
			exit 1; \
		fi; \
	fi; \
	echo "leak-check passed"
