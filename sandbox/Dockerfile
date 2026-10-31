# Sandbox, in der der Agent die Tests ausführt.
# Das Repository wird beim Start schreibgeschützt nach /repo eingebunden.
FROM python:3.12-slim

RUN pip install --no-cache-dir pytest==9.2.0

ENV PYTHONDONTWRITEBYTECODE=1
RUN useradd --create-home sandbox
USER sandbox
WORKDIR /repo
