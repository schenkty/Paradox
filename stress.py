# Nano Stressor
# Ty Schenk 2019

# import required packages
from io import BytesIO
import json
import csv
import pycurl
from threading import Timer
from threading import Thread
import random
import argparse
import sys
import time
import signal
import os.path
from collections import defaultdict

parser = argparse.ArgumentParser(
    description="Stress test for NANO network. Sends 10 raw each to itself ")
parser.add_argument('-n', '--num-accounts', type=int, help='Number of accounts', required=True)
parser.add_argument('-s', '--size', type=int, help='Size of each transaction in Nano raw', default=10)
parser.add_argument('-sn', '--save_num', type=int, help='Save blocks to disk how often', default=1000)
parser.add_argument('-r', '--representative', type=str, help='Representative to use', default='nano_1brainb3zz81wmhxndsbrjb94hx3fhr1fyydmg6iresyk76f3k7y7jiazoji')
parser.add_argument('-tps', '--tps', type=int, help='Throttle transactions per second during processing. 0 (default) will not throttle.', default=0)
parser.add_argument('-slam', '--slam', type=bool, help='Variable throttle transactions per second during processing. false (default) will not vary.', default=False)
parser.add_argument('-stime', '--slam_time', type=int, help='Define how often slam is decided', default=20)
parser.add_argument('-m', '--mode', help='define what mode you would like', choices=['buildAccounts', 'seedAccounts', 'buildAll', 'buildSend', 'buildReceive', 'processSend', 'processReceive', 'processAll', 'autoOnce', 'countAccounts', 'recover'])
parser.add_argument('-nu', '--node_url', type=str, help='Nano node url', default='[::1]')
parser.add_argument('-np', '--node_port', type=int, help='Nano node port', default=55000)
parser.add_argument('-z', '--zero_work', type=str, help='Submits empty work', default='False')
parser.add_argument('-ss', '--save_seed', type=str, help='Save to file during initial seeding', default='False')
parser.add_argument('-dw', '--disable_watch_work', type=str, help='Disable watch_work feature for RPC process (v20 needed)', default='False')

options = parser.parse_args()

SAVE_EVERY_N = options.save_num

# add a circuit breaker variable
global signaled
signaled = False

# global vars
accounts = {'accounts':{}}
blocks = {'accounts':{}}

# keep track of number of built and processed blocks
buildReceiveCount = 0
buildSendCount = 0
processSendCount = 0
processReceiveCount = 0

# tps counters
throttle_tps = options.tps
highest_tps = 0
current_tps = 0
average_tps = 0
start = 0
start_process = 0

# custom
threadDelay = 1 # delay after doing multithreading receive or send to wait for processes to finnish

# read json file and decode it
def readJson(filename):
    with open(filename) as f:
        return json.load(f)

# write json file and encode it
def writeJson(filename, data):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file)

def chunkBlocks(seq, num):
    avg = len(seq) / float(num)
    out = []
    last = 0.0

    while last < len(seq):
        out.append(seq[int(last):int(last + avg)])
        last += avg

    return out

def slamScaler():
	if not options.slam:
		throttle_tps = options.tps
		return
	if options.tps == 0:
		throttle_tps = 0
		return
	scales = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
	slamScale = random.choice(scales)
	throttle_tps = options.tps + (100 * slamScale)
	newSlam = ("New Slam: {0}").format(throttle_tps)
	print(newSlam)

# allow multidimentional dictionaries. Initialize: newDict = nestedDict(2, float)
def nestedDict(n, type):
    if n == 1:
        return defaultdict(type)
    else:
        return defaultdict(lambda: nestedDict(n-1, type))

# collect failed blocks
failedBlocks = nestedDict(2, str)

class SlamTimer(object):
    def __init__(self, interval, function, *args, **kwargs):
        self._timer     = None
        self.interval   = interval
        self.function   = function
        self.args       = args
        self.kwargs     = kwargs
        self.is_running = False
        self.start()

    def _run(self):
        if not options.slam:
            self.stop()
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

# variable tps slam every options.slam_time seconds
slamThread = SlamTimer(options.slam_time, slamScaler)

