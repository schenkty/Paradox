# Nano Stressor
# Ty Schenk 2019

# import required packages
from io import BytesIO
import json
import pycurl
from threading import Timer
from threading import Thread
import random
import argparse
import sys
import time
import signal
import os.path
import os
from collections import defaultdict
import asyncio
import async_timeout
import math

parser = argparse.ArgumentParser(
    description="Stress test for NANO network. Sends 10 raw each to itself ")
parser.add_argument('-n', '--num-accounts', type=int, help='Number of accounts', required=True)
parser.add_argument('-s', '--size', type=int, help='Size of each transaction in Nano raw', default=10)
parser.add_argument('-sn', '--save_num', type=int, help='Save blocks to disk how often', default=1000)
parser.add_argument('-r', '--representative', type=str, help='Representative to use', default='nano_1brainb3zz81wmhxndsbrjb94hx3fhr1fyydmg6iresyk76f3k7y7jiazoji')
parser.add_argument('-tps', '--tps', type=float, help='Throttle transactions per second during processing. 1000 (default).', default=1000)
parser.add_argument('-slam', '--slam', type=bool, help='Variable throttle transactions per second during processing. false (default) will not vary.', default=False)
parser.add_argument('-stime', '--slam_time', type=int, help='Define how often slam is decided', default=20)
parser.add_argument('-m', '--mode', help='define what mode you would like', required=True, choices=['buildAccounts', 'seedAccounts', 'buildAll', 'buildSend', 'buildReceive', 'processSend', 'processReceive', 'processAll', 'autoOnce', 'countAccounts', 'recover'])
parser.add_argument('-nu', '--node_url', type=str, help='Nano node url', default='[::1]')
parser.add_argument('-np', '--node_port', type=int, help='Nano node port', default=55000)
parser.add_argument('-z', '--zero_work', type=str, help='Submits empty work', default='False')
parser.add_argument('-ss', '--save_seed', type=str, help='Save to file during initial seeding', default='False')
parser.add_argument('-dw', '--disable_watch_work', type=str, help='Disable watch_work feature for RPC process (v20 needed)', default='False')
parser.add_argument('-al', '--auto_loops', type=int, help='How many times to run the autoOnce mode. 1 (default)', default=1)

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
validCount = 0
slamScale = 1.0

# tps counters
throttle_tps = options.tps
highest_tps = 0
current_tps = 0
average_tps = 0
start = 0
start_process = 0

# custom
# timeout for a whole chunk of RPC calls. Should be high because maybe you do 1000 BPS target
# but RPC is limited to 1 BPS. Then it will take 1000 seconds for that chunk and you don't want it to timeout
chunkTimeout = 100000

# read json file and decode it
def readJson(filename):
    with open(filename) as f:
        return json.load(f)

# write json file and encode it
def writeJson(filename, data):
    # backup old file to avoid corruption during save
    if os.path.exists(filename):
        os.rename(filename, filename + '.bak')
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
    global slamScale

    if not options.slam:
        return

    """
    if not options.slam:
        throttle_tps = options.tps
        return
    if options.tps == 0:
        throttle_tps = 0
        return
	scales = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    """
    # 0.5 = double BPS
    scales = [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.95, 0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6, 0.55, 0.5]
    slamScale = random.choice(scales)
    #throttle_tps = options.tps + (100 * slamScale)
    #newSlam = ("New Slam: {0}").format(throttle_tps)
    newSlam = ("New Slam: {0}").format(options.tps*slamScale)
    print(newSlam)

# allow multidimentional dictionaries. Initialize: newDict = nestedDict(2, float)
def nestedDict(n, type):
    if n == 1:
        return defaultdict(type)
    else:
        return defaultdict(lambda: nestedDict(n-1, type))

# collect failed blocks
failedSeedBlocks = nestedDict(2, str)
failedProcessBlocks = nestedDict(2, str)

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
    global average_tps
    global start_process
    # calculate average_tps
    average_tps = validCount / (time.perf_counter() - start_process)

    # print tps results
    printTPS()

async def communicateNode(rpc_command):
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
            if c is not None:
                c.perform()
                ok = True
            else:
                ok = False
        except pycurl.error as error:
            print('Communication with node failed with error: {}', error)
            await asyncio.sleep(2)
            global signaled
            if signaled: sys.exit(2)

    if buffer is not None:
        body = buffer.getvalue()
        parsed_json = json.loads(body.decode('iso-8859-1'))
        return parsed_json

# standard function to save blocks and print
def saveBlocks():
    writeJson('blocks.json', blocks)
    print('\n(SAVE) Blocks have been written to blocks.json\n')

