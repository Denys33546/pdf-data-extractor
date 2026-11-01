FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN useradd --create-home --uid 1000 appuser

# dependencies first: this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pdf_extractor ./pdf_extractor
COPY samples ./samples

USER appuser

ENTRYPOINT ["python", "-m", "pdf_extractor"]
CMD ["--help"]