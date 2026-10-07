FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PORT=8501 DB_PATH=/data/workshop.db TZ=Europe/Paris

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app

# Utilisateur non-root par défaut ; docker-compose.yml le remplace par l'UID:GID du NAS.
USER 1000:1000
EXPOSE 8501
# --preload : init DB une seule fois avant de lancer les 2 workers.
CMD exec gunicorn --preload -w 2 -b 0.0.0.0:${PORT} --access-logfile - 'app:create_app()'
