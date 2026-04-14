# scintilla

# Show available recipes
default:
    @just --list

# Install package in editable mode with dev dependencies
install:
    pip install -e ".[dev]"

# Run all tests
test:
    python -m pytest tests/ -v

# Lint source files
lint:
    python -m ruff check src/

# Format source files
fmt:
    python -m ruff format src/

# Run py_compile check on a source file
check file:
    python -m py_compile {{file}}
