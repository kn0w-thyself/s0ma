#!/bin/bash
set -e
echo "=== s0ma Self-Check ==="
echo "Step 1: Type checking..."
mypy src/s0ma/ --strict
echo "Step 2: Linting..."
ruff check src/s0ma/
echo "Step 3: Bootstrap test (THE test)..."
pytest tests/test_bootstrap.py -v
echo "Step 4: Full test suite with coverage..."
pytest --cov=s0ma --cov-report=term-missing
echo "=== All checks passed ==="
