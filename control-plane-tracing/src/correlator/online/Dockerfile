FROM python:3.11-slim

WORKDIR /app

COPY correlator ./correlator

EXPOSE 8080

CMD ["python", "-u", "correlator/online/server.py"]
