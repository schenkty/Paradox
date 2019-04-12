# recorder
Record and process data from Nano nodes

# install
Install `pycurl`

# usage
## run recorder manually:
`python3 record.py`  

## run recorder continuously:
Set Permissions for script:
1. `chmod +x run.sh`
2. `sh run.sh`

# process script
this script matches up the hashes from `record.py` and accounts from `stress.py`

1. provide the `blocks.json` file from `stress.py` and `data.json` from `record.py`
2. run `python3 process.py -l myblocks`
3. to process additional blocks, provide new `data.json` and `blocks.json` files. The final result file will be `data-info.json`

### launch arguments
1. `-l` - set label to identify your blocks, default to `Unknown`
