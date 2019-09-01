# out-of-nano-scope

This is my Nano playground for basically anything that nano needs but doesn't have.

## network stressor

1. install pycurl
2. build launch script
example: `python3 stress.py -m buildAccounts -n 10 -s 10 -nu 127.0.0.1`
in this example, we are connecting to a nano node running on localhost
and building 10 nano accounts.
3. fund account provided in terminal by step 2
4. run `python3 stress.py -m seedAccounts -n 10 -s 10 -nu 127.0.0.1`
5. run `python3 stress.py -m buildAll -n 10 -s 10 -nu 127.0.0.1`
6. run `python3 stress.py -m processAll -n 10 -s 10 -nu 127.0.0.1`
7. repeat steps 5 and 6

## disclaimers - please read

1. Do not edit or delete the `accounts.json` or `blocks.json` files
2. Do Not change the raw size `-s` used for testing. Once you set up accounts, you can only use that size. If you want to change the size, start from scratch with a new size command.
3. If you make any changes to `-n` make sure your accounts are always in the `receive` ready state.<br />

An example of proper subset usage is the following:<br />
`python3 stress.py -m autoOnce -n 10 -s 10 -nu 127.0.0.1`<br />
`python3 stress.py -m autoOnce -n 5 -s 10 -nu 127.0.0.1`<br />
`python3 stress.py -m autoOnce -n 10 -s 10 -nu 127.0.0.1`<br />

`autoOnce` does a full build cycle and process cycle which allows you to safely adjust the accounts used.

4. You can only increase the number of accounts (`-n`) during a send cycle (pending receive) for current accounts. If you add new accounts outside of this send cycle (after a receive and before a send), you will corrupt the accounts and their block orders. To recover this, call the mode - recoverAll.

### launch arguments

1. `-n` - Number of accounts used for testing
2. `-s` - Size of each transaction in RAW, default is 10 RAW
3. `-sn` - Save blocks or accounts to disk how often, default is every 10 blocks or accounts
4. `-r` - Representative to use, default is the brainblocks rep
5. `-tps` - Throttle transactions per second during processing, default is 0 which is no throttle
6. `-m` - define what mode you would like to use
7. `-nu` - url of the nano node that you would like to use, default is `127.0.0.1`
8. `-np` - port of the nano node that you would like to use, default is `55000`
9. `-z` - provide zero proof of work, default is `False`
10. `slam` - Variable TPS throttle, default is `False`
11. `slam_time` - Define how often slam is decided, default `20` for 20 seconds

Slam will not work unless `-tps` argument is specified. Slam is weighted towards the specified tps amount but it is randomly decided.

### launch modes

1. `buildAccounts` - initial account/key pair setup and save
2. `seedAccounts` - fund each account (real-time)
3. `buildSend` - build all send blocks and save
4. `buildReceive` - build all receive blocks and save
5. `buildAll` - build all blocks for both receive and send and save
6. `processSend` - process all send blocks
7. `processReceive` - process all receive blocks
8. `processAll` - process all blocks for both receive and send
9. `autoOnce` - run through buildAll and processAll once
10. `countAccounts` - return number of accounts built
11. `recover` - receive all pending blocks for every account, build a batch of send blocks and process send blocks
