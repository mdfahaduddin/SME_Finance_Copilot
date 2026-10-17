# SME Finance Copilot API (production image)
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production

WORKDIR /app

# Tesseract OCR reads scanned PDF statements locally. English is included; add packs with e.g.
#   docker compose build --build-arg OCR_LANGS="ben"   (then set OCR_LANGUAGES=eng+ben)
ARG OCR_LANGS=""
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
       $(for l in $OCR_LANGS; do echo "tesseract-ocr-$l"; done) \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as an unprivileged user; the image needs no write access to its own code.
RUN useradd --system --uid 10001 --no-create-home app \
    && chmod +x docker-entrypoint.sh
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["serve"]
