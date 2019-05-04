# Nano Data Recorder
# Ty Schenk 2019

# import required packages
from io import BytesIO
import json
import pycurl
import sys
from threading import Timer
import time
import datetime
import signal
import os.path
import argparse

parser = argparse.ArgumentParser(description="record all blocks on Nano network")
parser.add_argument('-nu', '--node_url', type=str, help='Nano node url', default='127.0.0.1')
parser.add_argument('-np', '--node_port', type=int, help='Nano node port', default=55000)
parser.add_argument('-s', '--save', type=int, help='Save blocks to disk how often (in seconds)', default=60)
parser.add_argument('-d', '--delay', type=int, help='recorder delay (in seconds)', default=0.01)
options = parser.parse_args()

SAVE_EVERY_N = options.save
# sleep for 0.01 seconds
RECORD_DELAY = options.delay

# add a circuit breaker variable
global signaled
signaled = False

# global save pause
savePause = False

# global dicts for upcoming data
blocks = {'times':{}}
data = {'hashes':{}}

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

class RepeatedTimer(object):
    def __init__(self, interval, function, *args, **kwargs):
        self._timer     = None
        self.interval   = interval
        self.function   = function
        self.args       = args
        self.kwargs     = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        self.is_running = False
        self.start()
        self.function(*self.args, **self.kwargs)

    def start(self):
        if not self.is_running:
            self._timer = Timer(self.interval, self._run)
            self._timer.start()
            self.is_running = True

    def stop(self):
        self._timer.cancel()
        self.is_running = False

def saveBlocks():
    global blocks
    global data
    global savePause

    savePause = True
    tempData = data
    tempBlocks = blocks
    savePause = False
    writeJson('data.json', tempData)
    writeJson('blockcounts.json', tempBlocks)
    # notify system when the data was last saved
    print ('saved data at: ' + time.strftime("%I:%M:%S"))

# execute recording responsibilities
def startRecording():
    global blocks
    global data
    global savePause

    # notify system that the recording has started
    print('Recorder started')

	# check if files exist and read them before starting
    if os.path.exists('data.json'):
        data = readJson('data.json')

    if os.path.exists('blockcounts.json'):
        blocks = readJson('blockcounts.json')

    # record blocks continuously
    while True:
        # get current time
        currentTime = time.time()
        confirmations = getConfirmations()['confirmations']
        newBlocks = getBlocks()

        # wait if save is trying to make a copy
        while savePause:
            print("waiting for save to copy: " + time.strftime("%I:%M:%S"))
            pass

        # insert new data into old data
        for item in confirmations:
            hash = item['hash']
            data['hashes'][hash] = item

        # create new dictionary to format block counts
        blocks['times'][currentTime] = {"time": currentTime, "checked": newBlocks['count'], "unchecked": newBlocks['unchecked']}
        print("recorded blocks. execution: %s seconds" % (time.time() - currentTime))

        time.sleep(RECORD_DELAY)

# write to disk for SAVE_EVERY_N
RepeatedTimer(SAVE_EVERY_N, saveBlocks)
# start data recorder
startRecording()
