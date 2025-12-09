#!/bin/bash
#
# Update Homebrew formula with new version and sha256 checksums.
# Usage: ./scripts/update-homebrew-formula.sh <version>
# Example: ./scripts/update-homebrew-formula.sh 0.1.4
#
# This script:
# 1. Downloads macOS release tarballs from GitHub
# 2. Computes sha256 checksums
# 3. Generates the formula file
# 4. Optionally commits and pushes to homebrew-tap repo

set -e

VERSION="${1:-}"
REPO="pchalasani/claude-code-tools"
TAP_REPO="${HOME}/Git/homebrew-tap"
FORMULA_FILE="${TAP_REPO}/Formula/aichat-search.rb"

if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 <version>"
    echo "Example: $0 0.1.4"
    exit 1
fi

# Ensure tap repo exists
if [[ ! -d "$TAP_REPO" ]]; then
    echo "Error: homebrew-tap repo not found at $TAP_REPO"
    echo "Clone it first: gh repo clone pchalasani/homebrew-tap ~/Git/homebrew-tap"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_FILE="${SCRIPT_DIR}/aichat-search.rb.template"

echo "Updating formula for version $VERSION..."

# Base URL for release assets
BASE_URL="https://github.com/${REPO}/releases/download/rust-v${VERSION}"

# Download and compute sha256 for each platform
echo "Computing sha256 for macOS ARM64..."
SHA_ARM64=$(curl -sL "${BASE_URL}/aichat-search-macos-arm64.tar.gz" | shasum -a 256 | cut -d' ' -f1)
echo "  $SHA_ARM64"

echo "Computing sha256 for macOS Intel..."
SHA_INTEL=$(curl -sL "${BASE_URL}/aichat-search-macos-intel.tar.gz" | shasum -a 256 | cut -d' ' -f1)
echo "  $SHA_INTEL"

echo "Computing sha256 for Linux x86_64..."
SHA_LINUX_X86=$(curl -sL "${BASE_URL}/aichat-search-linux-x86_64.tar.gz" | shasum -a 256 | cut -d' ' -f1)
echo "  $SHA_LINUX_X86"

echo "Computing sha256 for Linux ARM64..."
SHA_LINUX_ARM=$(curl -sL "${BASE_URL}/aichat-search-linux-arm64.tar.gz" | shasum -a 256 | cut -d' ' -f1)
echo "  $SHA_LINUX_ARM"

# Create Formula directory if needed
mkdir -p "$(dirname "$FORMULA_FILE")"

# Copy template and replace placeholders
cp "$TEMPLATE_FILE" "$FORMULA_FILE"
sed -i '' "s/REPLACE_VERSION/${VERSION}/g" "$FORMULA_FILE"
sed -i '' "s/REPLACE_SHA_ARM64/${SHA_ARM64}/g" "$FORMULA_FILE"
sed -i '' "s/REPLACE_SHA_INTEL/${SHA_INTEL}/g" "$FORMULA_FILE"
sed -i '' "s/REPLACE_SHA_LINUX_ARM/${SHA_LINUX_ARM}/g" "$FORMULA_FILE"
sed -i '' "s/REPLACE_SHA_LINUX_X86/${SHA_LINUX_X86}/g" "$FORMULA_FILE"

echo ""
echo "Formula written to: $FORMULA_FILE"
echo ""
cat "$FORMULA_FILE"
echo ""

# Ask whether to commit and push
read -p "Commit and push to homebrew-tap? [y/N] " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    cd "$TAP_REPO"
    git add Formula/aichat-search.rb
    git commit -m "Update aichat-search to ${VERSION}"
    git push origin main
    echo "Pushed to homebrew-tap!"
    echo ""
    echo "Users can now install with:"
    echo "  brew install pchalasani/tap/aichat-search"
fi
