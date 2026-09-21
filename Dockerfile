# Self-contained WaveBeasts site for Railway. The engine (stateless resolver) source is PRIVATE, so we
# fetch the prebuilt static Linux binary from the public downloads repo instead of building from source.
# Rebuild + re-upload that artifact (see scripts/) whenever the engine changes.
FROM python:3.11-slim
WORKDIR /app
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
