FROM python:3.11-slim

WORKDIR /app

COPY correlator/online/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY correlator ./correlator

EXPOSE 8080

CMD ["python", "-u", "-m", "correlator.online.server"]
