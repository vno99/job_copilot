# Extension de l'image Airflow officielle avec les dépendances applicatives.
# Utilisé par `build: .` du docker-compose.yaml.
FROM apache/airflow:3.1.8

USER root

RUN apt-get update && apt-get install -y \
    # Bibliothèques de base
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxcursor1 \
    libxdamage1 \
    libxi6 \
    libxtst6 \
    libxrandr2 \
    libasound2 \
    libpangocairo-1.0-0 \
    libpango-1.0-0 \
    libcairo2 \
    libatspi2.0-0 \
    libgtk-3-0 \
    libgbm-dev \
    libxshmfence-dev \
    # Bibliothèques supplémentaires souvent nécessaires
    libdrm2 \
    libxkbcommon0 \
    libxfixes3 \
    libxrender1 \
    libxext6 \
    libx11-6 \
    libxrandr2 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrender1 \
    libxext6 \
    libx11-6 \
    # Utilitaires
    wget \
    curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /requirements.txt
USER airflow
RUN pip install --no-cache-dir -r /requirements.txt

RUN playwright install chromium