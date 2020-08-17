# Paradox Nano Stressor
from io import BytesIO
import json
import pycurl
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
from nanolib import Block, get_account_key_pair

parser = argparse.ArgumentParser(
    description='Paradox stress testing tool for NANO network. Sends 10 raw each to itself')
parser.add_argument('-n', '--num-accounts', type=int, help='Number of accounts', required=True)
parser.add_argument('-s', '--size', type=int, help='Size of each transaction in Nano raw', default=10)
parser.add_argument('-sn', '--save_num', type=int, help='Save blocks to disk how often', default=10000)
parser.add_argument('-r', '--representative', type=str, help='Representative to use', default='nano_1paradoxtestingxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxw5qzjpw3')
parser.add_argument('-bps', '--bps', type=float, help='Throttle blocks per second during processing. 1000 (default).', default=1000)
parser.add_argument('-m', '--mode', help='define what mode you would like', required=True, choices=['buildAccounts', 'seedAccounts', 'buildAll', 'buildSend', 'buildReceive', 'processSend', 'processReceive', 'processAll', 'autoOnce', 'countAccounts', 'recover', 'repair', 'benchmark'])
parser.add_argument('-nu', '--node_url', type=str, help='Nano node url', default='[::1]')
parser.add_argument('-np', '--node_port', type=int, help='Nano node port', default=7076)
parser.add_argument('-z', '--zero_work', type=str, help='Submits empty work', default='False')
parser.add_argument('-ss', '--save_seed', type=str, help='Save to file during initial seeding', default='False')
parser.add_argument('-dw', '--disable_watch_work', type=str, help='Disable watch_work feature for RPC process', default='False')
parser.add_argument('-al', '--auto_loops', type=int, help='How many times to run the autoOnce mode. 1 (default)', default=1)
parser.add_argument('-wu', '--work_url', type=str, help='Nano work url')
parser.add_argument('-wp', '--work_port', type=int, help='Nano work port')
options = parser.parse_args()

SAVE_EVERY_N = options.save_num

# add a circuit breaker variable
global signaled
signaled = False

# global vars
accounts = {'accounts':{}}
blocks = {'accounts':{}}
ZERO_AMT = '0000000000000000000000000000000000000000000000000000000000000000'

# keep track of number of built and processed blocks
buildReceiveCount = 0
buildSendCount = 0
processSendCount = 0
processReceiveCount = 0
validCount = 0

# bps counters
highest_bps = 0
average_bps = 0
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

# allow multidimentional dictionaries. Initialize: newDict = nestedDict(2, float)
def nestedDict(n, type):
    if n == 1:
        return defaultdict(type)
    else:
        return defaultdict(lambda: nestedDict(n-1, type))

# collect failed blocks
failedSeedBlocks = nestedDict(2, str)
failedProcessBlocks = nestedDict(2, str)

if os.path.exists('accounts.json'):
    accounts = readJson('accounts.json')

if os.path.exists('blocks.json'):
    blocks = readJson('blocks.json')

def printBPS():
    # print bps results
    results = ('Average transactions per second: {0}\n' +
           'Most transactions in 1 second: {1}').format(average_bps, highest_bps)
    print(results)

def findKey(account):
    return accounts['accounts'][account]['key']

def bpsCalc():
    global average_bps
    global start_process
    # calculate average_bps
    average_bps = validCount / (time.perf_counter() - start_process)

    # print bps results
    printBPS()

async def communicateNode(rpc_command, url=options.node_url, port=options.node_port):
    buffer = BytesIO()
    c = pycurl.Curl()
    c.setopt(c.URL, url)
    c.setopt(c.PORT, port)
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

async def getPending(account):
    return await communicateNode({'action':'pending', 'account': account, 'count': '10'})

async def getHistory(account, count='10'):
    return await communicateNode({'action':'account_history', 'account': account, 'count': count, 'reverse': True})

async def process(block):
    if 'block' in block:
        block = block['block']
    if options.disable_watch_work == 'true':
        return await communicateNode({'action': 'process', 'block': block, 'watch_work': False})
    else:
        return await communicateNode({'action': 'process', 'block': block})

async def getInfo(account):
    return await communicateNode({'action': 'account_info', 'account': account, 'count': 1, 'pending': True})

async def getBlockInfo(hash):
    return await communicateNode({'action': 'block_info', 'hash': hash})

async def getWork(hash):
    work_url = options.node_url
    work_port = options.node_port

    if options.work_url:
        work_url = options.work_url

    if options.work_port:
        work_port = options.work_port

    return await communicateNode({'action': 'work_generate', 'hash': hash, 'use_peers': True}, work_url, work_port)

async def generateBlock(key, account, balance, previous, link):
    block = Block(block_type='state', account=account, representative=options.representative, previous=previous, balance=balance, link=link)

    if options.zero_work == 'true':
        block.work = '1111111111111111'
        block.sign(key)
        return block.json()

    if previous == ZERO_AMT:
        pair = get_account_key_pair(key)
        previous = pair.public

    work = await getWork(previous)
    if work:
        block.work = work['work']
        block.sign(key)

    blockObj = {'hash': block.block_hash, 'block': block.json()}
    return blockObj