if os.path.exists('accounts.json'):
    accounts = readJson('accounts.json')

if os.path.exists('blocks.json'):
    blocks = readJson('blocks.json')

def printTPS():
    # print tps results
    results = ("Average transactions per second: {0}\n" +
           "Most transactions in 1 second: {1}").format(average_tps, highest_tps)
    print(results)

def findKey(account):
    return accounts['accounts'][account]['key']

def tpsCalc():
    global highest_tps
    global current_tps
    global average_tps
    global start
    global start_process
    # calculate average_tps
    average_tps = average_tps / (time.perf_counter() - start_process)

    # print tps results
    printTPS()

def tpsDelay():
    global highest_tps
    global current_tps
    global average_tps
    global start
    global start_process
    # delay next process if --tps is not 0, to throttle outgoing
    if throttle_tps != 0:
        while average_tps / (time.perf_counter() - start_process) > throttle_tps:
            time.sleep(0.001)

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

# standard function to save blocks and print
def saveBlocks():
    writeJson('blocks.json', blocks)
    print('\n(SAVE) Blocks have been written to blocks.json\n')

# standard function to save failed blocks and print
def saveFailedBlocks():
    writeJson('failedBlocks.json', failedBlocks)
    print('(SAVE) Failed blocks have been written to failedBlocks.json\n')

# standard function to save accounts and print
def saveAccounts():
    writeJson('accounts.json', accounts)
    print('\n(SAVE) Accounts have been written to accounts.json\n')

# generate new key pair
def getKeyPair():
    return communicateNode({'action': 'key_create'})

# republish block to the nano network
def republish(hash):
    return communicateNode({'action': 'republish', 'hash': hash})

def getPending(account):
    return communicateNode({'action':'pending', 'account': account, 'count': '10'})

def getHistory(account):
    return communicateNode({'action':'account_history', 'account': account, 'count': '10', 'reverse': True})

def process(block):
    if 'block' in block:
        block = block['block']
    if options.disable_watch_work == 'true':
        return communicateNode({'action': 'process', 'block': block, 'watch_work': 'false'})
    else:
        return communicateNode({'action': 'process', 'block': block})

def getInfo(account):
    return communicateNode({'action': 'account_info', 'account': account, 'count': 1, 'pending': 'true' })

def getBlockInfo(hash):
    return communicateNode({'action': 'block_info', 'hash': hash})

# validate if an address is the correct format
def validate_address(address):
    # Check if the withdraw address is valid
    validate_command = {'action': 'validate_account_number', 'account': address}
    address_validation = communicateNode(validate_command)

    # If the address did not start with xrb_ or nano_ or was deemed invalid by the node, return an error.
    address_prefix_valid = address[:4] == 'xrb_' or address[:5] == 'nano_'
    if not address_prefix_valid or address_validation['valid'] != '1':
        return False

    return True

def generateBlock(key, account, balance, previous, link):
    create_block = {'action': 'block_create', 'type': 'state', 'account': account,
                    'link': link, 'balance': balance, 'representative': options.representative,
                    'previous': previous, 'key': key}

    if options.zero_work == 'true':
        create_block = {'action': 'block_create', 'type': 'state', 'account': account,
                        'link': link, 'balance': balance, 'representative': options.representative,
                        'previous': previous, 'key': key, 'work': '1111111111111111'}
    # Create block
    block_out = communicateNode(create_block)
    return block_out

def receive(key, account, prev):
    blockInfo = getBlockInfo(prev)
    amount = blockInfo['amount']
    newBalance = 0
    previous = prev

    info_out = getInfo(account)
    if 'frontier' in info_out:
        previous = info_out["frontier"]
        balance = getInfo(account)['balance']
        newBalance = str(int(balance) + int(amount))
    else:
        newBalance = amount
        previous = '0'

    block = generateBlock(key, account, newBalance, previous, prev)
    return process(block)

def receiveAllPending(key):
    keyExpand = communicateNode({'action':'key_expand', 'key':key})
    account = keyExpand['account']
    blocks = getPending(account)['blocks']

    for block in blocks:
        print(receive(key, account, block))

