# E2E 5G Deployment Example

This directory provides an example deployment of an end-to-end (E2E) OpenAirInterface (OAI) 5G network (cn5g-fed-v2.1.0) using Helm charts on Kubernetes.

The deployment includes:

- OAI 5G Core (CN)
- OAI CU
- OAI DU
- OAI NR UE

---

# Prerequest

## k8s cluster environment

### fix IP
```bash
sudo vi /etc/netplan/50-cloud-init.yaml
```
example yaml:
```yaml
network:
  version: 2
  ethernets:
    ens33:
      dhcp4: no
      addresses:
        - 192.168.168.61/24
      routes:
        - to: default
          via: 192.168.168.2
      nameservers:
        addresses:
          - 8.8.8.8
          - 8.8.4.4
```
```bash
sudo netplan apply
```

### k8s installation (on all nodes)

```bash
# uninstall k8s
sudo systemctl stop kubelet
sudo kubeadm reset
sudo apt-get purge kubeadm kubectl kubelet kubernetes-cni kube*
sudo apt-get autoremove
sudo rm -rf $HOME/.kube
sudo rm -rf /etc/cni/net.d
sudo iptables --flush

# install k8s (v1.31)
sudo apt-get update
sudo apt-get install -y apt-transport-https ca-certificates curl gpg
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.31/deb/Release.key | sudo gpg --dearmor -o /etc/apt/keyrings/kubernetes-apt-keyring.gpg
echo 'deb [signed-by=/etc/apt/keyrings/kubernetes-apt-keyring.gpg] https://pkgs.k8s.io/core:/stable:/v1.31/deb/ /' | sudo tee /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update
sudo apt-get install -y kubelet kubeadm kubectl
sudo apt-mark hold kubelet kubeadm kubectl
sudo systemctl enable --now kubelet
```

### container runtime installation (all nodes)

```bash
# uninstall docker
sudo systemctl stop docker
sudo systemctl stop containerd
sudo systemctl stop docker.socket
sudo apt-get purge -y docker.io
sudo apt-get purge -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin docker-ce-rootless-extras
dpkg -l | grep -i docker # see your installed packages

# install docker
# sudo apt-get install -y docker.io
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# containerd setup
sudo mkdir /etc/containerd
sudo sh -c "containerd config default > /etc/containerd/config.toml"
sudo sed -i 's/ SystemdCgroup = false/ SystemdCgroup = true/' /etc/containerd/config.toml
sudo systemctl restart containerd
sudo systemctl restart kubelet

sudo docker info | grep -i cgroup # ensure docker use systemd cgroup driver

sudo usermod -a -G docker $(whoami)
```

### machine setup (all nodes)

```bash
# machine setup
sudo swapoff -a
sudo vi /etc/fstab # any lines contain "swap"
sudo hostnamectl set-hostname <name> # set hostname on all nodes
sudo vi /etc/hosts # set dns on all nodes (192.168.50.119 master, ...)

# kernel module
cat <<EOF | sudo tee /etc/modules-load.d/k8s.conf
overlay
br_netfilter
EOF
sudo modprobe overlay
sudo modprobe br_netfilter

# kernel parameter
cat <<EOF | sudo tee /etc/sysctl.d/k8s.conf
net.bridge.bridge-nf-call-iptables  = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward                 = 1
EOF
sudo sysctl --system
```

### download conntrack (all node)

```bash
sudo apt-get update
sudo apt-get install -y conntrack
```

### cluster initialization

```bash
# pull image on master node
sudo kubeadm config images pull

# master node delete init
sudo kubeadm reset
sudo rm -rf /etc/cni/net.d
sudo rm -rf /var/lib/cni/
sudo rm -rf /var/lib/kubelet/*
sudo rm -rf /etc/kubernetes/
sudo systemctl stop kubelet
sudo systemctl stop containerd
# check if there is pod left over
sudo crictl ps
# if there is
sudo crictl rm -f $(sudo crictl ps -q)
# reset
sudo systemctl restart containerd
sudo systemctl restart kubelet

# master node initialization
sudo kubeadm init \
    --apiserver-advertise-address=192.168.168.87 \
    --pod-network-cidr=10.244.0.0/16
mkdir -p $HOME/.kube
sudo cp -i /etc/kubernetes/admin.conf $HOME/.kube/config
sudo chown $(id -u):$(id -g) $HOME/.kube/config

curl https://raw.githubusercontent.com/projectcalico/calico/v3.26.0/manifests/calico.yaml -O
kubectl apply -f calico.yaml

# worker node initialization
<provided kubeadm join command>

# check cluster status
kubectl get nodes # check joined worker nodes
kubectl get nodes -o wide
kubectl get pods --all-namespaces # confirm the cluster is running
kubeadm token create --print-join-command # if you forgot the command
```

## helm install and git clone

On control node:

```bash
sudo swapoff -a

# install helm
curl -fsSL https://raw.githubusercontent.com/helm/helm/master/scripts/get-helm-3 | bash
helm version

# clone repo
# git clone https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed.git
# git clone --branch v2.1.0-1.2 --depth 1 https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed.git 
git clone --branch master --depth 10 https://gitlab.eurecom.fr/oai/cn5g/oai-cn5g-fed.git
cd oai-cn5g-fed
git checkout 6bb0b69
```

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