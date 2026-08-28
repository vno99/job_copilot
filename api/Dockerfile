# API FastAPI (service api/ du docker-compose).
#
# Dev-first : le code applicatif (src/, api/, config/, sql/, data/) est monté en
# volume depuis la racine du dépôt au runtime (comme les conteneurs Airflow).
# L'image ne contient que les dépendances Python.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
# Racine du dépôt montée dans le conteneur : permet les imports src.*, config.* et api.*
ENV PYTHONPATH=/workspace

WORKDIR /workspace

# Dépendances copiées avant le code pour bénéficier du cache de build Docker.
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Navigateur headless pour la récupération d'offres (feature « Ajouter des
# offres d'emploi », POST /job-offers/from-url) : installe Chromium + les
# dépendances système. (python:3.12-slim en root → `--with-deps` OK.)
RUN playwright install --with-deps chromium

EXPOSE 8000

CMD ["uvicorn", "api.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
