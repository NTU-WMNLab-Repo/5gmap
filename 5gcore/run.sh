# run.sh
#!/bin/bash

#---------------------------------------------------------------
#---------------------------------------------------------------
GREEN='\x1b[32m'
BLUE='\x1b[34m'
RED='\x1B[31m'
NC='\033[0m'

bold=$(tput bold)
NORMAL=$(tput sgr0)

#---------------------------------------------------------------
#---------------------------------------------------------------


                        #gnbsimim   dnnim   users   slices iterationstest thrtesttype(1==hostlvl, 0==podlvl)     iperf_client_host        iperf_server_ip       log_server_ip
/bin/bash ./deploy.sh   zoomv3      zoomv3    1       1           1                     0                          10.0.12.155               10.0.1.126           10.0.1.71

#For now, the number of users, slices and iterationstest is set 1 and the remainder of the use cases is commented out. The user can adjust these values according to their need

#/bin/bash ./deploy.sh netflixv3 netflixv3 10 8 20 1
#/bin/bash ./deploy.sh oculusv3 oculusv3 10 8 20 1
#/bin/bash ./deploy.sh tiktokv3 tiktokv3 10 8 20 1
#/bin/bash ./deploy.sh whatsappv3 whatsappv3 10 8 20 1
#/bin/bash ./deploy.sh fortnitev3 fortnitev3 10 8 20 1

echo "-------------------------------------------------"
echo "Experiment Finished for All Use Cases"
echo "-------------------------------------------------"
