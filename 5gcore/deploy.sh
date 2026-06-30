# deploy.sh
#!/bin/bash

st=`date +%s`
#---------------------------------------------------------------
#---------------------------------------------------------------
GREEN='\x1b[32m'
BLUE='\x1b[34m'
NC='\033[0m'

bold=$(tput bold)
NORMAL=$(tput sgr0)
#---------------------------------------------------------------
#---------------------------------------------------------------

opmode="OTEL"
loglevel="trace"
proxyport="11095"
serviceport="8080"
proxyversion="7.0.0"

#---------------------------------------------------------------
nrfloc="edge"
udrloc="az"
udmloc="az"
ausfloc="az"
amfloc="edge"
smfloc="edge"

#---- DO NOT CHANGE THESE ----
upfloc="edge"
gnbsimloc="az"
dnnloc="edge"

# Function to wait for a pod with a specific name prefix to be running
wait_for_pod() {
	echo -e "${BLUE} ${bold} Waiting for pod deployment ${NC} ${NORMAL}"
    local namespace=$1
    local pod_name_prefix=$2

    # Check if the pod is running
    local is_pod_running=false
    while [ "$is_pod_running" = false ]; do
        # Get the status of the pod by name prefix
        local pod_name=$(kubectl get pods -n "$namespace" --field-selector=status.phase!=Succeeded,status.phase!=Failed --no-headers | grep "^$pod_name_prefix" | awk '{print $1}' | head -n 1)
        local pod_status=""
        if [ ! -z "$pod_name" ]; then
            pod_status=$(kubectl get pod "$pod_name" -n "$namespace" -o jsonpath="{.status.phase}")
        fi

        # Check if the status is "Running"
        if [ "$pod_status" = "Running" ]; then
            is_pod_running=true
            echo "Pod $pod_name is running."
        else
            # Wait for a short period before checking again
            sleep 5
        fi
    done
	sleep 5
}

gnbsimim=$1
dnnim=$2

((user=$3+10))
((trafficusers=$3-1))
((slice=$4+9))
u=10

echo "-------------------------------------------------"
echo -e "${BLUE} ${bold} gNBSIM image set to $gnbsimim ${NC} ${NORMAL}"
echo -e "${BLUE} ${bold} DNN image is set to $dnnim ${NC} ${NORMAL}"
echo "-------------------------------------------------"

echo "-------------------------------------------------"
echo -e "${BLUE} ${bold} Deploying $4 slices with $3 users each ${NC} ${NORMAL}"
echo "-------------------------------------------------"

echo "-------------------------------------------------"
echo -e "${GREEN} ${bold} Starting 5G Core deployment ${NC} ${NORMAL}"
echo "-------------------------------------------------"