# standard function to save failed blocks and print
def saveFailedProcessBlocks():
    writeJson('failedProcessBlocks.json', failedProcessBlocks)
    print('(SAVE) Failed blocks have been written to failedProcessBlocks.json\n')

# standard function to save failed blocks and print
def saveFailedSeedBlocks():
    writeJson('failedSeedBlocks.json', failedSeedBlocks)
    print('(SAVE) Failed blocks have been written to failedSeedBlocks.json\n')

# standard function to save accounts and print
def saveAccounts():
    writeJson('accounts.json', accounts)
    print('\n(SAVE) Accounts have been written to accounts.json\n')

# generate new key pair
async def getKeyPair():
    return await communicateNode({'action': 'key_create'})

# republish block to the nano network
async def republish(hash):
    return await communicateNode({'action': 'republish', 'hash': hash})

async def getPending(account):
    return await communicateNode({'action':'pending', 'account': account, 'count': '10'})

async def getHistory(account):
    return await communicateNode({'action':'account_history', 'account': account, 'count': '10', 'reverse': True})

async def process(block):
    if 'block' in block:
        block = block['block']
    if options.disable_watch_work == 'true':
        return await communicateNode({'action': 'process', 'block': block, 'watch_work': 'false'})
    else:
        return await communicateNode({'action': 'process', 'block': block})

async def getInfo(account):
    return await communicateNode({'action': 'account_info', 'account': account, 'count': 1, 'pending': 'true' })

async def getBlockInfo(hash):
    return await communicateNode({'action': 'block_info', 'hash': hash})

# validate if an address is the correct format
async def validate_address(address):
    # Check if the withdraw address is valid
    validate_command = {'action': 'validate_account_number', 'account': address}
    address_validation = await communicateNode(validate_command)

    # If the address did not start with xrb_ or nano_ or was deemed invalid by the node, return an error.
    address_prefix_valid = address[:4] == 'xrb_' or address[:5] == 'nano_'
    if not address_prefix_valid or address_validation['valid'] != '1':
        return False

    return True

async def generateBlock(key, account, balance, previous, link):
    create_block = {'action': 'block_create', 'type': 'state', 'account': account,
                    'link': link, 'balance': balance, 'representative': options.representative,
                    'previous': previous, 'key': key}

    if options.zero_work == 'true':
        create_block = {'action': 'block_create', 'type': 'state', 'account': account,
                        'link': link, 'balance': balance, 'representative': options.representative,
                        'previous': previous, 'key': key, 'work': '1111111111111111'}
    # Create block
    block_out = await communicateNode(create_block)
    return block_out

async def receive(key, account, prev):
    blockInfo = await getBlockInfo(prev)
    amount = blockInfo['amount']
    newBalance = 0
    previous = prev

    info_out = await getInfo(account)
    if 'frontier' in info_out:
        previous = info_out["frontier"]
        balance = info_out['balance']
        newBalance = str(int(balance) + int(amount))
    else:
        newBalance = amount
        previous = '0'

    block = await generateBlock(key, account, newBalance, previous, prev)
    return await process(block)

async def receiveAllPending(key):
    keyExpand = await communicateNode({'action':'key_expand', 'key':key})
    account = keyExpand['account']
    accounts = await getPending(account)
    blocks = accounts['blocks']

    for block in blocks:
        print(await receive(key, account, block))

async def buildAccounts():
    global accounts
    keyNum = options.num_accounts + 1

    currentCount = len((list(accounts['accounts'])))
    keyNum = (keyNum - currentCount)

    i = 0
    for x in range(keyNum):
        i = (i + 1)
        newKey = await getKeyPair()
        accountObject = {'key': newKey['private'], 'seeded': False}
        accounts['accounts'][newKey['account']] = accountObject

    writeJson('accounts.json', accounts)
    print("Fund Account {0}".format(list(accounts['accounts'])[0]))

def getAccounts():
    global accounts
    keyNum = options.num_accounts + 1

    currentCount = len((list(accounts['accounts'])))
    print("Accounts {0}".format(currentCount))

