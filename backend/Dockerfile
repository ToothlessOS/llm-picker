# syntax=docker/dockerfile:1
#
# Single stage, deliberately: every dependency in the closure (pandas, pyarrow,
# numpy, datasets) publishes a cp313 manylinux wheel, so no compiler toolchain
# is needed and a builder stage would only duplicate a very large venv.
FROM python:3.13-slim

# Copied from uv's own image and pinned, rather than `curl … | sh`, which would
# fetch whatever happens to be current. This must stay in step with the uv that
# wrote `uv.lock` (`uv --version` on the dev machine is 0.11.12) so a lockfile
# format change cannot land silently in a deploy.
COPY --from=ghcr.io/astral-sh/uv:0.11.12 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    # The uv cache and the venv live on different layers, so hardlinks cannot work.
    UV_LINK_MODE=copy \
    # The base image already ships the 3.13 that `.python-version` asks for.
    # Without this, uv may download its own interpreter and build the venv on a
    # different Python from the one `/usr/local/bin/python` names.
    UV_PYTHON_PREFERENCE=only-system \
    # `datasets` caches the LMArena download here. Left at the default it would
    # land in the container's writable layer (HOME is /app, see the useradd
    # below) and be re-downloaded on every recreate. docker-compose.yml mounts a
    # named volume at this path.
    HF_HOME=/cache/hf

WORKDIR /app

# `/data` holds the SQLite database; `/app/staticfiles` is collectstatic's
# target. Both are created *and chowned here* so that a fresh named volume,
# which Docker initialises from the image path, inherits app ownership rather
# than arriving as root and leaving SQLite unable to write.
RUN groupadd --system django \
 && useradd --system --gid django --home-dir /app django \
 && mkdir -p /app/staticfiles /data /cache/hf \
 && chown -R django:django /app /data /cache/hf

# Dependencies first, keyed only on the two files uv needs to resolve, so that
# editing application source below does not invalidate this layer.
COPY pyproject.toml uv.lock /app/
RUN uv sync --frozen --no-dev --no-install-project

COPY . /app/
# The exec bit on entrypoint.sh is restored here rather than relied upon from
# the build context: a fresh clone or an archive transfer can drop it, and the
# failure ("permission denied" from the container runtime) is not obvious.
RUN chown -R django:django /app \
 && chmod +x /app/docker/entrypoint.sh

# The line that makes `python`, `celery` and `gunicorn` resolve to the project
# venv. `uv sync` creates /app/.venv but puts nothing on PATH, so a bare
# `python` would otherwise be the system interpreter -- which has no Django.
ENV PATH="/app/.venv/bin:$PATH"

USER django

EXPOSE 8000

ENTRYPOINT ["/app/docker/entrypoint.sh"]

# `llm_picker_backend.wsgi`, not `config.wsgi`: that is this project's module.
# No --chdir or PYTHONPATH is needed -- gunicorn inserts its chdir (the cwd,
# which WORKDIR sets to /app) into sys.path.
CMD ["gunicorn", "llm_picker_backend.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--timeout", "60", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