for ((s=10;s<=$slice;s++))
do

    #-----------------------START-----------------------
    #--------------------Proxy Config-------------------

    sed -i "/opmode/c\  opmode: $opmode" oai-nrf/values.yaml
    sed -i "/opmode/c\  opmode: $opmode" oai-udr/values.yaml
    sed -i "/opmode/c\  opmode: $opmode" oai-udm/values.yaml
    sed -i "/opmode/c\  opmode: $opmode" oai-ausf/values.yaml
    sed -i "/opmode/c\  opmode: $opmode" oai-amf/values.yaml
    sed -i "/opmode/c\  opmode: $opmode" oai-smf/values.yaml

    sed -i "/loglevel/c\  loglevel: $loglevel" oai-nrf/values.yaml
    sed -i "/loglevel/c\  loglevel: $loglevel" oai-udr/values.yaml
    sed -i "/loglevel/c\  loglevel: $loglevel" oai-udm/values.yaml
    sed -i "/loglevel/c\  loglevel: $loglevel" oai-ausf/values.yaml
    sed -i "/loglevel/c\  loglevel: $loglevel" oai-amf/values.yaml
    sed -i "/loglevel/c\  loglevel: $loglevel" oai-smf/values.yaml

    sed -i "/proxyport/c\  proxyport: $proxyport" oai-nrf/values.yaml
    sed -i "/proxyport/c\  proxyport: $proxyport" oai-udr/values.yaml
    sed -i "/proxyport/c\  proxyport: $proxyport" oai-udm/values.yaml
    sed -i "/proxyport/c\  proxyport: $proxyport" oai-ausf/values.yaml
    sed -i "/proxyport/c\  proxyport: $proxyport" oai-amf/values.yaml
    sed -i "/proxyport/c\  proxyport: $proxyport" oai-smf/values.yaml

    sed -i "/serviceport/c\  serviceport: $serviceport" oai-nrf/values.yaml
    sed -i "/serviceport/c\  serviceport: $serviceport" oai-udr/values.yaml
    sed -i "/serviceport/c\  serviceport: $serviceport" oai-udm/values.yaml
    sed -i "/serviceport/c\  serviceport: $serviceport" oai-ausf/values.yaml
    sed -i "/serviceport/c\  serviceport: $serviceport" oai-amf/values.yaml
    sed -i "/serviceport/c\  serviceport: $serviceport" oai-smf/values.yaml

    sed -i "/networksliceID/c\  networksliceID: $s" oai-nrf/values.yaml
    sed -i "/networksliceID/c\  networksliceID: $s" oai-udr/values.yaml
    sed -i "/networksliceID/c\  networksliceID: $s" oai-udm/values.yaml
    sed -i "/networksliceID/c\  networksliceID: $s" oai-ausf/values.yaml
    sed -i "/networksliceID/c\  networksliceID: $s" oai-amf/values.yaml
    sed -i "/networksliceID/c\  networksliceID: $s" oai-smf/values.yaml

    sed -i "/locationID/c\  locationID: $nrfloc" oai-nrf/values.yaml
    sed -i "/locationID/c\  locationID: $udrloc" oai-udr/values.yaml
    sed -i "/locationID/c\  locationID: $udmloc" oai-udm/values.yaml
    sed -i "/locationID/c\  locationID: $ausfloc" oai-ausf/values.yaml
    sed -i "/locationID/c\  locationID: $amfloc" oai-amf/values.yaml
    sed -i "/locationID/c\  locationID: $smfloc" oai-smf/values.yaml

    sed -i "/proxyversion/c\  proxyversion: $proxyversion" oai-nrf/values.yaml
    sed -i "/proxyversion/c\  proxyversion: $proxyversion" oai-udr/values.yaml
    sed -i "/proxyversion/c\  proxyversion: $proxyversion" oai-udm/values.yaml
    sed -i "/proxyversion/c\  proxyversion: $proxyversion" oai-ausf/values.yaml
    sed -i "/proxyversion/c\  proxyversion: $proxyversion" oai-amf/values.yaml
    sed -i "/proxyversion/c\  proxyversion: $proxyversion" oai-smf/values.yaml
    #--------------------Proxy Config-------------------
    #------------------------END------------------------


	((z=$s-9))
	((st=$s+1))

	#------------------------NRF-------------------------
	sed -i "22s/.*/name: oai-nrf$s/" oai-nrf/Chart.yaml
	sed -i "/saname/c\  saname: \"oai-nrf$s-sa\"" oai-nrf/values.yaml
	sed -i "/servicename/c\  servicename: \"nrf$st\"" oai-nrf/values.yaml
	sed -i "/deplocation/c\  deplocation: $nrfloc" oai-nrf/values.yaml
	
	helm install nrf$s oai-nrf/ -n oai
	wait_for_pod "oai" "oai-nrf"
	sleep 2
	echo -e "${GREEN} ${bold} NRF$s deployed ${NC} ${NORMAL}"

	#------------------------UDR-------------------------
	sed -i "23s/.*/name: oai-udr$s/" oai-udr/Chart.yaml
	sed -i "/nrfFqdn/c\  nrfFqdn: \"oai-nrf$s-svc\"" oai-udr/values.yaml
	sed -i "/saname/c\  saname: \"oai-udr$s-sa\"" oai-udr/values.yaml
	sed -i "/servicename/c\  servicename: \"udr$st\"" oai-udr/values.yaml
	sed -i "/deplocation/c\  deplocation: $udrloc" oai-udr/values.yaml
	
	helm install udr$s oai-udr/ -n oai
	wait_for_pod "oai" "oai-udr"
	sleep 2
	echo -e "${GREEN} ${bold} UDR$s deployed ${NC} ${NORMAL}"
	
	#------------------------UDM-------------------------
	sed -i "23s/.*/name: oai-udm$s/" oai-udm/Chart.yaml
	sed -i "/nrfFqdn/c\  nrfFqdn: \"oai-nrf$s-svc\"" oai-udm/values.yaml
	sed -i "/udrFqdn/c\  udrFqdn: \"oai-udr$s-svc\"" oai-udm/values.yaml
	sed -i "/saname/c\  saname: \"oai-udm$s-sa\"" oai-udm/values.yaml
	sed -i "/servicename/c\  servicename: \"udm$st\"" oai-udm/values.yaml
	sed -i "/deplocation/c\  deplocation: $udmloc" oai-udm/values.yaml

	helm install udm$s oai-udm/ -n oai
	wait_for_pod "oai" "oai-udm"
	sleep 2
	echo -e "${GREEN} ${bold} UDM$s deployed ${NC} ${NORMAL}"
	
	#------------------------AUSF------------------------
	sed -i "22s/.*/name: oai-ausf$s/" oai-ausf/Chart.yaml
	sed -i "/nrfFqdn/c\  nrfFqdn: \"oai-nrf$s-svc\"" oai-ausf/values.yaml
	sed -i "/udmFqdn/c\  udmFqdn: \"oai-udm$s-svc\"" oai-ausf/values.yaml
	sed -i "/saname/c\  saname: \"oai-ausf$s-sa\"" oai-ausf/values.yaml
	sed -i "/servicename/c\  servicename: \"ausf$st\"" oai-ausf/values.yaml
	sed -i "/deplocation/c\  deplocation: $ausfloc" oai-ausf/values.yaml


	helm install ausf$s oai-ausf/ -n oai
	wait_for_pod "oai" "oai-ausf"
	sleep 2
	echo -e "${GREEN} ${bold} AUSF$s deployed ${NC} ${NORMAL}"
	
	#------------------------AMF-------------------------
	sed -i "22s/.*/name: oai-amf$s/" oai-amf/Chart.yaml
	sed -i "/nrfFqdn/c\  nrfFqdn: \"oai-nrf$s-svc\"" oai-amf/values.yaml
	sed -i "/smfFqdn/c\  nrfFqdn: \"oai-smf$s-svc\"" oai-amf/values.yaml
	sed -i "/ausfFqdn/c\  ausfFqdn: \"oai-ausf$s-svc\"" oai-amf/values.yaml
	sed -i "/saname/c\  saname: \"oai-amf$s-sa\"" oai-amf/values.yaml
	sed -i "/sst0/c\  sst0: \"2$s\"" oai-amf/values.yaml
	sed -i "/servicename/c\  servicename: \"amf$st\"" oai-amf/values.yaml
	sed -i "/deplocation/c\  deplocation: $amfloc" oai-amf/values.yaml
	
	helm install amf$s oai-amf/ -n oai
	wait_for_pod "oai" "oai-amf"
	sleep 2
	echo -e "${GREEN} ${bold} AMF$s deployed ${NC} ${NORMAL}"
	amfpod=$(kubectl get pods -n oai  | grep amf$s | awk '{print $1}')
	amfeth0=$(kubectl exec -n oai $amfpod -c amf -- ifconfig | grep "inet 10.42" | awk '{print $2}')
	
	#------------------------SMF-------------------------
	sed -i "22s/.*/name: oai-smf$s/" oai-smf/Chart.yaml
	sed -i "/nrfFqdn/c\  nrfFqdn: \"oai-nrf$s-svc\"" oai-smf/values.yaml
	sed -i "/udmFqdn/c\  udmFqdn: \"oai-udm$s-svc\"" oai-smf/values.yaml
	sed -i "/amfFqdn/c\  amfFqdn: \"oai-amf$s-svc\"" oai-smf/values.yaml
	sed -i "/nssaiSst0/c\  nssaiSst0: \"2$s\"" oai-smf/values.yaml
	sed -i "/saname/c\  saname: \"oai-smf$s-sa\"" oai-smf/values.yaml
	sed -i "/servicename/c\  servicename: \"smf$st\"" oai-smf/values.yaml
	sed -i "/deplocation/c\  deplocation: $smfloc" oai-smf/values.yaml
	
	helm install smf$s oai-smf/ -n oai
	wait_for_pod "oai" "oai-smf"
	sleep 2
	echo -e "${GREEN} ${bold} SMF$s deployed ${NC} ${NORMAL}"
	
	#------------------------UPF-------------------------
	sed -i "22s/.*/name: oai-spgwu-tiny$s/" oai-spgwu-tiny/Chart.yaml
	sed -i "/nrfFqdn/c\  nrfFqdn: \"oai-nrf$s-svc\"" oai-spgwu-tiny/values.yaml
	sed -i "/fqdn/c\  fqdn: \"oai-spgwu-tiny$s-svc\"" oai-spgwu-tiny/values.yaml
	sed -i "/oai-spgwu-tiny-sa/c\  name: \"oai-spgwu-tiny$s-sa\"" oai-spgwu-tiny/values.yaml
	sed -i "24s/.*/  name: \"oai-spgwu-tiny$s\"/" oai-spgwu-tiny/values.yaml
	sed -i "/nssaiSst0/c\  nssaiSst0: \"2$s\"" oai-spgwu-tiny/values.yaml
	sed -i "/deplocation/c\  deplocation: $upfloc" oai-spgwu-tiny/values.yaml
	
	helm install upf$s oai-spgwu-tiny/ -n oai
	wait_for_pod "oai" "oai-spgwu"
	sleep 2
	echo -e "${GREEN} ${bold} UPF$s deployed ${NC} ${NORMAL}"
	upfpod=$(kubectl get pods -n oai  | grep spgwu-tiny$s | awk '{print $1}')
	upfeth0=$(kubectl exec -n oai $upfpod -c spgwu -- ifconfig | grep "inet 10.42" | awk '{print $2}')
	
	echo "-------------------------------------------------"
	echo -e "${GREEN} ${bold} Finished Core VNF deployment. Starting RAN. ${NC} ${NORMAL}"
	echo "-------------------------------------------------"

	ip=2
	for ((ut=0;ut<$3;ut++))
	do
		#-----------------------------GNBSIM Deployment----------------------------------------
		sed -i "2s/.*/name: gnbsim$u/" gnbsim/Chart.yaml
		sed -i "6s/.*/  version: ${gnbsimim}/" gnbsim/values.yaml
		sed -i "28s/.*/  name: \"gnbsim-sa$u\"/" gnbsim/values.yaml
		sed -i "/ngappeeraddr/c\  ngappeeraddr: \"$amfeth0\"" gnbsim/values.yaml
		sed -i "/gnbid/c\  gnbid: \"$u\"" gnbsim/values.yaml
		sed -i "/msin/c\  msin: \"00000000$u\"" gnbsim/values.yaml
		sed -i "/key/c\  key: \"0C0A34601D4F07677303652C046253$u\"" gnbsim/values.yaml
		sed -i "/sst/c\  sst: \"2$s\"" gnbsim/values.yaml
		sed -i "/deplocation/c\  deplocation: $gnbsimloc" gnbsim/values.yaml


		helm install gnb$u gnbsim/ -n oai 
		# 修正 1：精準等待 gnbsim Pod 就緒
        wait_for_pod "oai" "gnbsim$u"
		sleep 15
		echo -e "${BLUE} ${bold} GNBSIM$u deployed ${NC} ${NORMAL}"
		gnbsimpod=$(kubectl get pods -n oai  | grep gnbsim$u | awk '{print $1}')
		gnbsimeth0=$(kubectl exec -n oai $gnbsimpod -c gnbsim -- ifconfig | grep "inet 10.42" | awk '{print $2}')


		#-----------------------------DNN Deployment-------------------------------------------
		sed -i "4s/.*/  name: oai-dnn$u/" oai-dnn/02_deployment.yaml
		sed -i "6s/.*/    app: oai-dnn$u/" oai-dnn/02_deployment.yaml
		sed -i "11s/.*/      app: oai-dnn$u/" oai-dnn/02_deployment.yaml
		sed -i "17s/.*/        app: oai-dnn$u/" oai-dnn/02_deployment.yaml
		sed -i "28s/.*/        image: tolgaomeratalay\/oai-dnn:${dnnim}/" oai-dnn/02_deployment.yaml
		sed -i "22s/.*/        deplocation: $dnnloc/" oai-dnn/02_deployment.yaml

		kubectl apply -k oai-dnn/
		# 修正 2：精準等待 dnn Pod 就緒
        wait_for_pod "oai" "oai-dnn$u"
		sleep 5
		echo -e "${BLUE} ${bold} DNN$u deployed ${NC} ${NORMAL}"
		dnnpod=$(kubectl get pods -n oai  | grep oai-dnn$u | awk '{print $1}')
		dnneth0=$(kubectl exec -n oai $dnnpod -- ifconfig | grep "inet 10.42" | awk '{print $2}')

		# 修正 3：加入防呆，如果變數不幸還是抓空，強制暫停一下
        if [ -z "$upfeth0" ] || [ -z "$dnneth0" ]; then
            echo -e "\033[31m[Warning] UPF or DNN IP is empty, waiting 10s for networking...\033[0m"
            sleep 10
            # 重新獲取
            upfeth0=$(kubectl exec -n oai $upfpod -c spgwu -- ifconfig | grep "inet 10.42" | awk '{print $2}')
            dnneth0=$(kubectl exec -n oai $dnnpod -- ifconfig | grep "inet 10.42" | awk '{print $2}')
        fi
		
		kubectl exec -it -n oai $dnnpod -- iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
		echo -e "${BLUE} Route 1 ${NC} ${NORMAL}"
		kubectl exec -it -n oai $dnnpod -- ip route add 12.1.1.0/24 via $upfeth0 dev eth0 onlink
		echo -e "${BLUE} Route 2 ${NC} ${NORMAL}"
		kubectl exec -it -n oai $gnbsimpod -c gnbsim -- ip route replace $dnneth0 via 0.0.0.0 dev eth0 src 12.1.1.$ip
		echo -e "${BLUE} Route 3 ${NC} ${NORMAL}"

		
		((ip+=1))
		((u+=1))
		echo "-------------------------------------------------"
	done
done


echo "-------------------------------------------------"
echo -e "${GREEN} ${bold} Finished 5G Deployment ${NC} ${NORMAL}"
echo "-------------------------------------------------"

/bin/bash ./start_traffic.sh $3 $4 $dnnim $5 $6 $7 $8 $9
