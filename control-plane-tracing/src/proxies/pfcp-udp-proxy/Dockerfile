FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY proxies/pfcp-udp-proxy/requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

COPY protocols ./protocols
COPY proxies ./proxies
COPY correlator ./correlator

CMD ["python3", "-u", "proxies/pfcp-udp-proxy/pfcp_udp_proxy.py"]
