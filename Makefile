install:
	conda deactivate -f
	python -m maturin develop

install-release:
	conda deactivate -f
	python -m maturin develop --release

pre-commit:
	cargo +nightly fmt --all && cargo clippy --all-features
	python -m ruff check . --fix --exit-non-zero-on-fix
	python -m ruff format polars_trading tests
	mypy polars_trading tests

test:
	python -m pytest tests

run: install
	conda deactivate -f
	python run.py

run-release: install-release
	conda deactivate -f
	python run.py

