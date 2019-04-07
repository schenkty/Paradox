# out-of-scope

This is my Nano playground for basically anything that nano needs but doesn't have.

## stress testing

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

### modes
buildAccounts - initial account/key pair setup and save

seedAccounts - fund each account (real-time)

buildSend - build all send blocks and save

buildReceive - build all receive blocks and save

buildAll - build all blocks for both receive and send and save

processSend - process all send blocks

processReceive - process all receive blocks

processAll - process all blocks for both receive and send

autoOnce - run through buildAll and processAll once

recover - reset specific account's previous block

recoverAll - reset all accounts
