# improve report — online.py

seed 4242 · end-to-end re-check: nothing_changed (0 checks) · effect shell byte-identical: True

| function | action | speedup | checks | inputs |
|---|---|---:|---:|---:|

Effect shell (preserved byte for byte):

* `login` (line 12): line 13: keyword arguments in call
* `sign` (line 20): line 21: call to hmac.new(session_key.encode(), json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest() (no op card or lifted function)
* `send_state` (line 24): line 25: expression Dict
* `receive` (line 30): line 31: call to sock.makefile().readline() (no op card or lifted function)
