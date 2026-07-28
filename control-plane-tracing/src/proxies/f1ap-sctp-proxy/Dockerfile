FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libsctp-dev \
    lksctp-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY proxies/f1ap-sctp-proxy/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY protocols ./protocols
COPY proxies ./proxies

CMD ["python3", "-u", "proxies/f1ap-sctp-proxy/f1ap_sctp_proxy.py"]
