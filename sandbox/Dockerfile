# Sandbox in which the agent runs the tests.
# The repository is mounted read-only at /repo on start.
FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==9.2.0

ENV PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home sandbox
USER sandbox
WORKDIR /repo