async def seedAccounts():
    global accounts
    global blocks
    global failedSeedBlocks

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
    await receiveAllPending(mainKey)
    info_out = await getInfo(accountList[0])

    # set previous block
    if 'frontier' in info_out:
        prev = info_out["frontier"]
    else:
        print("Account Not Found. Please Check that account funds are pending")
        return

    # seed all accounts with test raw
    i = 0
    processSeedCount = 0

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
        block_out = await generateBlock(mainKey, firstAccount, adjustedbal, prev, destAccount)
        blockTime = time.perf_counter() - blockTimeStart

        # save block as previous
        prev = block_out['hash']

        processTimeStart = time.perf_counter() # measure the time taken for RPC call
        result = await process(block_out)
        processTime = time.perf_counter() - processTimeStart

        failed = False
        hash = ''
        if 'hash' in result:
            if len(result['hash']) == 64:
                processSeedCount += 1
                hash = result['hash']
            else:
                failedSeedBlocks[x]['send'] = {'hash': block['hash'], 'result': result}
                print(result)
                failed = True

        blockObject = {'send': {'hash': hash}}
        blocks['accounts'][destAccount] = blockObject

        rpcTimings[str(i-1)] = {'block_create_time':blockTime, 'process_time':processTime}

        # set seeded to true for destAccount
        if failed:
            accounts['accounts'][destAccount]['seeded'] = False
        else:
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
    saveFailedSeedBlocks()
    print("Seeded " + str(processSeedCount) + " blocks")

async def buildReceiveBlocks():
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
                    print("Receive block already built or failed process")
                    continue

            prev = blockObject["send"]["hash"]

            if 'block' in blockObject["send"]:
                sendBal = json.loads(blockObject["send"]["block"])
                newBalance = str(int(sendBal["balance"]) + options.size)

        if 'receive' in blockObject:
            # skip blocks that were already built
            if 'processed' in blockObject["receive"]:
                if blockObject["receive"]['processed'] == False:
                    print("Receive block already built or failed process")
                    continue

            previous = prev

        # build receive block
        block_out = await generateBlock(key, account, newBalance, previous, prev)
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

async def buildSendBlocks():
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
                    print("Receive block not built yet")
                    continue

            previous = blockObject['receive']["hash"]
            receiveBal = json.loads(blockObject["receive"]["block"])
            newBalance = str(int(receiveBal["balance"]) - options.size)

        # skip building if already built
        if 'send' in blockObject:
            if 'processed' in blockObject["send"]:
                if blockObject["send"]['processed'] == False:
                    print("Send block already built or failed process")
                    continue

        # build send block
        block_out = await generateBlock(key, account, newBalance, previous, account)
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

async def asyncProcess(blockObject, account, type):
    global validCount
    global processReceiveCount
    global processSendCount
    global failedProcessBlocks
    global blocks

    block = blockObject[type]
    result = await process(block)

    failed = False # indicate if a block has failed

    if 'hash' in result:
        if len(result['hash']) == 64:
            validCount += 1
            print('Valid: ' + result['hash'])
            if type == 'receive':
                processReceiveCount += 1
            elif type == 'send':
                processSendCount += 1
        else:
            failed = True
    else:
        failed = True

    if failed:
        failedProcessBlocks[account][type] = {'hash': block['hash'], 'result': result}
        blockObject[type]['processed'] = False
        print(result)
    else:
        blockObject[type]['processed'] = True
    # update processed
    blocks['accounts'][account] = blockObject

async def processBlocks(type, all = False):
    # using global counters instead of local for processAll function
    global validCount
    global start_process
    global highest_tps

    # receive all blocks
    savedBlocks = list(blocks['accounts'].keys())

    keyNum = options.num_accounts + 1
    validCount = 0 # reset

    # we may only want a subset of accounts
    savedBlocks = savedBlocks[0:keyNum]

    # control the pace with asyncio chunks
    target = max([int(options.tps), 1])
    maxSleep = max([1 / options.tps, 1]) # max amount of time to sleep, used when target tps is < 1
    chunkCount = math.ceil(len(savedBlocks) / target)

    tasks = []

    if not all:
        start_process = time.perf_counter()

    # one iteration per chunk, ie. one second
    for i in range(chunkCount):
        start = time.perf_counter()
        currentCount = validCount
        print("Processing " + type + " chunk " + str(i+1) + " / " + str(chunkCount))
        bpsChunk = chunkBlocks(savedBlocks, chunkCount)[i]

        # add the batch to run in parallel as ascynio tasks
        for account in bpsChunk:
            # skip blocks that were already processed or if not built
            if blocks['accounts'][account][type]['processed'] == True:
                print("Already processed " + type)
                continue

            blockObject = blocks['accounts'][account]
            tasks.append(asyncio.ensure_future(asyncProcess(blockObject, account, type)))

        try:
            with async_timeout.timeout(chunkTimeout):
                # process the blocks
                await asyncio.gather(*tasks)

        except asyncio.TimeoutError as t:
            pass
            print('RPC process timed out')

        # valid count in latest iteration
        currentCount = validCount - currentCount

        # calculate how long to wait to get a full second (but subtract time if blocks were less than the target)
        currentTime = time.perf_counter()
        sleepTime = (maxSleep - (currentTime - start) - ((target - currentCount) * (maxSleep / target))) * slamScale

        # real BPS without time compensation
        bps = min([currentCount / (currentTime - start), options.tps])
        highest_tps = max([bps, highest_tps])
        print("Average Chunk BPS: " + str(bps))

        # if RPC saturation (the asyncio processes has taken more than 1 sec), loop as fast as possible
        if sleepTime < 0:
            sleepTime = 0

        await asyncio.sleep(sleepTime)

    if not all:
        # calculate tps and print results
        tpsCalc()

