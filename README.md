# MobiCom 2025 - 5G-MAP

This repo contains the bare-minimum code to reproduce the results of the MobiCom 2025 paper - 5G-MAP: Demystifying the Performance Implications of Cloud-Based 5G Core Deployments. This platform is currently undergoing commercialzation and forms the technical foundation of the Cellular Optimization, Security & Manamgent via Intelligent Control (COSMIC) platform. For more details please contact the authors of the paper.

This repository contains the instructions for:
- deployment of the 5G-MAP integrated OpenAirInterface 5G Core
- the source code of the 5G-MAP Side Car Proxy

# 5G Core Deploymment

**-----------------------**

## Deploying the Cluster and Running the Users

### Preliminaries

1. Docker installed on the target node
2. On the target node, set "AllowTCPForwarding" and "PermitRootLogin" to **yes** from /etc/ssh/sshd.conf  
3. On the target node, add current user, which will be used by the RKE to access the docker daemon to the docker group 
```
$ sudo usermod -aG docker $USER
```

### Step 1: Setting up the K8s Cluster

In this deployment, the K8s cluster is set up using the Ranchers Kubernetes Engine (RKE) which can be installed following this [link](https://rancher.com/docs/rke/latest/en/installation/). Certain RKE versions can only setup certain versions of Kubernetes. We used rke 1.4.3 with Kubernetes 1.24.8.


Once the RKE binary is setup, the [cluster.yaml](cluster.yml) file is used in order to setup the K8s cluster. The given file shows how to configure multiple nodes to be used in the same cluster. In order to adapt the yaml to one's own environment, change the following parameters:

1. Make the necessary modifications to the cluster.yaml. A sample snippet is shown below with the relevant descriptions
<pre>
\```yaml

- address: 10.0.1.165 # --> change to the address of the relevant node
  port: "22"
  role:
  - controlplane # --> remove if the node is a worker
  - etcd # --> remove if the node is a worker
  - worker # --> remove if the node is a control plane node
  user: ubuntu # --> change to the username on the relevant targent cluster node
  ssh_key_path: "~/.ssh/awscluster.pem" # --> change the name of the key to the one that will be used
  labels:
    type: az # --> Labeling the nodes in the cluster so that VNFs can be assigned to either the AZ or edge zones. Use 'az' for AZs and 'edge' for edge zones.

\```
</pre>

The above snippet shows an example for a single node in the cluster. 

a) IP addresses of the target nodes
b) If using a network abstraction with multiple subnets (as is the case with most OpenStack setups), change the "internal_address" variable for the pertaining subnet
c) The ssh key path to the key that is copied on all the hosts
d) The host usernames

 From the directory that contains the cluster.yaml file, run
```
$ rke up
```
2. Set up kubectl on your workstation by following this [link](https://kubernetes.io/docs/tasks/tools/install-kubectl-linux/).
3. The directory that you executed item 7 in Step 1 now contains the "kube_config_cluster.yml file", which is the configuration file of the cluster. Set up the access with

```
$ mkdir -p ~/.kube;
$  kube_config_cluster.yml ~/.kube/config; 
```

4. Install Helm

https://helm.sh/docs/intro/install/

### Step 2: Deploy the Instrumentation Pipeline

1. Add the required helm repositories to the Bastion node

```
helm repo add jaegertracing https://jaegertracing.github.io/helm-charts
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts
```

2. Create the necessary namespaces in the cluster

```
kubectl create ns jaeger; 
kubectl create ns otel; 
kubectl create ns oai
```

3. Deploy certificate manager

```
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.17.0/cert-manager.yaml
```

4. Install Jaeger using Helm charts

```
helm install jaeger jaegertracing/jaeger -n jaeger
```
This installation can take 4-5 minutes. Some pods may remain in CrashLoopBackOff but after 4-5 restarts all pods should be "Running"

5. In case DNS resolution does not work in the cluster, replace the IP of Jaeger Collector in the otel.yaml with the IP of Jaeger Collector pod

6. Install OpenTelemetry

```
helm upgrade --install opentelemetry-collector open-telemetry/opentelemetry-collector --version 0.65.0 --values otel.yaml -n test

```

7. Port Forward for UI access using public IP

```
kubectl port-forward -n jaeger service/jaeger-query --address 0.0.0.0 16686:80

```

### Step 3: Run the 5G Core

The 5G core is designed to run using the "one-click" mentality. A series of bash scripts will automate the deployment process and start the chosen traffic patterns depending on the selections made by the user. 


1. To run the deployment first instantiate the Mysql database.
```
helm install mysql mysql/ -n oai
```
2. Start the 5G deployment
```
./run.sh
```

To customize the deployment, the values in the run.sh file can be changed.


