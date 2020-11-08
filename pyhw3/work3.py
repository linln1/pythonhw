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

async def socks5ReadDstHost(r, atyp, *, logHint):
    dstHost = None
    if atyp == b'\x01':
        dstHost = await aioRead(r, ReadMode.EXACT, exactLen=4, logHint=f'{logHint} ipv4')
        dstHost = str(ipaddress.ip_address(dstHost))
    elif atyp == b'\x03':
        dataLen = await aioRead(r, ReadMode.EXACT, exactLen=1, logHint=f'{logHint} fqdnLen')
        dataLen = dataLen[0]
        dstHost = await aioRead(r, ReadMode.EXACT, exactLen=dataLen, logHint=f'{logHint} fqdn')
        dstHost = dstHost.decode('utf8')
    elif atyp == b'\x04':
        dstHost = await aioRead(r, ReadMode.EXACT, exactLen=16, logHint=f'{logHint} ipv6')
        dstHost = str(ipaddress.ip_address(dstHost))
    else:
        raise MyError(f'RECV ERRATYP={atyp} {logHint}')
    return dstHost

def socks5EncodeBindHost(bindHost):
    atyp = b'\x03'
    hostData = None
    try:
        ipAddr = ipaddress.ip_address(bindHost)
        if ipAddr.version == 4:
            atyp = b'\x01'
            hostData = struct.pack('!L', int(ipAddr))
        else:
            atyp = b'\x04'
            hostData = struct.pack('!16s', ipaddress.v6_int_to_packed(int(ipAddr)))
    except Exception:
        hostData = struct.pack(f'!B{len(bindHost)}s', len(bindHost), bindHost)
    return atyp, hostData

async def remoteProxyRun(reader, writer):
    address = await aioRead(reader, ReadMode.LINE)
    host_port = address.decode()
    host_port = host_port.replace("\r\n", " ")
    host = host_port.split(":")[0]
    port = host_port.split(":")[1]
    print('remote proxy server recieve host: {}' % host)
    print('remote proxy server recieve port: {}' % port)

    try:
        rm_reader, rm_writer = await asyncio.open_connection(host, int(port))
        reply = f'HTTP/1.1 200 OK\r\n'
        await aioWrite(writer, reply.encode())
    except Exception as Err:
        MyError(Err)
        reply = "HTTP/1.1" + str(Err) + " Fail\r\n\r\n"
        await aioWrite(writer, reply.encode())

    await asyncio.wait({
        asyncio.create_task(xferData(reader, rm_writer)),
        asyncio.create_task(xferData(rm_reader, writer))
    })

async def doClient(clientR, clientW):
    serverR, serverW = None, None
    try:
        clientHost, clientPort, *_ = clientW.get_extra_info('peername')
        logHint = f'{clientHost} {clientPort}'
        firstByte = await aioRead(clientR, ReadMode.EXACT, exactLen=1, logHint=f'1stByte')
        if b'\x05' == firstByte:
            proxyType = 'SOCKS5'
            logHint = f'{logHint} {proxyType}'
            numMethods = await aioRead(clientR, ReadMode.EXACT, exactLen=1, logHint='nMethod')
            await aioRead(clientR, ReadMode.EXACT, exactLen=numMethods[0], logHint='methods')
            await aioWrite(clientW, b'\x05\x00', logHint='method.noAuth')
            await aioRead(clientR, ReadMode.EXACT, exactData=b'\x05\x01\x00', logHint='verCmdRsv')
            atyp = await aioRead(clientR, ReadMode.EXACT, exactLen=1, logHint='atyp')
            dstHost = await socks5ReadDstHost(clientR, atyp, logHint='dstHost')
            dstPort = await aioRead(clientR, ReadMode.EXACT, exactLen=2, logHint='dstPort')
            dstPort = int.from_bytes(dstPort, 'big')
        else:
            line = await aioRead(clientR, ReadMode.LINE, logHint='1stLine')
            line = firstByte + line
            line = line.decode()
            method, uri, proto, *_ = line.split()
            if 'connect' == method.lower():
                proxyType = 'HTTPS'
                logHint = f'{logHint} {proxyType}'
                dstHost, dstPort, *_ = uri.split(':')
                data = await aioRead(clientR, ReadMode.UNTIL, untilSep=b'\r\n\r\n', logHint='msg')
            else:
                raise MyError(f'RECV INVALID={line.strip()} EXPECT=CONNECT')

        logHint = f'{logHint} {dstHost} {dstPort}'
        log.info(f'{logHint} connStart...')

        serverR, serverW = await asyncio.open_connection(dstHost, dstPort)
        bindHost, bindPort, *_ = serverW.get_extra_info('sockname')
        log.info(f'{logHint} connSucc bind {bindHost} {bindPort}')

        if 'SOCKS5' == proxyType:
            atyp, hostData = socks5EncodeBindHost(bindHost)
            data = struct.pack(f'!ssss{len(hostData)}sH', b'\x05', b'\x00', b'\x00', atyp, hostData, int(bindPort))
            await aioWrite(clientW, data, logHint='reply')
        else:
            serverR, serverW = await asyncio.open_connection(remoteProxyHost, remoteProxyPort)
            connect_info = dstHost + ':' + dstPort + '\r\n'
            await aioWrite(serverW, connect_info.encode(), logHint='Connect remote Proxy')
            # await aioWrite(clientW, f'{proto} 200 OK\r\n\r\n'.encode(), logHint='response')

        await asyncio.wait({
            asyncio.create_task(xferData(clientR, serverW, logHint=f'{logHint} fromClient')),
            asyncio.create_task(xferData(serverR, clientW, logHint=f'{logHint} fromServer'))
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
    srv = await asyncio.start_server(doClient, host=args.listenHost, port=args.listenPort)
    addrList = list([s.getsockname() for s in srv.sockets])
    log.info(f'LISTEN {addrList}')
    async with srv:
        await srv.serve_forever()

async def remoteTask(): #启动远程代理服务器
    rm_srv = await asyncio.start_server(remoteProxyRun, host=remoteProxyHost, port=remoteProxyPort)
    addrList = list([s.getsockname() for s in rm_srv.sockets])
    log.info(f'LISTEN Client Proxy {addrList}')
    async with rm_srv:
        await rm_srv.serve_forever()

async def xferData(srcR, dstW, *, logHint=None):
    try:
        while True:
            data = await aioRead(srcR, ReadMode.MAX, maxLen=65535, logHint='')
            await aioWrite(dstW, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

    await aioClose(dstW, logHint=logHint)

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
    _parser.add_argument('--host', dest='listenHost', metavar='listen_host', default='127.0.0.1', help='proxy listen host default listen all interfaces')
    _parser.add_argument('--port', dest='listenPort', metavar='listen_port', default= 8888, required=False, help='proxy listen port')
    args = _parser.parse_args()

    if sys.platform == 'win32':
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    asyncio.run(main())