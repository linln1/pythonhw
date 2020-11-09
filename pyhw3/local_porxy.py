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
remotetunnelPort = 8889
remotesocksPort= 8890


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

async def transfer_client_remote(cl_reader, rm_writer, logHint=None):
    try:
        while True:
            data = await aioRead(cl_reader, ReadMode.MAX, maxLen=65535, logHint='')
            await aioWrite(rm_writer, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

async def transfer_remote_client(rm_reader, cl_writer, logHint=None):
    try:
        while True:
            data = await aioRead(rm_reader, ReadMode.MAX, maxLen=65535, logHint='')
            await aioWrite(cl_writer, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

async def local_run(clientR, clientW):
    serverR, serverW = None, None
    try:
        clientHost, clientPort, *_ = clientW.get_extra_info('peername')
        logHint = f'{clientHost} {clientPort}'
        if args.proto == 'SOCKS5':
            serverR, serverW = await asyncio.open_connection(remoteProxyHost, remotesocksPort)
            bindHost, bindPort, *_ = serverW.get_extra_info('sockname')
            log.info(f'{logHint} connSucc bind {bindHost} {bindPort}')

        else:
            line = await aioRead(clientR, ReadMode.LINE, logHint='Connection Request Header')
            req_headers = await aioRead(clientR, ReadMode.UNTIL, untilSep=b'\r\n\r\n', logHint='Request Header')
            line = line.decode()
            method, uri, proto, *_ = line.split()

            if 'connect' == method.lower():
                proxyType = 'HTTPS'
                logHint = f'{logHint} {proxyType}'
                i = uri.find(':')
                if i:
                    dstHost, dstPort = uri[:i], uri[i + 1:]
                else:
                    dstHost, dstPort = uri, 8889
            else:
                raise MyError(f'RECV INVALID={line.strip()} EXPECT=CONNECT')
            #连接远程代理并且发送数据
            logHint = f'{logHint} {remoteProxyHost} {remotetunnelPort}'
            log.info(f'{logHint} connStart...')
            serverR, serverW = await asyncio.open_connection(remoteProxyHost, remotetunnelPort)
            info = struct.pack("!B", 0x00)
            await aioWrite(serverW, info, logHint='Connect remote Proxy')
            connect_info = dstHost + ':' + dstPort + '\r\n'
            await aioWrite(serverW, connect_info.encode(), logHint='Connect remote Proxy')
            # await aioWrite(clientW, f'{proto} 200 OK\r\n\r\n'.encode(), logHint='response')

        await asyncio.wait({
            asyncio.create_task(transfer_client_remote(clientR, serverW, logHint=f'{logHint} fromClient')),
            asyncio.create_task(transfer_remote_client(serverR, clientW, logHint=f'{logHint} fromServer'))
        })

    except MyError as exc:
        log.info(f'{logHint} {exc}')
        await aioClose(clientW, logHint=logHint)
        await aioClose(serverW, logHint=logHint)
    except OSError:
        log.info(f'{logHint} connFail')
        await aioClose(clientW, logHint=logHint)
    except Exception as exc:
        log.error(f'{traceback.format_exc()}')
        exit(1)

async def localTask(): #启动本地代理服务器
    srv = await asyncio.start_server(local_run, host=args.listenHost, port=args.listenPort)
    addrList = list([s.getsockname() for s in srv.sockets])
    log.info(f'LISTEN {addrList}')
    async with srv:
        await srv.serve_forever()

async def main():
    asyncio.create_task(localTask())
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

    _parser = argparse.ArgumentParser(description='socks5 https dual proxy server')
    _parser.add_argument('--proto', dest='proto', metavar='protocol', default = 'http tunnel')
    _parser.add_argument('--host', dest='listenHost', metavar='listen_host', default='127.0.0.1', help='proxy listen host default listen all interfaces')
    _parser.add_argument('--port', dest='listenPort', metavar='listen_port', default= 8888, required=False, help='proxy listen port')
    args = _parser.parse_args()

    if sys.platform == 'win32':
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    asyncio.run(main())