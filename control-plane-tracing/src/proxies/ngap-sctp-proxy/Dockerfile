FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    libsctp-dev \
    lksctp-tools \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY proxies/ngap-sctp-proxy/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY protocols ./protocols
COPY correlator ./correlator
COPY proxies ./proxies

CMD ["python3", "-u", "proxies/ngap-sctp-proxy/ngap_sctp_proxy.py"]
