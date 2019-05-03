# Nano Data Recorder
# Ty Schenk 2019

# import required packages
from io import BytesIO
import json
import pycurl
import sys
import time
import signal
import os.path
import argparse

parser = argparse.ArgumentParser(description="record all blocks on Nano network")
parser.add_argument('-nu', '--node_url', type=str, help='Nano node url', default='127.0.0.1')
parser.add_argument('-np', '--node_port', type=int, help='Nano node port', default=55000)
options = parser.parse_args()

# add a circuit breaker variable
global signaled
signaled = False

def communicateNode(rpc_command):
    buffer = BytesIO()
    c = pycurl.Curl()
    c.setopt(c.URL, options.node_url)
    c.setopt(c.PORT, options.node_port)
    c.setopt(c.POSTFIELDS, json.dumps(rpc_command))
    c.setopt(c.WRITEFUNCTION, buffer.write)
    c.setopt(c.TIMEOUT, 500)

    #add a retry mechanism in case of CURL errors
    ok = False
    while not ok:
        try:
            c.perform()
            ok = True
        except pycurl.error as error:
            print('Communication with node failed with error: {}', error)
            time.sleep(2)
            global signaled
            if signaled: sys.exit(2)

    body = buffer.getvalue()
    parsed_json = json.loads(body.decode('iso-8859-1'))
    return parsed_json

# generate rpc commands
def buildPost(command):
    return {'action': command}

# pull confirmation history from nano node
def getConfirmations():
    return communicateNode(buildPost('confirmation_history'))

# pull block counts from nano node
def getBlocks():
	return communicateNode(buildPost('block_count'))

# read json file and decode it
def readJson(filename):
    with open(filename) as f:
        return json.load(f)

# write json file and encode it
def writeJson(filename, data):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file)

# execute recording responsibilities
def start():
	# notify system that the recording has started
	print('Recorder started')

	# create empty arrays for upcoming data
	blocks = {'times':{}}
	data = {'hashes':{}}

	# check if files exist and read them before starting
	if os.path.exists('data.json'):
		data = readJson('data.json')

	if os.path.exists('blockcounts.json'):
		blocks = readJson('blockcounts.json')

	# record blocks continuously
	while True:
		confirmations = getConfirmations()['confirmations']
		newBlocks = getBlocks()

		# insert new data into old data
		for item in confirmations:
			hash = item['hash']
			data['hashes'][hash] = item

		# get current time
		currentTime = time.time()

		# create new dictionary to format block counts
		blocks['times'][currentTime] = {"time": currentTime, "checked": newBlocks['count'], "unchecked": newBlocks['unchecked']}

		# save changes
		writeJson('data.json', data)
		writeJson('blockcounts.json', blocks)

		# notify system when the data was last saved
		print ('saved data at: ' + time.strftime("%I:%M:%S"))

		# sleep for 0.1 seconds
		time.sleep(0.1)

start()
