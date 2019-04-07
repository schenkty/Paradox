# Nano Node Recorder
# Ty Schenk 2018

# import required packages
from io import BytesIO
import json
import pycurl
import sys
import time
import signal
import os.path

# add a circuit breaker variable
global signaled
signaled = False

def communicateNode(rpc_command):
    buffer = BytesIO()
    c = pycurl.Curl()
    c.setopt(c.URL, '0.0.0.0')
    c.setopt(c.PORT, 7076)
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
        
# pull confirmation history from nano node
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

# execute processing responsibilities
def start():
	# notify system that the recording has started
	print('Processing started')

	# create empty array for upcoming data
	data = []
	newData = []
	process = True
	
	# check if files exist and read them before starting
	if os.path.exists('data.json'):
		data = readJson('data.json')

	# create new dictionary to format block counts
	while process:
		# set count to zero
		count = 0

		# count items in array
		for item in data:
			count += 1

		# check if count is equal to zero
		if count == 0:
			process = False
			break
		
		# notfiy user of pending data 
		print ('data left to process: ' + str(count) + ' at: ' + time.strftime("%I:%M:%S"))

		# create new dictionary
		newBlockDict = {"hash": item['hash'], "account": getAccount(item['hash']), "duration": item['duration'], "time": item['time'], "tally": item['tally']}
		
		# add new dictionary to newData array
		newData.append(newBlockDict)

		# remote item from old data array
		data.remove(item)

	# save changes
	writeJson('data-accounts.json', newData)

	# notify system when the data was last saved
	print ('saved data at: ' + time.strftime("%I:%M:%S"))

start()