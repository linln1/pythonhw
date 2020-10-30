import argparse
import asyncio
import ipaddress
import logging
import os
import signal
import struct
import sys
import time
import traceback

async def main():
    try:
        serverR, serverW = await asyncio.open_connection('127.0.0.1', 1081)
        while True:
            serverW.write(f'{time.asctime()}\n'.encode())
            await serverW.drain()
            data = await serverR.readline()
            if not data:
                print(f'EOF')
            print(f'Receive line={data.decode().rstrip()}')
            await asyncio.sleep(1)
    except Exception as exc:
        print(f'{traceback.format_exc()}')

    serverW.close()
    await serverW.wait_closed()

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    if sys.platform == 'win32':
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    asyncio.run(main())