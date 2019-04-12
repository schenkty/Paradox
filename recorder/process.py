# Nano Recorder
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
options = parser.parse_args()

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

# global vars
data = []
newData = []
accounts = []
blockData = {}
blockArray = list(blockData)
process = True

# check if files exist and read them before starting
if os.path.exists('data.json'):
	data = readJson('data.json')

if os.path.exists('data-info.json'):
	print("Importing Existing Blocks")
	temp = readJson('data-info.json')
	addInfo = True
	while addInfo:
		if len(temp) == 0:
			addInfo = False
		for object in temp:
			data.append(object)
			temp.remove(object)
	print("Importing Complete")

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
	# update blockArray
    blockArray = list(blockData)

while process:
	if len(data) == 0:
		# save changes
		writeJson('data-info.json', newData)
		process = False

	for object in data:
		known = False

		# notfiy user of pending data
		sys.stdout.write(time.strftime("%I:%M:%S") + " data left: %d%   \r" % (len(data)) )
		sys.stdout.flush()

		if not 'hash' in object:
			data.remove(object)
			continue

		hash = object['hash']

		if hash in blockArray:
			known = True

		if 'label' in object and object['label'] == "Unknown" and known == True:
			account = blockData[hash]
			object['label'] = options.label
			object['account'] = account

		if not 'label' in object and known == False:
			object['label'] = "Unknown"
			object['account'] = "xrb_other"

		if not 'label' in object and known == True:
			account = blockData[hash]
			object['label'] = options.label
			object['account'] = account

		if not object in newData:
			# add new dictionary to newData array
			newData.append(object)

		# remove object from data
		data.remove(object)

	# save changes
	writeJson('data-info.json', newData)

# notify system that the processing has finished
print('Processing Complete')
