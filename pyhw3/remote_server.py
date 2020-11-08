import argparse
import asyncio
import ipaddress
import logging
import os
import signal
import struct
import sys
import traceback

from enum import Enum
ReadMode = Enum('ReadMod', ('EXACT', 'LINE', 'MAX', 'UNTIL'))

remoteProxyHost = '127.0.0.1'
remoteProxyPort = 8889
class MyError(Exception):
    pass

async def aioClose(w, *, logHint=None):
    if not w:
        await asyncio.sleep(0.001)
        return
    host, port, *_ = w.get_extra_info('peername')
    log.info(f'{logHint} close... peer {host} {port}')
    try:
        w.close()
        await w.wait_closed()
    except Exception as exc:
        pass

async def aioRead(r, mode, *, logHint=None, exactData=None, exactLen=None, maxLen=-1, untilSep=b'\r\n'):
    data = None
    try:
        if ReadMode.EXACT == mode:
            exactLen = len(exactData) if exactData else exactLen
            data = await r.readexactly(exactLen)
            if exactData and data != exactData:
                raise MyError(f'recvERR={data} {logHint}')
        elif ReadMode.LINE == mode:
            data = await r.readline()
        elif ReadMode.MAX == mode:
            data = await r.read(maxLen)
        elif ReadMode.UNTIL == mode:
            data = await r.readuntil(untilSep)
        else:
            log.error(f'INVALID mode={mode}')
            exit(1)
    except ConnectionResetError as exc:
        raise MyError(f'recvEXC={exc} {logHint}')
    except ConnectionAbortedError as exc:
        raise MyError(f'recvEXC={exc} {logHint}')
    if not data:
        raise MyError(f'recvEOF {logHint}')
    return data

async def aioWrite(w, data, *, logHint=''):
    try:
        w.write(data)
        await w.drain()
    except ConnectionAbortedError as exc:
        raise MyError(f'sendEXC={exc} {logHint}')

async def xferData(srcR, dstW, *, logHint=None):
    try:
        while True:
            data = await aioRead(srcR, ReadMode.MAX, maxLen=65535, logHint='')
            await aioWrite(dstW, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

    await aioClose(dstW, logHint=logHint)

async def remoteProxyRun(reader, writer):
    address = await aioRead(reader, ReadMode.LINE)
    host_port = address.decode()
    host_port = host_port.replace("\r\n"," ")
    i = host_port.find(':')
    if i:
        host, port = host_port[:i], host_port[i+1:]
    else:
        host, port = host_port, 8889

    try:
        rm_reader, rm_writer = await asyncio.open_connection(host, int(port))
        reply = f'HTTP/1.1 200 OK\r\n\r\n'
        await aioWrite(writer, reply.encode())
    except Exception as Err:
        MyError(Err)
        reply = "HTTP/1.1" + str(Err) + " Fail\r\n\r\n"
        await aioWrite(writer, reply.encode())

    await asyncio.wait({
        asyncio.create_task(xferData(reader, rm_writer)),
        asyncio.create_task(xferData(rm_reader, writer))
    })

async def remoteTask(): #启动远程代理服务器
    rm_srv = await asyncio.start_server(remoteProxyRun, host=remoteProxyHost, port=remoteProxyPort)
    addrList = list([s.getsockname() for s in rm_srv.sockets])
    log.info(f'LISTEN Client Proxy {addrList}')
    async with rm_srv:
        await rm_srv.serve_forever()


async def main():
    asyncio.create_task(remoteTask())
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)

    asyncio.run(main())