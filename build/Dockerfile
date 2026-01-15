FROM mcr.microsoft.com/playwright/python:v1.57.0-noble

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

COPY pyproject.toml requirements.txt README.md /app/
COPY src /app/src
COPY examples /app/examples

RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir .

RUN chown -R pwuser:pwuser /app

USER pwuser

CMD ["python", "-m", "community_intern", "run"]
