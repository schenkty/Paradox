apt update -y
apt upgrade -y
apt install docker.io p7zip-full
docker run --network="host" --name=node --restart=unless-stopped -d -p 7075:7075/udp -p 7075:7075 -p 7076:7076 -v /root/Nano:/root/Nano nanocurrency/nano:V21.1
docker stop node
cd /root/Nano
rm data.ldb
rm data.ldb-lock
wget "https://mynano.ninja/api/ledger/download" -O ledger.7z
7z x ledger.7z 
rm ledger.7z
docker start node
