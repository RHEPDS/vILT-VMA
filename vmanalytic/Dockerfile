# VMAnalytic — Flask + Gunicorn (production-style container)
#
# OpenShift helper (o-i-creator): set OIC_STATIC_ROOT to a directory that contains
# the static export (index.html + assets/). Example bind-mount at run time:
#   docker run ... -v /path/to/o-i-creator/static:/app/oic-static:ro -e OIC_STATIC_ROOT=/app/oic-static ...
#
# SPDX-License-Identifier: GPL-2.0-only

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    OIC_STATIC_ROOT=/app/oic-static

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir 'gunicorn>=22.0.0'

COPY web/ web/
COPY vm_analysis/ vm_analysis/
COPY helper_files/ helper_files/

# Writable dirs (upload sessions, optional CSV cache)
RUN mkdir -p data/uploads saved_csv_files oic-static \
    && chmod -R u+rwX data saved_csv_files oic-static

# Non-root runtime
RUN useradd --create-home --uid 1000 --shell /bin/bash vmanalytic \
    && chown -R vmanalytic:vmanalytic /app
USER vmanalytic

EXPOSE 5000

# Long timeout: analysis can run several minutes on large inventories
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "2", "--timeout", "600", "web.app:app"]
