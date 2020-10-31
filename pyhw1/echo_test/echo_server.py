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
    try:
        while True:
            data = await clientR.readline()
            if not data:
                print(f'EOF')
                break
            print(f'Receive line={data.decode().rstrip()}')
            clientW.write(data)
            await clientW.drain()
    except Exception as exc:
        print(f'{traceback.format_exc()}')

    clientW.close()
    await clientW.wait_closed()

async def main():
    srv = await asyncio.start_server(doClient, host=None, port=1082)
    addrList = list([s.getsockname() for s in srv.sockets])
    print(f'Listen {addrList}')
    async with srv:
        await srv.serve_forever()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if sys.platform == 'win32':
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    asyncio.run(main())