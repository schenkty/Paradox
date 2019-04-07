from io import BytesIO
import json
import pycurl
import argparse
import sys
import time
import signal
import os.path

SAVE_EVERY_N = 10

parser = argparse.ArgumentParser(
    description="Stress test for NANO network. Sends 10 raw each to itself ")
parser.add_argument('-n', '--num-accounts', type=int, help='Number of accounts', required=True)
parser.add_argument('-s', '--size', type=int, help='Size of each transaction in RAW', default=10)
parser.add_argument('-sn', '--save_num', type=int, help='Save blocks to disk how often', default=10)
parser.add_argument('-r', '--representative', type=str, help='Representative to use', default='xrb_1brainb3zz81wmhxndsbrjb94hx3fhr1fyydmg6iresyk76f3k7y7jiazoji')
parser.add_argument('-tps', '--tps', type=int, help='Throttle transactions per second during processing. 0 (default) will not throttle.', default=0)
parser.add_argument('-m', '--mode', type=str, help='define what mode you would like', required=True)
parser.add_argument('-nu', '--node_url', type=str, help='set node url', required=True)
parser.add_argument('-np', '--node_port', type=int, help='set node port', default=7076)
parser.add_argument('-a', '--account', type=str, help='Account that will be used to spam', required=False)
options = parser.parse_args()

SAVE_EVERY_N = options.save_num

# read json file and decode it
def readJson(filename):
    with open(filename) as f:
        return json.load(f)

# write json file and encode it
def writeJson(filename, data):
    with open(filename, 'w') as json_file:
        json.dump(data, json_file)

def saveBlocks():
    writeJson('blocks.json', blocks)
    print('\n(SAVE) Blocks have been written to blocks.json\n')

# add a circuit breaker variable
global signaled
signaled = False

# global vars
keys = []
blocks = {'accounts':{}}
balance = 0

if os.path.exists('accounts.json'):
    keys = readJson('accounts.json')

if os.path.exists('blocks.json'):
    blocks = readJson('blocks.json')

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

def findAccount(key):
    for object in keys:
        if object['key'] == key:
            return object['account']

def findKey(account):
    for object in keys:
        if object['account'] == account:
            return object['key']

# generate new key pair
def getKeyPair():
    return communicateNode({'action': 'key_create'})

def getPending(account):
    return communicateNode({'action':'pending', 'account': account, 'count': '10'})

def getHistory(account):
    return communicateNode({'action':'account_history', 'account': account, 'count': '10', 'reverse': True})

def accountBalance(account):
    return communicateNode({'action': 'account_balance', 'account': account})

def process(block):
    if 'block' in block:
        block = block['block']
    return communicateNode({'action': 'process', 'block': block})

def getInfo(account):
    return communicateNode({'action': 'account_info', 'account': account, 'count': 1, 'pending': 'true' })

def getBlockInfo(hash):
    return communicateNode({'action': 'block_info', 'hash': hash})

def accountHistory(account):
    response = communicateNode({'action': 'account_history', 'account':account, 'count':100})
    history = response.history
    if not history:
        history = []

    return history

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

    balance = accountBalance(account)
    return balance['balance']

def buildAccounts():
    global keys
    keyNum = options.num_accounts

    if os.path.exists('accounts.json'):
        keys = readJson('accounts.json')
        keyNum = (keyNum - len(keys))

    for x in range(keyNum):
        newKey = getKeyPair()
        newKey = {'account': newKey['account'], 'key': newKey['private']}
        keys.append(newKey)

    writeJson('accounts.json', keys)
    first = keys[0]
    account = first['account'];
    print("Fund Account {0}".format(account))

def seedAccounts():
    global keys
    global blocks
    prev = None

    # build our array of accounts and keys
    buildAccounts()

    # pull first account/key pair object from keys array
    first = keys[0]
    account = first['account']
    mainKey = first['key']

    # amount of raw in each txn
    testSize = options.size

    # pull info for our account
    receiveAllPending(mainKey)
    info_out = getInfo(account)

    # set previous block
    prev = info_out["frontier"]

    # seed all accounts with test raw
    i = 0
    for x in keys:
        i = (i + 1)
        # create a blank destination account
        destAccount = x['account']

        # calculate the state block balance
        adjustedbal = str(int(info_out['balance']) - options.size * (i + 1))

        # build receive block
        block_out = generateBlock(mainKey, account, adjustedbal, prev, destAccount)

        hash = process(block_out)["hash"]
        blockObject = {'send': {'hash': hash}}
        blocks['accounts'][destAccount] = blockObject

        # save block as previous
        prev = block_out["hash"]

        # process current block
        process(block_out)

        print("\nCreated block {0}".format(hash))

        if i%SAVE_EVERY_N == 0:
            writeJson('blocks.json', blocks)
            print('\n(SAVE) Blocks have been written to blocks.json\n')
    saveBlocks()

