# The interpreter is pinned, three ways, since 2026-10-10. The project requires Python
# >= 3.14 (pyproject / uv.lock / .python-version) but this image was python:3.12-slim, so
# uv fetched a managed interpreter during `uv sync`; .python-version was only copied AFTER
# that step, so an uncached build took the newest 3.14+ -- 3.15, for which the lock has no
# psycopg2-binary wheel -- and the source build died on pg_config (Actions run 38047810847,
# the first uncached build in a week). Production had been running uv-managed CPython 3.14.8
# inside a 3.12 base the whole time. Now the base IS 3.14 (digest-pinned so it cannot drift
# under us; bump the digest deliberately), .python-version travels with the lock, and uv
# may neither download another Python nor pick one other than the image's.
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170

# libgomp1: the OpenMP runtime LightGBM's native library needs. The API alone
# never imports lightgbm, so the slim image worked until the model pipeline
# (scheduler service) ran in this image too -- squad/minutes.py failed at
# import with "libgomp.so.1: cannot open shared object file" (2026-09-04).
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3.14

COPY .python-version pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen

COPY . .

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
