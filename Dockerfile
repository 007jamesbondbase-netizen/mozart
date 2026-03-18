FROM python:3.11-slim

# FFmpeg + FluidSynth + SoundFont — tudo que o bot precisa
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libfluidsynth3 \
    fluid-soundfont-gm \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY mozart_maestro_v6.py .
COPY .env .env

CMD ["python3", "-u", "mozart_maestro_v6.py"]
