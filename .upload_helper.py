import base64, sys
data = base64.b64decode(sys.stdin.read())
with open(sys.argv[1], 'wb') as f:
    f.write(data)
