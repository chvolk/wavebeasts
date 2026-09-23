# Self-contained WaveBeasts site for Railway. The engine (stateless resolver) source is PRIVATE, so we
# fetch the prebuilt static Linux binary from the public downloads repo instead of building from source.
# Rebuild + re-upload that artifact (see scripts/) whenever the engine changes.
FROM python:3.11-slim
WORKDIR /app
# Bump ENGINE_REV whenever the engine binary is re-published so the ADD below re-fetches (it uses a fixed
# "latest" URL that Docker would otherwise cache). The RUN references the ARG, so changing it busts the
# cache from here down and pulls the fresh binary. 2026-09-21f: UI rebrand and local HP display.
ARG ENGINE_REV=2026-09-22-tutorial-0.12.12
RUN echo "engine rev ${ENGINE_REV}"
ADD https://github.com/chvolk/wavebeast-dl/releases/latest/download/wavebeast-linux-amd64 /usr/local/bin/wavebeast
RUN chmod +x /usr/local/bin/wavebeast && /usr/local/bin/wavebeast -version
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput || true
ENV WAVEBEAST_RESOLVER=http://127.0.0.1:8777
ENV WAVEBEAST_DB=/tmp/wavebeast.db
ENV DEBUG=0
CMD ["./start.sh"]
