import argparse
import asyncio
import ipaddress
import logging
import os
import signal
import struct
import sys
import traceback

async def doClient(clientR, clientW):
    serverR, serverW = None, None
    try:
        serverR, serverW = await asyncio.open_connection('127.0.0.1', 1082)

        asyncio.create_task(doServer(serverR, serverW, clientW))

        while True:
            data = await clientR.readline()
            if not data:
                print(f'EOF from client')
                break
            print(f'Receive from client line={data.decode().rstrip()}')
            serverW.write(data)
            await serverW.drain()
    except Exception as exc:
        print(f'{traceback.format_exc()}')

    clientW.close()
    await clientW.wait_closed()
    serverW.close()
    await serverW.wait_closed()

async def doServer(serverR, serverW, clientW):
    try:
        while True:
            data = await serverR.readline()
            if not data:
                print(f'EOF from server')
            print(f'Receive from server line={data.decode().rstrip()}')
            clientW.write(data)
            await clientW.drain()
    except Exception as exc:
        print(f'{traceback.format_exc()}')

    clientW.close()
    await clientW.wait_closed()
    serverW.close()
    await serverW.wait_closed()

async def main():
    srv = await asyncio.start_server(doClient, host=None, port=1081)
    addrList = list([s.getsockname() for s in srv.sockets])
    print(f'Proxy listen {addrList}')
    async with srv:
        await srv.serve_forever()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if sys.platform == 'win32':
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    asyncio.run(main())