def buildAccounts():
    global accounts
    keyNum = options.num_accounts + 1

    currentCount = len((list(accounts['accounts'])))
    keyNum = (keyNum - currentCount)

    i = 0
    for x in range(keyNum):
        i = (i + 1)
        newKey = getKeyPair()
        accountObject = {'key': newKey['private'], 'seeded': False}
        accounts['accounts'][newKey['account']] = accountObject

    writeJson('accounts.json', accounts)
    print("Fund Account {0}".format(list(accounts['accounts'])[0]))

def getAccounts():
    global accounts
    keyNum = options.num_accounts + 1

    currentCount = len((list(accounts['accounts'])))
    print("Accounts {0}".format(currentCount))

def seedAccounts():
    global accounts
    global blocks
    prev = None
    rpcTimings = {}

    # pull first account/key pair object from keys array
    accountList = list(accounts['accounts'])
    firstAccount = accountList[0]
    firstObject = accounts['accounts'][firstAccount]
    mainKey = firstObject['key']

    # amount of raw in each txn
    testSize = options.size

    # pull info for our account
    receiveAllPending(mainKey)
    info_out = getInfo(accountList[0])

    # set previous block
    if 'frontier' in info_out:
        prev = info_out["frontier"]
    else:
        print("Account Not Found. Please Check that account funds are pending")
        return

    # seed all accounts with test raw
    i = 0
    for destAccount in accountList:
        i = (i + 1)
        if i == 1:
            continue

        seeded = accounts['accounts'][destAccount]['seeded']
        if seeded == True:
            print("Account has already been seeded. Skipping...")
            continue

        # calculate the state block balance
        adjustedbal = str(int(info_out['balance']) - options.size * (i - 1))

        # build receive block
        blockTimeStart = time.perf_counter() # measure the time taken for RPC call
        block_out = generateBlock(mainKey, firstAccount, adjustedbal, prev, destAccount)
        blockTime = time.perf_counter() - blockTimeStart

        processTimeStart = time.perf_counter() # measure the time taken for RPC call
        hash = process(block_out)["hash"]
        processTime = time.perf_counter() - processTimeStart

        blockObject = {'send': {'hash': hash}}
        blocks['accounts'][destAccount] = blockObject

        # save block as previous
        prev = block_out["hash"]

        rpcTimings[str(i-1)] = {'block_create_time':blockTime, 'process_time':processTime}

        # set seeded to true for destAccount
        accounts['accounts'][destAccount]['seeded'] = True

        print("Building Send Block {0}".format((i-1)))
        print("\nCreated block {0}".format(hash))

        if options.save_seed == 'true':
            if i%SAVE_EVERY_N == 0:
                saveBlocks()
                saveAccounts()

    writeJson('blocks.json', blocks)
    writeJson('accounts.json', accounts)
    writeJson('seedRPCTimings.json', rpcTimings)

def buildReceiveBlocks():
    global accounts
    global blocks
    global buildReceiveCount

    buildReceiveCount = 0

    keyNum = options.num_accounts + 1
    accountList = list(accounts['accounts'])
    # receive all accounts with test raw
    i = 0

    # we may only want a subset of accounts
    accountList = accountList[0:keyNum]

    for account in accountList:
        i = (i + 1)
        if i == 1:
            continue

        # set key
        key = accounts['accounts'][account]['key']
        # pull blockObject
        blockObject = blocks['accounts'][account]
        previous = '0'
        prev = ''
        newBalance = options.size

        if 'send' in blockObject:
            # skip blocks that were already built
            if 'processed' in blockObject["send"]:
                if blockObject["send"]['processed'] == False:
                    print("Already built receive")
                    continue

            prev = blockObject["send"]["hash"]

            if 'block' in blockObject["send"]:
                sendBal = json.loads(blockObject["send"]["block"])
                newBalance = str(int(sendBal["balance"]) + options.size)

        if 'receive' in blockObject:
            # skip blocks that were already built
            if 'processed' in blockObject["receive"]:
                if blockObject["receive"]['processed'] == False:
                    print("Already built receive")
                    continue

            previous = prev

        # build receive block
        block_out = generateBlock(key, account, newBalance, previous, prev)
        hash = block_out['hash']
        block = block_out["block"]
        receiveObject = {"hash":hash, "block":block, "processed":False}
        blockObject['receive'] = receiveObject
        blocks['accounts'][account] = blockObject
        print("Building Receive Block {0}".format((i-1)))
        print("\nCreated block {0}".format(block_out['hash']))
        buildReceiveCount += 1

        if i%SAVE_EVERY_N == 0:
            saveBlocks()
    writeJson('blocks.json', blocks)

