FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
COPY dist/qf-1.0.2-py3-none-any.whl dist/

# Install into /install prefix so we can copy cleanly
RUN pip install --no-cache-dir --prefix=/install \
    dist/qf-1.0.2-py3-none-any.whl \
    -r requirements.txt


FROM python:3.12-slim

RUN useradd --create-home --shell /bin/bash appuser

WORKDIR /app

COPY --from=builder /install /usr/local

# Copy application code
COPY . .

RUN mkdir -p /app/data && chown -R appuser:appuser /app

USER appuser

EXPOSE 5100

CMD ["python", "main.py"]
