#!/bin/sh
# Double-click (macOS) or run (Linux) to start QualFrame. The first start downloads
# Python and the required packages; later starts take a few seconds.
cd "$(dirname "$0")" || exit 1
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv, a small tool that sets up Python for QualFrame..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"
  export PATH
fi
exec uv run --python 3.12 --extra llm qualframe start "$@"
