#!/bin/bash
set -ex

##
## Create some aliases
##
echo 'alias ll="ls -alF"' >> $HOME/.bashrc
echo 'alias la="ls -A"' >> $HOME/.bashrc
echo 'alias l="ls -CF"' >> $HOME/.bashrc

# Convenience workspace directory for later use
WORKSPACE_DIR=$(pwd)

# Keep uv's cache inside the workspace so it survives container rebuilds.
export UV_CACHE_DIR="${WORKSPACE_DIR}/.cache/uv"
echo "export UV_CACHE_DIR=${UV_CACHE_DIR}" >> $HOME/.bashrc

# Now install all dependencies. These two commands are the documented dev setup
# in README.md -- keep them in step with it.
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -e ".[dev]"

# Drop straight into the venv on every new shell.
echo "source ${WORKSPACE_DIR}/.venv/bin/activate" >> $HOME/.bashrc

echo "Done!"