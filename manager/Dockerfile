FROM ghcr.io/sagernet/sing-box:v1.14.3 AS sing-box

FROM python:3.12-alpine
COPY --from=sing-box /usr/local/bin/sing-box /usr/local/bin/sing-box
COPY manager/app.py /app/app.py
COPY manager/telemetry.py /app/telemetry.py
COPY manager/dashboard.js /app/dashboard.js
RUN mkdir -p /data && chown -R 10001:10001 /data /app
USER 10001:10001
EXPOSE 8080 10000
CMD ["python3", "/app/app.py"]