def buildReceiveBlocks():
    global keys
    global blocks
    # receive all accounts with test raw
    i = 0
    for x in keys:
        i = (i + 1)
        # set account
        account = x['account']
        key = x['key']
        blockObject = blocks['accounts'][account]
        previous = '0'
        newBalance = options.size

        if 'send' in blockObject:
            previous = blockObject["send"]["hash"]

        if i == 1:
            newBalance = getInfo(account)['balance']

        # build receive block
        block_out = generateBlock(key, account, newBalance, previous, account)
        hash = block_out['hash']
        block = block_out["block"]
        receiveObject = {"hash":hash, "block":block, "processed":False}
        blockObject['receive'] = receiveObject
        blocks['accounts'][account] = blockObject

        print("\nCreated block {0}".format(block_out['hash']))

        if i%SAVE_EVERY_N == 0:
            writeJson('blocks.json', blocks)
            print('\n(SAVE) Blocks have been written to blocks.json\n')
    saveBlocks()

def buildSendBlocks():
    global keys
    global blocks
    global balance
    # send all accounts with test raw
    i = 0
    for x in keys:
        i = (i + 1)
        # set account
        account = x['account']
        key = x['key']
        blockObject = blocks['accounts'][account]
        prev = blockObject['receive']["hash"]
        newBalance = 0

        if i == 1:
            newBalance = getInfo(account)['balance']
        else:
            newBalance = options.size

        # build send block
        block_out = generateBlock(key, account, newBalance, prev, 'xrb_1jnatu97dka1h49zudxtpxxrho3j591jwu5bzsn7h1kzn3gwit4kejak756y')
        hash = block_out['hash']
        block = block_out["block"]
        sendObject = {"hash":hash, "block":block, "processed":False}
        blockObject['send'] = sendObject
        blocks['accounts'][account] = blockObject

        print("\nCreated block {0}".format(block_out['hash']))

        if i%SAVE_EVERY_N == 0:
            writeJson('blocks.json', blocks)
            print('\n(SAVE) Blocks have been written to blocks.json\n')
    saveBlocks()

def processReceives():
    global keys
    global blocks
    # receive all blocks
    savedBlocks = blocks['accounts'].keys()
    i = 0
    for x in savedBlocks:
        i = (i + 1)
        blockObject = blocks['accounts'][x]
        block = blockObject['receive']
        blockObject['receive']['processed'] = True

        print("Processing block {0}".format(block['hash']))
        process(block)
        # update processed
        blocks['accounts'][x] = blockObject
        if i%SAVE_EVERY_N == 0:
            writeJson('blocks.json', blocks)
            print('\n(SAVE) Blocks have been written to blocks.json\n')
        # delay next process if --tps is not 0, to throttle outgoing
        if options.tps != 0:
            while average_tps / (time.perf_counter() - start_process) > options.tps:
                time.sleep(0.001)
    saveBlocks()

def processSends():
    global keys
    global blocks
    # send all blocks
    savedBlocks = blocks['accounts'].keys()
    i = 0
    for x in savedBlocks:
        i = (i + 1)
        blockObject = blocks['accounts'][x]
        block = blockObject['send']
        blockObject['send']['processed'] = True
        print("Processing block {0}".format(block['hash']))
        print(process(block))
        # update processed
        blocks['accounts'][x] = blockObject

        if i%SAVE_EVERY_N == 0:
            saveBlocks()

        # delay next process if --tps is not 0, to throttle outgoing
        if options.tps != 0:
            while average_tps / (time.perf_counter() - start_process) > options.tps:
                time.sleep(0.001)
    saveBlocks()

def processAll():
    # receive all blocks
    processReceives()
    # send all blocks
    processSends()

def buildAll():
    # build all receive blocks
    buildReceiveBlocks()
    # build all send blocks
    buildSendBlocks()

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
        print("missing account")
        return

    key = findKey(account)

    # pull info for our account
    info_out = getInfo(account)

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
    print(prev)
    saveBlocks()

# reset all saved hashes and grab head blocks
def recoverAll():
    for x in keys:
        # set account
        account = x['account']
        recover(account)
    saveBlocks()

if options.mode == 'buildAccounts':
    buildAccounts()
elif options.mode == 'seedAccounts':
    seedAccounts()
elif options.mode == 'buildAll':
    buildAll()
elif options.mode == 'buildSend':
    buildSendBlocks()
elif options.mode == 'buildReceive':
    buildReceiveBlocks()
elif options.mode == 'processSend':
    processSends()
elif options.mode == 'processReceive':
    processReceives()
elif options.mode == 'processAll':
    processAll()
elif options.mode == 'autoOnce':
    autoOnce()
elif options.mode == 'recover':
    recover(options.account)
elif options.mode == 'recoverAll':
    recoverAll()
    
# save all blocks
saveBlocks()
