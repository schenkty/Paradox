# Paradox Testing for NANO

Don't leave your RPC server accessible to the internet.

`peer.py` creates a local list of nano network peers who have their RPC vulnerable to the internet and stores it in `peer.json`

`protector.py` uses the `peer.json` list provided by `peer.py` to stop the vulnerable nodes and protect them from malicious attacks
