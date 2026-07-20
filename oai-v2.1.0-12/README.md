# E2E 5G Deployment Example

This directory provides an example deployment of an end-to-end (E2E) OpenAirInterface (OAI) 5G network (cn5g-fed-v2.1.0) using Helm charts on Kubernetes.

The deployment includes:

- OAI 5G Core (CN)
- OAI CU
- OAI DU
- OAI NR UE

---

## Deployment

### 1. Reset the Environment

```bash
cd ~/oai-cn5g-fed/charts
./tb_reset.sh
```

---

### 2. Deploy the 5G Core

```bash
cd ~/oai-cn5g-fed/charts/oai-5g-core/oai-5g-basic

helm dependency update
helm install oai-5g-basic .
```

---

### 3. Deploy the CU

```bash
cd ~/oai-cn5g-fed/charts/oai-5g-ran/oai-cu

helm install oai-gnb-cu .
```

---

### 4. Verify CN ↔ CU Connection

Check that all pods are running:

```bash
kubectl -n default get pods -o wide
```

Monitor AMF:

```bash
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/name=oai-amf -o name) --tail 1000
```

Monitor CU:

```bash
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/instance=oai-gnb-cu -o name) --tail 1000
```

Monitor UPF:

```bash
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/name=oai-upf -o name) --tail 1000
```

Wait until the CU successfully connects to the Core Network before continuing.

---

### 5. Deploy the DU

Apply the shared service (shared service is used for DU fault tolerant):

```bash
cd ~/oai-cn5g-fed/charts/oai-5g-ran/oai-du

kubectl apply -f shared_service.yaml
```

Install the primary DU:

```bash
helm install oai-du-prime . -f values_prime.yaml
```

---

### 6. Deploy the NR UE

```bash
cd ~/oai-cn5g-fed/charts/oai-5g-ran/oai-nr-ue

helm install oai-nr-ue .
```

---

### 7. Verify the Complete Connection

Check pod status:

```bash
kubectl -n default get pods -o wide
```

Monitor the logs:

AMF

```bash
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/name=oai-amf -o name) --tail 1000
```

CU

```bash
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/instance=oai-gnb-cu -o name) --tail 1000
```

DU

```bash
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/instance=oai-du-prime -o name) --tail 1000
```

NR UE

```bash
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/instance=oai-nr-ue -o name) --tail 1000
```

---

### 8. Validate the End-to-End Link (pass)

```bash
cd ~/oai-cn5g-fed/charts

./check_link.sh
```

---

### 9. Deploy the DU backup

Install the backup DU:

```bash
cd ~/oai-cn5g-fed/charts/oai-5g-ran/oai-du
helm install oai-du-backup . -f values_backup.yaml
# monitor
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/instance=oai-du-backup -o name)
```

---

### 10. Kill the DU prime

For fault tolerant testing.

```bash
kubectl scale deployment oai-du-prime --replicas=0
```

---

### 11. Check control plane

check if the UE restart and register.

```bash
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/name=oai-amf -o name) --tail 1000
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/instance=oai-gnb-cu -o name) --tail 1000
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/instance=oai-du-backup -o name) --tail 1000
kubectl logs -f $(kubectl get pods -l app.kubernetes.io/instance=oai-nr-ue -o name) --tail 1000
```

---

### 12. Validate the End-to-End Link (failed)

```bash
cd ~/oai-cn5g-fed/charts

./check_link.sh
```