async def processSends(allBlocks = False):
    await processBlocks('send', allBlocks)

    saveBlocks()
    saveFailedProcessBlocks()

async def processReceives(allBlocks = False):
    await processBlocks('receive', allBlocks)

    saveBlocks()
    saveFailedProcessBlocks()

async def processAll():
    global processReceiveCount
    global processSendCount
    global start_process

    processReceiveCount = 0
    processSendCount = 0

    start_process = time.perf_counter()
    # receive all blocks
    await processReceives(True)
    # send all blocks
    await processSends(True)

    totalTime = time.perf_counter() - start_process

    # calculate tps and print results
    tpsCalc()
    print("Processed " + str(processReceiveCount) + " receive blocks and " + str(processSendCount) + " send blocks")
    print("Total time: " + str(totalTime) + " seconds")

async def buildAll():
    await buildReceiveBlocks()
    await buildSendBlocks()

    print("Built " + str(buildReceiveCount) + " receive blocks and " + str(buildSendCount) + " send blocks")

async def autoOnce():
    loops = options.auto_loops
    while loops > 0:
        # build all blocks
        await buildAll()
        # process all blocks
        await processAll()
        loops -= 1

# recover single account
async def recover(account):
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
    info_out = await getInfo(account)

    if not 'frontier' in info_out:
        return

    # if we have pending blocks, receive them
    if int(info_out["pending"]) > 0:
        print("Receive pending")
        await receiveAllPending(key)
        # update info for our account
        info_out = await getInfo(account)

    # set previous block
    prev = info_out["frontier"]
    historyAccount = await getHistory(account)
    type = historyAccount["history"][0]["type"]
    if type == 'send':
        blocks['accounts'][account]['send']['hash'] = prev
        blocks['accounts'][account]['send']['processed'] = True # simulate processed or it will not be built in next step
    elif type == 'receive':
        blocks['accounts'][account]['receive']['hash'] = prev
        blocks['accounts'][account]['receive']['processed'] = False

# reset all saved hashes and grab head blocks
async def recoverAccounts():
    global processSendCount
    accounts = list(blocks['accounts'].keys())

    for account in accounts:
        # recover account
        await recover(account)

    await buildSendBlocks()

    processSendCount = 0
    await processSends()

    # reset the process state or receive blocks can't be built
    for account in accounts:
        if not account:
            continue
        # pull info for our account
        info_out = await getInfo(account)
        if not 'frontier' in info_out:
            continue

        historyAccount = await getHistory(account)
        type = historyAccount["history"][0]["type"]
        if type == 'receive':
            blocks['accounts'][account]['receive']['processed'] = True

    print("Processed " + str(processSendCount) + " send blocks")
    print("Accounts Recovered")
    writeJson('blocks.json', blocks)
    writeJson('accounts.json', accounts)

async def main():
    if options.mode == 'buildAccounts':
        await buildAccounts()

    elif options.mode == 'seedAccounts':
        await seedAccounts()

    elif options.mode == 'buildAll':
        await buildAll()

    elif options.mode == 'buildSend':
        await buildSendBlocks()
        print("Built " + str(buildSendCount) + " send blocks")

    elif options.mode == 'buildReceive':
        await buildReceiveBlocks()
        print("Built " + str(buildReceiveCount) + " receive blocks")

    elif options.mode == 'processSend':
        processSendCount = 0
        await processBlocks('send')
        print("Processed " + str(processSendCount) + " send blocks")

    elif options.mode == 'processReceive':
        processReceiveCount = 0
        await processBlocks('receive')
        print("Processed " + str(processReceiveCount) + " receive blocks")

    elif options.mode == 'processAll':
        await processAll()

    elif options.mode == 'autoOnce':
        await autoOnce()

    elif options.mode == 'countAccounts':
        getAccounts()

    elif options.mode == 'recover':
        await recoverAccounts()

    # end slam thread
    slamThread.stop()

    # save all blocks and accounts
    writeJson('blocks.json', blocks)
    writeJson('accounts.json', accounts)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
