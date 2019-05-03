# Nano Data Recorder
# Ty Schenk 2019

# import required packages
from io import BytesIO
import json
import pycurl
import sys
import time
import datetime
import signal
import os.path
import argparse

parser = argparse.ArgumentParser(description="record all blocks on Nano network")
parser.add_argument('-nu', '--node_url', type=str, help='Nano node url', default='127.0.0.1')
parser.add_argument('-np', '--node_port', type=int, help='Nano node port', default=55000)
parser.add_argument('-sn', '--save_num', type=int, help='Save blocks to disk how often', default=60)
options = parser.parse_args()
SAVE_EVERY_N = options.save_num

# add a circuit breaker variable
global signaled
signaled = False
lastSave = datetime.datetime.now()

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
	global lastSave
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
		start_time = time.time()
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
		currentTime = datetime.datetime.now()
		timeDiff = currentTime - lastSave
		if SAVE_EVERY_N <= timeDiff.seconds:
			writeJson('data.json', data)
			writeJson('blockcounts.json', blocks)
			lastSave = currentTime
			# notify system when the data was last saved
			print ('saved data at: ' + time.strftime("%I:%M:%S"))

		print("Recorded Blocks. Execution time: %s seconds" % (time.time() - start_time))
		# sleep for 0.01 seconds
		time.sleep(0.01)

start()
