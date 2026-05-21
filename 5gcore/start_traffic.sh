#!/bin/bash

#---------------------------------------------------------------
# Color Codes for Logging
#---------------------------------------------------------------
GREEN='\x1b[32m'
BLUE='\x1b[34m'
RED='\x1B[31m'
NC='\033[0m'

bold=$(tput bold)
NORMAL=$(tput sgr0)

iperf_client_host=$7
iperf_server_ip=$8
log_server_ip=$9

#---------------------------------------------------------------
# Functions for TCP and UDP Throughput Measurement
#---------------------------------------------------------------
measthrTCP () {
    ssh -i ~/.ssh/awscluster.pem ubuntu@$iperf_client_host /bin/bash << EOF
    iperf3 -c $iperf_server_ip -t 70 > iperf.log
    tail -3 iperf.log | head -1 > avg.log
    scp -i ~/.ssh/awscluster.pem avg.log ubuntu@$log_server_ip:/home/ubuntu/oai5gtrafficgen/logs/$usecase/throughput/iperf.log
EOF
}

measplUDP () {
    ssh -i ~/.ssh/awscluster.pem ubuntu@$iperf_client_host /bin/bash << EOF
    iperf3 -c $iperf_server_ip -u -b 1G -t 70 > iperf.log
    tail -3 iperf.log | head -1 > avg.log
    scp -i ~/.ssh/awscluster.pem avg.log ubuntu@$log_server_ip:/home/ubuntu/oai5gtrafficgen/logs/$usecase/throughput/iperf.log
EOF
}

#---------------------------------------------------------------
# Start Traffic Generation
#---------------------------------------------------------------
echo "-------------------------------------------------"
echo -e "${GREEN} ${bold} Starting DL/UL Traffic ${NC} ${NORMAL}"
echo "-------------------------------------------------"

usecase=$3
((total=$1*$2)) # total = users * slices

iperfpodnumber=10
runs=1
tc=0
gip=1

# Create directories for logs
rm -r logs/$usecase/compute/ 2>/dev/null
mkdir -p logs/$usecase/compute
rm -r logs/$usecase/throughput/ 2>/dev/null
mkdir -p logs/$usecase/throughput

iperfdnnpod=$(kubectl get pods -n oai | grep oai-dnn$iperfpodnumber | awk '{print $1}')
iperfgnbsimpod=$(kubectl get pods -n oai | grep gnbsim$iperfpodnumber | awk '{print $1}')
upfpod=$(kubectl get pods -n oai | grep spgwu-tiny10 | awk '{print $1}')
kubectl exec -n oai -c gnbsim $iperfgnbsimpod -- iperf3 -s &

