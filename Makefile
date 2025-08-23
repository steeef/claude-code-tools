.PHONY: install release patch minor major dev-install help clean all-patch all-minor release-github lmsh lmsh-install lmsh-publish

help:
	@echo "Available commands:"
	@echo "  make install      - Install in editable mode (for development)"
	@echo "  make dev-install  - Install with dev dependencies (includes commitizen)"
	@echo "  make release      - Bump patch version and install globally"
	@echo "  make patch        - Bump patch version (0.0.X) and install"
	@echo "  make minor        - Bump minor version (0.X.0) and install"
	@echo "  make major        - Bump major version (X.0.0) and install"
	@echo "  make all-patch    - Bump patch, clean, and build (ready for uv publish)"
	@echo "  make all-minor    - Bump minor, clean, and build (ready for uv publish)"
	@echo "  make clean        - Clean build artifacts"
	@echo "  make release-github - Create GitHub release from latest tag"
	@echo "  make lmsh      - Build lmsh binary (requires Rust)"
	@echo "  make lmsh-install - Build and install lmsh to ~/.cargo/bin"
	@echo "  make lmsh-publish - Publish lmsh to crates.io"

install:
	uv tool install --force -e .
	@if command -v cargo >/dev/null 2>&1; then \
		echo "Building and installing lmsh..."; \
		cd lmsh && cargo build --release; \
		mkdir -p ~/.cargo/bin; \
		cp target/release/lmsh ~/.cargo/bin/; \
		echo "lmsh installed to ~/.cargo/bin/lmsh"; \
		if ! echo "$$PATH" | grep -q ".cargo/bin"; then \
			echo "⚠️  Add ~/.cargo/bin to your PATH if not already there"; \
		fi; \
	else \
		echo "Rust/cargo not found - skipping lmsh installation"; \
		echo "To install lmsh later, run: make lmsh-install"; \
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

all-minor:
	@echo "Bumping minor version..."
	uv run cz bump --increment MINOR --yes
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

lmsh:
	@echo "Building lmsh..."
	@cd lmsh && cargo build --release
	@echo "lmsh built at: lmsh/target/release/lmsh"

lmsh-install: lmsh
	@echo "Installing lmsh to ~/.cargo/bin..."
	@mkdir -p ~/.cargo/bin
	@cp lmsh/target/release/lmsh ~/.cargo/bin/
	@echo "lmsh installed to ~/.cargo/bin/lmsh"
	@if ! echo "$$PATH" | grep -q ".cargo/bin"; then \
		echo "⚠️  Add ~/.cargo/bin to your PATH if not already there"; \
	fi

lmsh-publish:
	@echo "Publishing lmsh to crates.io..."
	@cd lmsh && cargo publish --allow-dirty
	@echo "Published! Users can now install with: cargo install lmsh"