def buildSendBlocks():
    global accounts
    global blocks
    global buildSendCount

    buildSendCount = 0

    keyNum = options.num_accounts + 1
    accountList = list(accounts['accounts'])
    # send all accounts with test raw
    i = 0

    # we may only want a subset of accounts
    accountList = accountList[0:keyNum]

    for account in accountList:
        i = (i + 1)
        if i == 1:
            continue

        # set key
        key = accounts['accounts'][account]['key']
        previous = '0'
        blockObject = blocks['accounts'][account]
        newBalance = 0

        if 'receive' in blockObject:
            # skip receive blocks that has not been built yet
            if 'processed' in blockObject["receive"]:
                if blockObject["receive"]['processed'] == True:
                    print("Receive not built yet")
                    continue

            previous = blockObject['receive']["hash"]
            receiveBal = json.loads(blockObject["receive"]["block"])
            newBalance = str(int(receiveBal["balance"]) - options.size)

        # skip building if already built
        if 'send' in blockObject:
            if 'processed' in blockObject["send"]:
                if blockObject["send"]['processed'] == False:
                    print("Already built send")
                    continue

        # build send block
        block_out = generateBlock(key, account, newBalance, previous, account)
        hash = block_out['hash']
        block = block_out["block"]
        sendObject = {"hash":hash, "block":block, "processed":False}
        blockObject['send'] = sendObject
        blocks['accounts'][account] = blockObject
        print("Building Send Block {0}".format((i-1)))
        print("\nCreated block {0}".format(block_out['hash']))
        buildSendCount += 1

        if i%SAVE_EVERY_N == 0:
            saveBlocks()
    writeJson('blocks.json', blocks)

def processReceiveBlocks(all = False, blockSection = 0):
    global keys
    global blocks

    # using global counters instead of local for processAll function
    global highest_tps
    global current_tps
    global average_tps
    global start
    global start_process
    global processReceiveCount
    global failedBlocks

    start = time.perf_counter()
    start_process = time.perf_counter()

    # receive all blocks
    savedBlocks = list(blocks['accounts'].keys())

    keyNum = options.num_accounts + 1
    # we may only want a subset of accounts
    savedBlocks = savedBlocks[0:keyNum]

    if blockSection != 0:
        if blockSection == 1:
            savedBlocks = chunkBlocks(savedBlocks, 4)[0]
        elif blockSection == 2:
            savedBlocks = chunkBlocks(savedBlocks, 4)[1]
        elif blockSection == 3:
            savedBlocks = chunkBlocks(savedBlocks, 4)[2]
        elif blockSection == 4:
            savedBlocks = chunkBlocks(savedBlocks, 4)[3]

    i = 0
    for x in savedBlocks:
        i = (i + 1)

        # skip blocks that were already processed or if not built
        if blocks['accounts'][x]['receive']['processed'] == True:
            print("Already processed receive")
            continue

        # increase average_tps and current_tps
        average_tps += 1
        current_tps += 1

        # calculate current_tps
        if time.perf_counter() - start > 1:
            if current_tps > highest_tps:
                highest_tps = current_tps
            current_tps = 0
            start = time.perf_counter()

        # process block
        blockObject = blocks['accounts'][x]
        block = blockObject['receive']
        print("block {0}".format((i-1)))
        print("Processing block {0}".format(block['hash']))
        result = process(block)

        failed = False # indicate if a block has failed
        if 'hash' in result:
            if len(result['hash']) == 64:
                processReceiveCount += 1
            else:
                failed = True
                failedBlocks[x]['receive'] = {'hash': block['hash'], 'result': result}
                print(result)
        else:
            failed = True
            failedBlocks[x]['receive'] = {'hash': block['hash'], 'result': result}
            print(result)

        if failed:
            blockObject['receive']['processed'] = False
        else:
            blockObject['receive']['processed'] = True
        # update processed
        blocks['accounts'][x] = blockObject

        # check if tps needs to throttle
        tpsDelay()

    if all == False:
        # calculate tps and print results
        tpsCalc()

