import asyncio
import logging
import websockets

async def send_msg(websocket, logHint=''):
    while True:
        recv_text = await websocket.recv()
        log.info(f'recv{logHint} bandwidth = {recv_text} per second')

async def main_logic():
    async with websockets.connect('ws://127.0.0.1:8896') as websocket:
        await send_msg(websocket)

if __name__ == '__main__':

    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)

    asyncio.run(main_logic())