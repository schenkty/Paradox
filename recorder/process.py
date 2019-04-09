# Nano Node Recorder
# Ty Schenk 2019

# import required packages
from io import BytesIO
import json
import sys
import time
import signal
import os.path
import argparse

parser = argparse.ArgumentParser(description="Match blocks up with accounts")
parser.add_argument('-l', '--label', type=str, help='sender label', default='Unknown')
parser.add_argument('-sn', '--save_num', type=int, help='Save blocks to disk how often', default=10)
options = parser.parse_args()

SAVE_EVERY_N = options.save_num

# get account for hash
def getAccount(nanoHash):
	command = {'action': 'block_account', 'hash': nanoHash}
	return communicateNode(command)['account']

# read json file and decode it
def readJson(filename):
    with open(filename) as f:
        return json.load(f)

# write json file and encode it
def writeJson(filename, data):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file)

# notify system that the recording has started
print('Processing started')

# create empty array for upcoming data
data = []
newData = []
accounts = []
blockData = {}
process = True

# check if files exist and read them before starting
if os.path.exists('data.json'):
	data = readJson('data.json')

# check if files exist and read them before starting
if os.path.exists('blocks.json'):
    temp = {'accounts':{}}
    temp = readJson('blocks.json')
    accounts = list(temp['accounts'])
    for account in accounts:
        send = temp['accounts'][account]['send']['hash']
        receive = temp['accounts'][account]['receive']['hash']
        blockData[send] = account
        blockData[receive] = account

while process:
    if len(data) == 0:
        # save changes
        writeJson('data-info.json', newData)
        process = False

    i = 0
    for object in data:
        i = (i + 1)
    	# notfiy user of pending data
        print ('data left: ' + str(len(data)) + ' at: ' + time.strftime("%I:%M:%S"))

        if not 'hash' in object:
            data.remove(object)
            continue

        hash = object['hash']
        blockArray = list(blockData)

        if hash in blockArray:
            account = blockData[hash]
            # create new dictionary
            newBlockDict = {"label": options.label, "hash": hash, "account": account, "duration": object['duration'], "time": object['time'], "tally": object['tally']}
        else:
            # create new dictionary
            newBlockDict = {"label": "Unknown", "hash": hash, "account": 'xrb_other', "duration": object['duration'], "time": object['time'], "tally": object['tally']}

    	# add new dictionary to newData array
        newData.append(newBlockDict)

        # remove object from array
        data.remove(object)

        if i%SAVE_EVERY_N == 0:
            # notify system when the data was last saved
            print ('saved data at: ' + time.strftime("%I:%M:%S"))
            # save changes
            writeJson('data-info.json', newData)
    # save changes
    writeJson('data-info.json', newData)
