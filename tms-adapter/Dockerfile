# Multi-stage, Alpine (perl-free → avoids the unfixed Debian perl CVEs), non-root.
# The build stage installs the package + deps into a prefix; the runtime stage copies
# just that prefix (no build tooling, no source tree). Deps are pure-Python wheels plus
# pydantic-core (which ships musllinux wheels), so nothing compiles.
FROM python:3.12-alpine AS build
WORKDIR /src
COPY pyproject.toml ./
COPY app ./app
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-alpine
RUN adduser -D -u 10001 appuser
WORKDIR /app
COPY --from=build /install /usr/local
USER appuser

EXPOSE 8000
# Honour Railway's injected $PORT; default 8000 for local/compose.
ENV PORT=8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://localhost:%s/healthz' % os.environ.get('PORT','8000'))" || exit 1
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