def processSendBlocks(all = False, blockSection = 0):
    global keys
    global blocks

    # using global counters instead of local for processAll function
    global highest_tps
    global current_tps
    global average_tps
    global start
    global start_process
    global processSendCount
    global failedBlocks

    if all == False:
        start = time.perf_counter()
        start_process = time.perf_counter()

    # send all blocks
    savedBlocks = list(blocks['accounts'].keys())

    keyNum = options.num_accounts + 1
    # we may only want a subset of accounts
    savedBlocks = savedBlocks[0:keyNum]

    if blockSection != 0:
        if blockSection == 1:
            savedBlocks = chunkBlocks(savedBlocks, 4)[0]
        elif blockSection == 2:
            savedBlocks = chunkBlocks(savedBlocks, 4)[1]
        elif blockSection == 3:
            savedBlocks = chunkBlocks(savedBlocks, 4)[2]
        elif blockSection == 4:
            savedBlocks = chunkBlocks(savedBlocks, 4)[3]

    i = 0
    for x in savedBlocks:
        i = (i + 1)

        # skip blocks that were already processed or if not built
        if blocks['accounts'][x]['send']['processed'] == True:
            print("Already processed send")
            continue

        # increase average_tps and current_tps
        average_tps += 1
        current_tps += 1

        # calculate current_tps
        if time.perf_counter() - start > 1:
            if current_tps > highest_tps:
                highest_tps = current_tps
            current_tps = 0
            start = time.perf_counter()

        # process block
        blockObject = blocks['accounts'][x]
        block = blockObject['send']
        print("block {0}".format((i-1)))
        print("Processing block {0}".format(block['hash']))
        result = process(block)

        failed = False # indicate if a block has failed
        if 'hash' in result:
            if len(result['hash']) == 64:
                processSendCount += 1
            else:
                failed = True
                failedBlocks[x]['send'] = {'hash': block['hash'], 'result': result}
                print(result)
        else:
            failed = True
            failedBlocks[x]['send'] = {'hash': block['hash'], 'result': result}
            print(result)

        if failed:
            blockObject['send']['processed'] = False
        else:
            blockObject['send']['processed'] = True

        # update processed
        blocks['accounts'][x] = blockObject

        # check if tps needs to throttle
        tpsDelay()

    if all == False:
        # calculate tps and print results
        tpsCalc()

def processSends(allBlocks = False):
    thread1 = Thread(target = processSendBlocks, args = (allBlocks, 1))
    thread2 = Thread(target = processSendBlocks, args = (allBlocks, 2))
    thread3 = Thread(target = processSendBlocks, args = (allBlocks, 3))
    thread4 = Thread(target = processSendBlocks, args = (allBlocks, 4))
    thread1.start()
    thread2.start()
    thread3.start()
    thread4.start()
    thread1.join()
    """
    # single sequential thread for testing
    processSendBlocks(allBlocks, 1)
    processSendBlocks(allBlocks, 2)
    processSendBlocks(allBlocks, 3)
    processSendBlocks(allBlocks, 4)
    """
    time.sleep(threadDelay) # wait for threads or the printing will come in wrong order
    saveBlocks()
    saveFailedBlocks()

def processReceives(allBlocks = False):
    thread1 = Thread(target = processReceiveBlocks, args = (allBlocks, 1))
    thread2 = Thread(target = processReceiveBlocks, args = (allBlocks, 2))
    thread3 = Thread(target = processReceiveBlocks, args = (allBlocks, 3))
    thread4 = Thread(target = processReceiveBlocks, args = (allBlocks, 4))
    thread1.start()
    thread2.start()
    thread3.start()
    thread4.start()
    thread1.join()
    """
    # single sequential thread for testing
    processReceiveBlocks(allBlocks, 1)
    processReceiveBlocks(allBlocks, 2)
    processReceiveBlocks(allBlocks, 3)
    processReceiveBlocks(allBlocks, 4)
    """
    time.sleep(threadDelay) # wait for threads or the printing will come in wrong order
    saveBlocks()
    saveFailedBlocks()

