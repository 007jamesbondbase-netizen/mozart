FROM python:3.11-slim

# Instalar em etapas separadas — evita estouro de memória no build
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    libfluidsynth3 fluid-soundfont-gm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mozart_maestro_v6.py .

CMD ["python3", "-u", "mozart_maestro_v6.py"]
