FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libsctp-dev \
    lksctp-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY f1ap_sctp_proxy.py .

CMD ["python3", "-u", "f1ap_sctp_proxy.py"]

