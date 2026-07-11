# swobml-sync runs from a slim Python image: the package plus its two runtime
# dependencies (requests, lxml), which both ship manylinux wheels — so no build
# toolchain beyond what the slim base provides is needed. See docs/adr/0003.
FROM python:3.12-slim

# Flush stdout/stderr immediately so the JSON summary and progress logs surface
# in real time under `docker run` and container log drivers.
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Only the files needed to build and install the package; the build context is
# trimmed further by .dockerignore. README.md is required — pyproject names it
# as the project readme.
COPY pyproject.toml README.md ./
COPY src ./src

# Install the package with its runtime deps. --no-cache-dir keeps the image
# slim; pip resolves hatchling in an isolated, discarded build environment, so
# no build backend lingers in the final image.
RUN pip install --no-cache-dir .

# `docker run <image> <partner> <dir> ...` behaves exactly like the local CLI.
ENTRYPOINT ["swobml-sync"]
