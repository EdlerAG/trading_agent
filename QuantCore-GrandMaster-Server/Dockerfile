FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=1 \
    OMP_NUM_THREADS=1 \
    MKL_NUM_THREADS=1 \
    OPENBLAS_NUM_THREADS=1 \
    VECLIB_MAXIMUM_THREADS=1 \
    NUMEXPR_NUM_THREADS=1 \
    MALLOC_TRIM_THRESHOLD_=65536 \
    MALLOC_ARENA_MAX=2

WORKDIR /srv/quantcore

RUN apt-get update -qq && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --compile -r requirements.txt

COPY . .
RUN mkdir -p storage/cartridges storage/backups

EXPOSE 8501

CMD ["python", "main.py"]