async def receive(key, account, prev):
    blockInfo = await getBlockInfo(prev)
    amount = int(blockInfo['amount'])
    newBalance = 0
    previous = prev

    info_out = await getInfo(account)
    if 'frontier' in info_out:
        previous = info_out['frontier']
        balance = info_out['balance']
        newBalance = int(balance) + int(amount)
    else:
        newBalance = amount
        previous = ZERO_AMT

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
    print('Fund Account {0}'.format(list(accounts['accounts'])[0]))

def getAccounts():
    global accounts
    keyNum = options.num_accounts + 1

    currentCount = len((list(accounts['accounts'])))
    print('Accounts {0}'.format(currentCount))

async def seedAccounts():
    global accounts
    global blocks
    global failedSeedBlocks

    prev = ZERO_AMT
    rpcTimings = {}

    # pull first account/key pair object from keys array
    accountList = list(accounts['accounts'])
    firstAccount = accountList[0]
    firstObject = accounts['accounts'][firstAccount]
    mainKey = firstObject['key']

    # pull info for our account
    await receiveAllPending(mainKey)
    info_out = await getInfo(accountList[0])

    # set previous block
    if 'frontier' in info_out:
        prev = info_out['frontier']
    else:
        print('Account Not Found. Please Check that account funds are pending')
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
            print('Account has already been seeded. Skipping...')
            continue

        # calculate the state block balance
        adjustedbal = int(info_out['balance']) - options.size * (i - 1)
        destObj = accounts['accounts'][destAccount]
        destKey = destObj['key']
        destPair = get_account_key_pair(destKey)
        destLink = destPair.public

        # build send block
        blockTimeStart = time.perf_counter() # measure the time taken for RPC call
        block_out = await generateBlock(mainKey, firstAccount, adjustedbal, prev, destLink)
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

        print('Building Send Block {0}'.format((i-1)))
        print('\nCreated block {0}'.format(hash))

        if options.save_seed == 'true':
            if i%SAVE_EVERY_N == 0:
                saveBlocks()
                saveAccounts()

    writeJson('blocks.json', blocks)
    writeJson('accounts.json', accounts)
    writeJson('seedRPCTimings.json', rpcTimings)
    saveFailedSeedBlocks()
    print('Seeded ' + str(processSeedCount) + ' blocks')

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
        previous = ZERO_AMT
        prev = ZERO_AMT
        newBalance = options.size

        if 'send' in blockObject:
            # skip blocks that were already built
            if 'processed' in blockObject['send']:
                if blockObject['send']['processed'] == False:
                    print('Receive block already built or failed process')
                    continue

            prev = blockObject['send']['hash']

            if 'block' in blockObject['send']:
                sendBal = json.loads(blockObject['send']['block'])
                newBalance = int(sendBal['balance']) + options.size

        if 'receive' in blockObject:
            # skip blocks that were already built
            if 'processed' in blockObject['receive']:
                if blockObject['receive']['processed'] == False:
                    print('Receive block already built or failed process')
                    continue

            previous = prev

        # build receive block
        block_out = await generateBlock(key, account, newBalance, previous, prev)
        if 'hash' not in block_out:
            continue
        hash = block_out['hash']
        block = block_out['block']
        receiveObject = {'hash':hash, 'block':block, 'processed':False}
        blockObject['receive'] = receiveObject
        blocks['accounts'][account] = blockObject
        print('Building Receive Block {0}'.format((i-1)))
        print('\nCreated block {0}'.format(block_out['hash']))
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
        pair = get_account_key_pair(key)
        link = pair.public
        previous = ZERO_AMT
        blockObject = blocks['accounts'][account]
        newBalance = 0

        if 'receive' in blockObject:
            # skip receive blocks that has not been built yet
            if 'processed' in blockObject['receive']:
                if blockObject['receive']['processed'] == True:
                    print('Receive block not built yet')
                    continue

            previous = blockObject['receive']['hash']
            receiveBal = json.loads(blockObject['receive']['block'])
            newBalance = int(receiveBal['balance']) - options.size

        # skip building if already built
        if 'send' in blockObject:
            if 'processed' in blockObject['send']:
                if blockObject['send']['processed'] == False:
                    print('Send block already built or failed process')
                    continue

        # build send block
        block_out = await generateBlock(key, account, newBalance, previous, link)
        if 'hash' not in block_out:
            continue
        hash = block_out['hash']
        block = block_out['block']
        sendObject = {'hash':hash, 'block':block, 'processed':False}
        blockObject['send'] = sendObject
        blocks['accounts'][account] = blockObject
        print('Building Send Block {0}'.format((i-1)))
        print('\nCreated block {0}'.format(block_out['hash']))
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
    global highest_bps

    # receive all blocks
    savedBlocks = list(blocks['accounts'].keys())

    keyNum = options.num_accounts + 1
    validCount = 0 # reset

    # we may only want a subset of accounts
    savedBlocks = savedBlocks[0:keyNum]

    # control the pace with asyncio chunks
    target = max([int(options.bps), 1])
    maxSleep = max([1 / options.bps, 1]) # max amount of time to sleep, used when target bps is < 1
    chunkCount = math.ceil(len(savedBlocks) / target)

    tasks = []

    if not all:
        start_process = time.perf_counter()

    # one iteration per chunk, ie. one second
    for i in range(chunkCount):
        start = time.perf_counter()
        currentCount = validCount
        print('Processing ' + type + ' chunk ' + str(i+1) + ' / ' + str(chunkCount))
        bpsChunk = chunkBlocks(savedBlocks, chunkCount)[i]

        # add the batch to run in parallel as ascynio tasks
        for account in bpsChunk:
            # skip blocks that were already processed or if not built
            if blocks['accounts'][account][type]['processed'] == True:
                print('Already processed ' + type)
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
        sleepTime = (maxSleep - (currentTime - start) - ((target - currentCount) * (maxSleep / target)))

        # real BPS without time compensation
        bps = min([currentCount / (currentTime - start), options.bps])
        highest_bps = max([bps, highest_bps])
        print('Average Chunk BPS: ' + str(bps))

        # if RPC saturation (the asyncio processes has taken more than 1 sec), loop as fast as possible
        if sleepTime < 0:
            sleepTime = 0

        await asyncio.sleep(sleepTime)

    if not all:
        # calculate bps and print results
        bpsCalc()

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

    # calculate bps and print results
    bpsCalc()
    print('Processed ' + str(processReceiveCount) + ' receive blocks and ' + str(processSendCount) + ' send blocks')
    print('Total time: ' + str(totalTime) + ' seconds')

