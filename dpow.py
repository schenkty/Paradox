# Nano Stressor
# Ty Schenk 2019

# import required packages
from io import BytesIO
import json
import pycurl
import random
import argparse
import sys
import time
import signal
import os.path

parser = argparse.ArgumentParser(
    description="Stress test for NANO network. Sends 10 raw each to itself ")
parser.add_argument('-m', '--mode', help='define what mode you would like', choices=['receives', 'sends', 'all'])

options = parser.parse_args()

# global vars
accounts = {'accounts':{}}
blocks = {'accounts':{}}

# read json file and decode it
def readJson(filename):
    with open(filename) as f:
        return json.load(f)

# write json file and encode it
def writeJson(filename, data):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file)

# check if accounts.json exists and if so, read the file to the accounts variable
if os.path.exists('accounts.json'):
    accounts = readJson('accounts.json')

# check if blocks.json exists and if so, read the file to the blocks variable
if os.path.exists('blocks.json'):
    blocks = readJson('blocks.json')

def processReceiveBlocks():
    global keys
    global blocks

    # receive all blocks
    savedBlocks = list(blocks['accounts'].keys())

    i = 0
    for x in savedBlocks:
        i = (i + 1)

        # skip blocks that were already processed
        if blocks['accounts'][x]['receive']['processed'] == True:
            continue

        # process block
        blockObject = blocks['accounts'][x]
        receiveBlock = blockObject['receive']['block']

        # decode json string to dict
        receiveDecoded = json.loads(receiveBlock)

        # change work here
        # receiveDecoded['work'] = "" # 1111

        # encode block again
        receiveEncoded = json.dumps(receiveDecoded, ensure_ascii=False)

        # write encoded block back to block object
        blockObject['receive']['block'] = receiveEncoded

        # print out new work
        print("block {0}".format((i-1)))
        print("Work {0}".format(receiveDecoded['work']))

        # save updated block object to blocks dict
        blocks['accounts'][x] = blockObject

    # save all blocks after processing receives
    writeJson('blocks.json', blocks)

def processSendBlocks():
    global keys
    global blocks

    # receive all blocks
    savedBlocks = list(blocks['accounts'].keys())

    i = 0
    for x in savedBlocks:
        i = (i + 1)

        # skip blocks that were already processed
        if blocks['accounts'][x]['send']['processed'] == True:
            continue

        # process block
        blockObject = blocks['accounts'][x]
        sendBlock = blockObject['send']['block']

        # decode json string to dict
        sendDecoded = json.loads(sendBlock)

        # change work here
        # sendDecoded['work'] = "" # 1111

        # encode block again
        sendEncoded = json.dumps(sendDecoded, ensure_ascii=False)

        # write encoded block back to block object
        blockObject['send']['block'] = sendEncoded

        # print out new work
        print("block {0}".format((i-1)))
        print("Work {0}".format(sendDecoded['work']))

        # save updated block object to blocks dict
        blocks['accounts'][x] = blockObject

    # save all blocks after processing sends
    writeJson('blocks.json', blocks)

if options.mode == 'receive':
    processReceiveBlocks()
elif options.mode == 'send':
    processSendBlocks()
elif options.mode == 'all':
    processSendBlocks()
    processReceiveBlocks()

# save all blocks after processing
writeJson('blocks.json', blocks)
