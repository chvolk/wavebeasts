# Self-contained WaveBeasts site for Railway: builds the WaveBeast Go engine (the stateless resolver)
# and runs it alongside gunicorn in one service, so generation/battle rules stay DRY in the engine.
FROM golang:1.27 AS engine
RUN CGO_ENABLED=0 go install github.com/chvolk/wavebeast/cmd/wavebeast@main

FROM python:3.11-slim
WORKDIR /app
COPY --from=engine /go/bin/wavebeast /usr/local/bin/wavebeast
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN python manage.py collectstatic --noinput || true
ENV WAVEBEAST_RESOLVER=http://127.0.0.1:8777
ENV WAVEBEAST_DB=/tmp/wavebeast.db
ENV DEBUG=0
CMD ["./start.sh"]
