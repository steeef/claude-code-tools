.PHONY: install release patch minor major dev-install help clean all-patch release-github lmshell lmshell-install

help:
	@echo "Available commands:"
	@echo "  make install      - Install in editable mode (for development)"
	@echo "  make dev-install  - Install with dev dependencies (includes commitizen)"
	@echo "  make release      - Bump patch version and install globally"
	@echo "  make patch        - Bump patch version (0.0.X) and install"
	@echo "  make minor        - Bump minor version (0.X.0) and install"
	@echo "  make major        - Bump major version (X.0.0) and install"
	@echo "  make all-patch    - Bump patch, clean, and build (ready for uv publish)"
	@echo "  make clean        - Clean build artifacts"
	@echo "  make release-github - Create GitHub release from latest tag"
	@echo "  make lmshell      - Build lmshell binary (requires Rust)"
	@echo "  make lmshell-install - Build and install lmshell to /usr/local/bin"

install:
	uv tool install --force -e .
	@if command -v cargo >/dev/null 2>&1; then \
		echo "Building and installing lmshell..."; \
		cd lmshell && cargo build --release && sudo cp target/release/lmshell /usr/local/bin/; \
		echo "lmshell installed successfully to /usr/local/bin/lmshell"; \
	else \
		echo "Rust/cargo not found - skipping lmshell installation"; \
		echo "To install lmshell later, run: make lmshell-install"; \
	fi

dev-install:
	uv pip install -e ".[dev]"

release: patch

patch:
	@echo "Bumping patch version..."
	uv run cz bump --increment PATCH --yes
	uv tool install --force --reinstall .
	@echo "Installation complete!"

minor:
	@echo "Bumping minor version..."
	uv run cz bump --increment MINOR --yes
	uv tool install --force --reinstall .
	@echo "Installation complete!"

major:
	@echo "Bumping major version..."
	uv run cz bump --increment MAJOR --yes
	uv tool install --force --reinstall .
	@echo "Installation complete!"

clean:
	@echo "Cleaning build artifacts..."
	rm -rf dist/*
	@echo "Clean complete!"

all-patch:
	@echo "Bumping patch version..."
	uv run cz bump --increment PATCH --yes
	@echo "Pushing to GitHub..."
	git push && git push --tags
	@echo "Creating GitHub release..."
	@VERSION=$$(grep "^version" pyproject.toml | head -1 | cut -d'"' -f2); \
	gh release create v$$VERSION --title "v$$VERSION" --generate-notes || echo "Release v$$VERSION already exists"
	@echo "Cleaning old builds..."
	rm -rf dist/*
	@echo "Building package..."
	uv build
	@echo "Build complete! Ready for: uv publish --token YOUR_TOKEN"

release-github:
	@echo "Creating GitHub release..."
	@VERSION=$$(grep "^version" pyproject.toml | head -1 | cut -d'"' -f2); \
	gh release create v$$VERSION --title "v$$VERSION" --generate-notes
	@echo "GitHub release created!"

lmshell:
	@echo "Building lmshell..."
	@cd lmshell && cargo build --release
	@echo "lmshell built at: lmshell/target/release/lmshell"

lmshell-install: lmshell
	@echo "Installing lmshell to /usr/local/bin..."
	@sudo cp lmshell/target/release/lmshell /usr/local/bin/
	@echo "lmshell installed successfully to /usr/local/bin/lmshell"