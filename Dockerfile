FROM python:3.12-slim

# libgomp1: the OpenMP runtime LightGBM's native library needs. The API alone
# never imports lightgbm, so the slim image worked until the model pipeline
# (scheduler service) ran in this image too -- squad/minutes.py failed at
# import with "libgomp.so.1: cannot open shared object file" (2026-09-04).
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen

COPY . .

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]