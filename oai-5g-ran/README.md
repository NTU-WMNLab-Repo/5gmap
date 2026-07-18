# TODO: DL data plane still needs routing/debug. UE -> DNN ping and UL iperf3 are working; DNN -> UE/DL is not yet fully validated.

# TODO: 把oai和tolgaomeratalay那些docker image抓下來換成自己的，避免對方改版。

# OAI 5G RAN notes for 5GMAP

This directory contains the Helm charts used by `../script/deploy.sh` to deploy
OAI split RAN:

- `oai-gnb-cu`
- `oai-gnb-du`
- `oai-nr-ue`

The deployment path is:

```text
5GC slice -> OAI gNB-CU -> OAI gNB-DU -> OAI NR-UE
```

`script/deploy.sh` rewrites several chart values at runtime, including AMF IP,
slice SST/SD, release names, and per-user RAN names. Do not treat the pod IPs in
the committed `values.yaml` files as stable configuration; they are deployment
artifacts from the last run.

## RFsim configuration

OAI RFsim parameters use an indexed config section. The working command-line
syntax is:

```bash
--rfsimulator.[0].serveraddr server
--rfsimulator.[0].serveraddr oai-gnb-du10
```

The older-looking syntax below is not correct for this OAI develop image:

```bash
--rfsimulator.serveraddr server
```

The same indexing matters in config files. Use a list-like `rfsimulator` block:

```conf
rfsimulator = (
  {
    serveraddr = "oai-gnb-du10";
    serverport = "4043";
    options = "";
    modelname = "AWGN";
    IQfile = "/tmp/rfsimulator.iqs";
  }
);
```

Reference:
https://gitlab.eurecom.fr/oai/openairinterface5g/-/raw/develop/radio/rfsimulator/README.md

## CU, DU, and UE roles

For this split RAN deployment:

- The DU is the RFsim server: `--rfsimulator.[0].serveraddr server`
- The UE is the RFsim client: `--rfsimulator.[0].serveraddr oai-gnb-du10`
- The temporary Python RFsim relay is not used. It only connected two RFsim
  clients at TCP level and did not provide real RFsim server behavior.

Both DU and UE use `-E` so they agree on the same reduced sampling rate. Without
matching `-E`, the UE can connect but repeatedly fails initial synchronization.

Both DU and UE also use:

```bash
--thread-pool N
```

This is recommended by OAI for RFsim because it avoids extra worker scheduling
that can make timing-sensitive procedures less stable.

## RA response window

The DU config uses:

```conf
ra_ResponseWindow = 5;
```

In OAI config this value is an enum index, not the literal number of slots. The
commented value mapping is:

```text
1,2,4,8,10,20,40,80
```

So `4` means a 10-slot response window, and `5` means a 20-slot response window.
Using `8` is invalid for this OAI develop image and can make DU fail while
encoding `NR_RACH_ConfigCommon`.

The reason this matters in Kubernetes is that the DU was receiving PRACH but was
slightly too late to schedule Msg2/RAR:

```text
exceeded RA window, cannot schedule Msg2
```

Increasing the enum from `4` to `5` allowed the UE to move past RA and register
with AMF.

## Runtime pod IP placeholders

Some OAI config values must be the actual pod IP, but ConfigMaps cannot expand
Kubernetes downward API environment variables by themselves. The charts handle
this by writing placeholders into `gnb.conf`, copying it to `/tmp`, replacing
the placeholders at container startup, and then launching `nr-softmodem`.

CU placeholders:

```conf
GNB_IPV4_ADDRESS_FOR_NG_AMF = "__GNB_NGA_IP_ADDRESS__";
GNB_IPV4_ADDRESS_FOR_NGU    = "__GNB_NGU_IP_ADDRESS__";
```

DU placeholder:

```conf
local_n_address = "__F1_DU_IP_ADDRESS__";
```

These are replaced from environment variables populated by `status.podIP`.

This is important for user-plane setup. If CU/DU advertise `0.0.0.0`, NGAP and
F1 can still appear healthy, but GTP-U tunnels can be created with unusable
remote addresses.

## Current validation path

Useful checks after deployment:

```bash
kubectl -n oai logs deploy/oai-gnb-du10 --container gnbdu --tail 120
kubectl -n oai logs deploy/oai-nr-ue10 --container nr-ue --tail 120
kubectl -n oai logs deploy/oai-amf10 --container amf --tail 120
```

Healthy control-plane signs:

- DU log shows the UE as `in-sync`
- UE log shows PBCH/SIB1 decode and RRC progress
- AMF log shows the IMSI in `5GMM-REGISTERED`

Traffic test:

```bash
./script/start_traffic.sh zoomv3 1 1 1 0
```

At the time these notes were written, control plane and PDU session setup were
working, while end-to-end ICMP traffic still needed user-plane debugging.
