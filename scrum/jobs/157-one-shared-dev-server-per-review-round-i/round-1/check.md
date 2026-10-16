CHECK: PASS

## Test: python3 -m unittest discover -s tests
exit 0
```
..................................................................................................................................................................................................................................local build ok: a85ca85 calc.py
.........................ss...............................................................................................................................................................................................................................----------------------------------------
Exception occurred during processing of request from ('127.0.0.1', 35334)
Traceback (most recent call last):
  File "/usr/lib/python3.13/socketserver.py", line 318, in _handle_request_noblock
    self.process_request(request, client_address)
    ~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.13/socketserver.py", line 349, in process_request
    self.finish_request(request, client_address)
    ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.13/socketserver.py", line 362, in finish_request
    self.RequestHandlerClass(request, client_address, self)
    ~~~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.13/socketserver.py", line 766, in __init__
    self.handle()
    ~~~~~~~~~~~^^
  File "/usr/lib/python3.13/http/server.py", line 451, in handle
    self.handle_one_request()
    ~~~~~~~~~~~~~~~~~~~~~~~^^
  File "/usr/lib/python3.13/http/server.py", line 439, in handle_one_request
    method()
    ~~~~~~^^
  File "/home/user/scrum/.claude/worktrees/scrum-157-one-shared-dev-server-per-review-round-i/tests/test_route.py", line 34, in do_GET
    self.wfile.write(type(self).body)
    ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "/usr/lib/python3.13/socketserver.py", line 845, in write
    self._sock.sendall(b)
    ~~~~~~~~~~~~~~~~~~^^^
BrokenPipeError: [Errno 32] Broken pipe
----------------------------------------
......................................................................................................................................................................................watchdog: broken: board.json is not valid JSON (Expecting property name enclosed in double quotes: line 1 column 2 (char 1)); fix or move it aside, it was not touched
...........
----------------------------------------------------------------------
Ran 668 tests in 95.985s

OK (skipped=2)
```

## .env check
no .env files in diff