#---------------------------------------------------------------
# Loop through users and slices
#---------------------------------------------------------------
for ((sim=0;sim<$1;sim++)) # Loop through users
do
    ((gip+=1))
    for ((n=0;n<$2;n++)) # Loop through slices
    do
        ((add=$n*$1))
        ((t=$add+$sim+10))
        ((tc+=1)) # Unique counter for each user-slice pair

        avglogsthr=logs/$usecase/throughput/throughput.avg$tc.log.txt
        avglogslat=logs/$usecase/throughput/lat.avg$tc.log.txt

        dnnpod=$(kubectl get pods -n oai | grep oai-dnn$t | awk '{print $1}')
        dnneth0=$(kubectl exec -n oai $dnnpod -- ifconfig | grep "inet 10.42" | awk '{print $2}')
        gnbsimpod=$(kubectl get pods -n oai | grep gnbsim$t | awk '{print $1}')

        echo -e "${BLUE} ${bold} Starting DL/UL for $dnnpod and $gnbsimpod ${NC} ${NORMAL}"

        #------------Downlink traffic----------------
        echo -e "${BLUE} ${bold} Starting DL on 12.1.1.$gip ${NC} ${NORMAL}"
        kubectl exec -n oai $gnbsimpod -c gnbsim -- python3 udpserverclient/server.py 12.1.1.$gip 20001 &
        sleep 1
        kubectl exec -n oai $dnnpod -- python3 udpserverclient/client.py 12.1.1.$gip 20001 1 DL &
        sleep 1
        echo -e "${BLUE} ${bold} DL traffic started ${NC} ${NORMAL}"

        #------------Uplink traffic------------------
        echo -e "${BLUE} ${bold} Starting UL on $dnneth0 ${NC} ${NORMAL}"
        kubectl exec -n oai $dnnpod -- python3 udpserverclient/server.py $dnneth0 20002 &
        sleep 1
        kubectl exec -n oai $gnbsimpod -c gnbsim -- python3 udpserverclient/client.py $dnneth0 20002 1 UL &
        sleep 1
        echo -e "${BLUE} ${bold} UL traffic started ${NC} ${NORMAL}"
        echo "-------------------------------------------------"
    done

    #---------------------------------------------------------------
    # testtype=1 (Host-Level)
    #---------------------------------------------------------------
    if [ $5 -eq 1 ]; then
        if [ $sim -eq 4 ] || [ $sim = 9 ]; then
            for ((ite=0;ite<$4;ite++))
            do
                log=logs/$usecase/throughput/iperf.log
                rm -f $log
                measthrTCP
                value=$(cat logs/$usecase/throughput/iperf.log)
                echo $value | awk '{print $7}' >> logs/$usecase/throughput/throughput.TCP$tc.log.txt
                sleep 5
            done

            for ((ite=0;ite<$4;ite++))
            do
                log=logs/$usecase/throughput/iperf.log
                rm -f $log
                measplUDP
                value=$(cat logs/$usecase/throughput/iperf.log)
                echo $value | awk '{print $12}' | sed 's/[^0-9.]//g' >> logs/$usecase/throughput/pl.UDP$tc.log.txt			 
                sleep 5
            done

            log=logs/$usecase/throughput/lat.log
            rm -f $log
            kubectl exec -n oai $iperfdnnpod -- ping -c 40 12.1.1.2 | awk -F '[:=]'  'NR!=1 {print $5}' >> $log
            avg=$(cat $log | sed 's/[^.0-9][^.0-9]*/ /g')
            echo $avg >> logs/$usecase/throughput/lat.avg$tc.log.txt
            sleep 3
        fi

    #---------------------------------------------------------------
    # testtype=0 (Pod-Level)
    #---------------------------------------------------------------
    else
        for ((ite=0;ite<$4;ite++))
        do
            log=logs/$usecase/throughput/iperf_tcp.log
            rm -f $log

            for run in $(seq 1 $runs); do
                kubectl exec -n oai $iperfdnnpod -- iperf3 -c 12.1.1.2 -t 100 | awk '/[0-9]]/{sub(/.*]/,""); print $1" "$5}'  >> $log
            done

            avg_tcp=$(cat $log | awk 'END{print $2}')
            echo $avg_tcp >> logs/$usecase/throughput/throughput.avg$tc.log.txt
            sleep 5
        done

        for ((ite=0;ite<$4;ite++))
        do
            log=logs/$usecase/throughput/iperf_udp.log
            rm -f $log

            for run in $(seq 1 $runs); do
                kubectl exec -n oai $iperfdnnpod -- iperf3 -c 12.1.1.2 -u -b 1G -t 70 | awk '/[0-9]]/{sub(/.*]/,""); print $1" "$12}' >> $log
            done

            avg_udp=$(cat $log | awk 'END{print $2}' | sed 's/[^0-9.]//g')
            echo $avg_udp >> logs/$usecase/throughput/pl.UDP$tc.log.txt
            sleep 5
        done
    fi
done

echo -e "${GREEN} ${bold} Traffic generation complete. Undeploying users. ${NC} ${NORMAL}"
read -p "Press enter to cleanup"
/bin/bash ./undeploy.sh $total
sleep 200
