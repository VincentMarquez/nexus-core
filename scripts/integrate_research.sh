#!/usr/bin/env bash
# Wire GitHub nexus-core (product) into the lab research tree.
# Safe: no delete, no overwrite of run.py — only helpers + PATH tips.
set -euo pipefail
PRODUCT="${NEXUS_PRODUCT_ROOT:-$HOME/nexus-core}"
LAB="${NEXUS_LAB_ROOT:-${NEXUS_LAB_ROOT:-~/lab}}"

if [[ ! -d "$PRODUCT/src/nexus" ]]; then
  echo "ERROR: product not found at $PRODUCT"
  exit 1
fi
if [[ ! -d "$LAB" ]]; then
  echo "ERROR: lab not found at $LAB"
  exit 1
fi

# ensure product venv + install
if [[ ! -x "$PRODUCT/.venv/bin/nexus" ]]; then
  echo "→ creating product venv + install"
  python3 -m venv "$PRODUCT/.venv"
  # shellcheck disable=SC1091
  source "$PRODUCT/.venv/bin/activate"
  pip install -e "$PRODUCT[dev]" -q
else
  # shellcheck disable=SC1091
  source "$PRODUCT/.venv/bin/activate"
  pip install -e "$PRODUCT[dev]" -q
fi

mkdir -p "$HOME/.local/bin"
ln -sfn "$PRODUCT/.venv/bin/nexus" "$HOME/.local/bin/nexus"
ln -sfn "$PRODUCT/.venv/bin/python" "$HOME/.local/bin/nexus-python"

# lab helper scripts (do not replace run.py)
mkdir -p "$LAB/bin"
cat > "$LAB/bin/nexus-alive-lab" <<EOF
#!/usr/bin/env bash
# Run product self-improve against the lab tree
export NEXUS_PROJECT_ROOT="$LAB"
export OLLAMA_HOST="\${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="\${OLLAMA_MODEL:-gemma4:26b}"
exec "$PRODUCT/.venv/bin/nexus" "\$@"
EOF
chmod +x "$LAB/bin/nexus-alive-lab"

cat > "$LAB/bin/nexus-alive-product" <<EOF
#!/usr/bin/env bash
# Run product self-improve against the GitHub package tree
export NEXUS_PROJECT_ROOT="$PRODUCT"
export OLLAMA_HOST="\${OLLAMA_HOST:-http://127.0.0.1:11434}"
export OLLAMA_MODEL="\${OLLAMA_MODEL:-gemma4:26b}"
exec "$PRODUCT/.venv/bin/nexus" "\$@"
EOF
chmod +x "$LAB/bin/nexus-alive-product"

# pointer file in lab
cat > "$LAB/NEXUS_PRODUCT.md" <<EOF
# Linked product CLI: nexus-core

- Product path: \`$PRODUCT\`
- GitHub: https://github.com/VincentMarquez/nexus-core
- Lab path: \`$LAB\`

## Commands from lab

\`\`\`bash
# improve the lab tree
./bin/nexus-alive-lab alive once
./bin/nexus-alive-lab github mine run -q "multi agent research" --improve

# improve the open-source product tree
./bin/nexus-alive-product alive once
./bin/nexus-alive-product demo --all --quick
\`\`\`

Boot lab infrastructure as usual:

\`\`\`bash
python3 run.py
\`\`\`

Docs: \`$PRODUCT/docs/MERGE_REAL_NEXUS.md\` · \`$PRODUCT/docs/ALIVE.md\`
EOF

echo "=== integrate complete ==="
echo "  product: $PRODUCT"
echo "  lab:     $LAB"
echo "  PATH:    ~/.local/bin/nexus → product CLI"
echo "  lab helpers:"
echo "    $LAB/bin/nexus-alive-lab      # NEXUS_PROJECT_ROOT=lab"
echo "    $LAB/bin/nexus-alive-product  # NEXUS_PROJECT_ROOT=product"
echo
echo "  PATH check: $(command -v nexus || echo 'restart shell or export PATH=\"\$HOME/.local/bin:\$PATH\"')"
echo
echo "  Real run (product self-improve):"
echo "    cd $PRODUCT && source .venv/bin/activate && nexus alive once"