def processAll():
    global processReceiveCount
    global processSendCount

    processReceiveCount = 0
    processSendCount = 0

    # receive all blocks
    processReceives(True)
    # send all blocks
    processSends(True)

    totalTime = time.perf_counter() - start_process - (threadDelay * 2)

    # calculate tps and print results
    tpsCalc()
    print("Processed " + str(processReceiveCount) + " receive blocks and " + str(processSendCount) + " send blocks")
    print("Total time: " + str(totalTime) + " seconds")

def buildAll():
    # build all receive blocks
    buildReceiveBlocks()
    # build all send blocks
    buildSendBlocks()

    print("Built " + str(buildReceiveCount) + " receive blocks and " + str(buildSendCount) + " send blocks")

def autoOnce():
    # build all blocks
    buildAll()
    # process all blocks
    processAll()

# recover single account
def recover(account):
    global keys
    global blocks
    if not account:
        return

    # ignore processed blocks because they don't need recovering
    if 'receive' in blocks['accounts'][account]:
        if 'processed' in blocks['accounts'][account]['receive']:
            if blocks['accounts'][account]['receive']['processed'] == True:
                return
    if 'send' in blocks['accounts'][account]:
        if 'processed' in blocks['accounts'][account]['send']:
            if blocks['accounts'][account]['send']['processed'] == True:
                return

    key = findKey(account)

    # pull info for our account
    info_out = getInfo(account)

    if not 'frontier' in info_out:
        return

    # if we have pending blocks, receive them
    if int(info_out["pending"]) > 0:
        receiveAllPending(key)
        # update info for our account
        info_out = getInfo(account)

    # set previous block
    prev = info_out["frontier"]
    type = getHistory(account)["history"][0]["type"]
    if type == 'send':
        blocks['accounts'][account]['send']['hash'] = prev
    elif type == 'receive':
        blocks['accounts'][account]['receive']['hash'] = prev
        blocks['accounts'][account]['receive']['processed'] = False

# reset all saved hashes and grab head blocks
def recoverAccounts():
    global processSendCount
    accounts = list(blocks['accounts'].keys())

    for account in accounts:
        # recover account
        recover(account)

    buildSendBlocks()
    processSendCount = 0
    processSends()

    # reset the process state or receive blocks can't be built
    for account in accounts:
        if not account:
            continue
        # pull info for our account
        info_out = getInfo(account)
        if not 'frontier' in info_out:
            continue

        type = getHistory(account)["history"][0]["type"]
        if type == 'receive':
            blocks['accounts'][account]['receive']['processed'] = True

    time.sleep(1)
    print("Processed " + str(processSendCount) + " send blocks")
    print("Accounts Recovered")
    writeJson('blocks.json', blocks)
    writeJson('accounts.json', accounts)

if options.mode == 'buildAccounts':
    buildAccounts()
elif options.mode == 'seedAccounts':
    seedAccounts()
elif options.mode == 'buildAll':
    buildAll()
elif options.mode == 'buildSend':
    buildSendBlocks()
    print("Built " + str(buildSendCount) + " send blocks")
elif options.mode == 'buildReceive':
    buildReceiveBlocks()
    print("Built " + str(buildReceiveCount) + " receive blocks")
elif options.mode == 'processSend':
    processSendCount = 0
    processSends()
    time.sleep(1)
    print("Processed " + str(processSendCount) + " send blocks")
elif options.mode == 'processReceive':
    processReceiveCount = 0
    processReceives()
    time.sleep(1)
    print("Processed " + str(processReceiveCount) + " receive blocks")
elif options.mode == 'processAll':
    processAll()
elif options.mode == 'autoOnce':
    autoOnce()
elif options.mode == 'countAccounts':
    getAccounts()
elif options.mode == 'recover':
    recoverAccounts()

# end slam thread
slamThread.stop()

# save all blocks and accounts
writeJson('blocks.json', blocks)
writeJson('accounts.json', accounts)