async def buildAll():
    await buildReceiveBlocks()
    await buildSendBlocks()

    print('Built ' + str(buildReceiveCount) + ' receive blocks and ' + str(buildSendCount) + ' send blocks')

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
    if int(info_out['pending']) > 0:
        print('Receive pending')
        await receiveAllPending(key)
        # update info for our account
        info_out = await getInfo(account)

    # set previous block
    prev = info_out['frontier']
    historyAccount = await getHistory(account)
    type = historyAccount['history'][0]['type']
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
        type = historyAccount['history'][0]['type']
        if type == 'receive':
            blocks['accounts'][account]['receive']['processed'] = True

    print('Processed ' + str(processSendCount) + ' send blocks')
    print('Accounts Recovered')
    writeJson('blocks.json', blocks)
    writeJson('accounts.json', accounts)

# repair seeded accounts
async def repairSeedAccounts():
    global accounts
    global blocks

    # pull first account/key pair object from keys array
    accountList = list(accounts['accounts'])
    accountListCount = len(accountList)
    firstAccount = accountList[0]
    print('pulling history')
    history = await getHistory(firstAccount, str(accountListCount))
    history = history['history']
    print('history found')
    seedsFound = 0

    print('sorting history')
    for destBlock in history:
        if not destBlock:
            continue

        if 'hash' in destBlock:
            hash = destBlock['hash']
            destAccount = destBlock['account']
            blockObject = {'send': {'hash': hash}}

            # set seeded to true for destAccount
            if destAccount in accounts['accounts']:
                blocks['accounts'][destAccount] = blockObject
                accounts['accounts'][destAccount]['seeded'] = True
                seedsFound += 1
                print('\nFound seed {0}'.format(destAccount))

    print('\nSeeds Found {0}'.format(seedsFound))
    print('Accounts Repaired')
    writeJson('blocks.json', blocks)
    writeJson('accounts.json', accounts)

async def benchmark():
    await buildAccounts()
    await seedAccounts()
    await autoOnce()

    print('Benchmark Complete')

async def main():
    if options.mode == 'buildAccounts':
        await buildAccounts()

    elif options.mode == 'seedAccounts':
        await seedAccounts()

    elif options.mode == 'buildAll':
        await buildAll()

    elif options.mode == 'buildSend':
        await buildSendBlocks()
        print('Built ' + str(buildSendCount) + ' send blocks')

    elif options.mode == 'buildReceive':
        await buildReceiveBlocks()
        print('Built ' + str(buildReceiveCount) + ' receive blocks')

    elif options.mode == 'processSend':
        processSendCount = 0
        await processBlocks('send')
        print('Processed ' + str(processSendCount) + ' send blocks')

    elif options.mode == 'processReceive':
        processReceiveCount = 0
        await processBlocks('receive')
        print('Processed ' + str(processReceiveCount) + ' receive blocks')

    elif options.mode == 'processAll':
        await processAll()

    elif options.mode == 'autoOnce':
        await autoOnce()

    elif options.mode == 'countAccounts':
        getAccounts()

    elif options.mode == 'repair':
        await repairSeedAccounts()

    elif options.mode == 'recover':
        await recoverAccounts()

    elif options.mode == 'benchmark':
        await benchmark()

    # save all blocks and accounts
    writeJson('blocks.json', blocks)
    writeJson('accounts.json', accounts)

if __name__ == '__main__':
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
