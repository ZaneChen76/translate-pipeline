.PHONY: docs test

# Generate USAGE.md from CLI
docs:
	python3 scripts/gen_usage.py

# Basic tests
test:
	python3 -m unittest discover -s tests -p "test_*.py" -v
