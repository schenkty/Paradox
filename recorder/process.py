# Nano Data Processor
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
parser.add_argument('-e', '--export', help='print out export format', default=False)
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
data = {'hashes':{}}
newData = {'hashes':{}}
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

    if 'hashes' not in temp:
        sys.exit("Invalid data-info.json format")

	addInfo = True
	while addInfo:
        tempKeys = temp['hashes'].keys()
        if len(tempKeys) == 0:
			addInfo = False

		for object in tempKeys:
            hashData = temp['hashes'][object]

            data['hashes'][object] = hashData
            # remove from temp
            del temp['hashes'][object]

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
    dataKeys = data['hashes'].keys()
	if len(dataKeys) == 0:
		# save changes
		writeJson('data-info.json', newData)
		process = False

	for object in dataKeys:
        objectData = data['hashes'][object]
		known = False

		# notfiy user of pending data
		sys.stdout.write(time.strftime("%I:%M:%S") + " data left: %d%   \r" % (len(data)) )
		sys.stdout.flush()

		if not 'hash' in objectData:
            # remove from data
            del data['hashes'][object]
			continue

		hash = objectData['hash']

		if hash in blockArray:
			known = True

		if 'label' in objectData and objectData['label'] == "Unknown" and known == True:
			account = blockData[hash]
			objectData['label'] = options.label
			objectData['account'] = account

		if not 'label' in objectData and known == False:
			objectData['label'] = "Unknown"
			objectData['account'] = "xrb_other"

		if not 'label' in object and known == True:
			account = blockData[hash]
			objectData['label'] = options.label
			objectData['account'] = account

        # put object in newData
        newData['hashes'][object] = objectData

		# remove object from data
        del data['hashes'][object]

	# save changes
	writeJson('data-info.json', newData)

if options.export == "True":
    exportData = []
    processExport = True
    while processExport:
        dataKeys = newData['hashes'].keys()
    	if len(dataKeys) == 0:
    		# save changes
    		writeJson('data-info.export.json', exportData)
    		processExport = False
        for object in dataKeys:
            objectData = newData['hashes'][object]
            exportData.append(objectData)
    		# remove object from data
            del newData['hashes'][object]
	# save changes
    writeJson('data-info.export.json', newData)

# notify system that the processing has finished
print('Processing Complete')
