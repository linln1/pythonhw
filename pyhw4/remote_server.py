import argparse
import asyncio
import ipaddress
import logging
import os
import signal
import struct
import sys
import traceback
import sqlite3
import aiosqlite

from enum import Enum
ReadMode = Enum('ReadMod', ('EXACT', 'LINE', 'MAX', 'UNTIL'))

remoteProxyHost = '127.0.0.1'
remoteProxyPort = 8889
remotesocksPort = 8890

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
            data = await aioRead(rm_reader, ReadMode.MAX, maxLen=65535, logHint='recv data from server')
            await aioWrite(cl_writer, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

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
    rm_reader, rm_writer = None, None
    submit = await aioRead(reader, ReadMode.LINE)
    if submit.decode().split(" ")[0] == "sumbit:":
        params = submit.decode().split(" ")
        username, password = params[1], params[2]
        async with aiosqlite.connect('cache.db') as db:
            l = []
            l.append(username, password)
            t = tuple(l)
            async with db.execute('SELECT * FROM USER WHERE USERNAME=?', t[0]) as cur:
                async for row in cur:#一般也就找到一行记录
                    if row[1] == t[1]:
                        version = await aioRead(reader, ReadMode.EXACT, exactLen=1, logHint=f'1stByte')
                        if b'\x05' == version:
                            proxyType = 'SOCKS5'
                            numMethods = await aioRead(reader, ReadMode.EXACT, exactLen=1, logHint='nMethod')
                            await aioRead(reader, ReadMode.EXACT, exactLen=numMethods[0], logHint='methods')
                            await aioWrite(writer, b'\x05\x00', logHint='method.noAuth')
                            await aioRead(reader, ReadMode.EXACT, exactData=b'\x05\x01\x00', logHint='verCmdRsv')
                            atyp = await aioRead(reader, ReadMode.EXACT, exactLen=1, logHint='atyp')
                            dstHost = await socks5ReadDstHost(reader, atyp, logHint='dstHost')
                            dstPort = await aioRead(reader, ReadMode.EXACT, exactLen=2, logHint='dstPort')
                            dstPort = int.from_bytes(dstPort, 'big')
                            # 连接远程代理服务器

                            rm_reader, rm_writer = await asyncio.open_connection(dstHost, dstPort)
                            bindHost, bindPort, *_ = rm_writer.get_extra_info('sockname')

                            atyp, hostData = socks5EncodeBindHost(bindHost)
                            data = struct.pack(f'!ssss{len(hostData)}sH', b'\x05', b'\x00', b'\x00', atyp, hostData, int(bindPort))
                            await aioWrite(writer, data, logHint='reply')

                        else:
                            proxyType = 'HTTP TUNNEL'
                            line = await aioRead(reader, ReadMode.LINE, logHint='Connection Request Header')
                            line = version + line
                            req_headers = await aioRead(reader, ReadMode.UNTIL, untilSep=b'\r\n\r\n',
                                                        logHint='Request Header')
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
                            # 连接远程代理并且发送数据
                            logHint = f'{logHint} {dstHost} {dstPort}'
                            log.info(f'{logHint} connStart...')
                            try:
                                rm_reader, rm_writer = await asyncio.open_connection(dstHost, int(dstPort))
                                reply = f'HTTP/1.1 200 OK\r\n\r\n'
                                await aioWrite(writer, reply.encode())
                            except Exception as Err:
                                MyError(Err)
                                reply = "HTTP/1.1" + str(Err) + " Fail\r\n\r\n"
                                await aioWrite(writer, reply.encode())

                        if rm_writer:
                            await asyncio.wait({
                                asyncio.create_task(transfer_client_remote(reader, rm_writer)),
                                asyncio.create_task(transfer_remote_client(rm_reader, writer))
                            })


async def remoteTask(port): #启动远程代理服务器
    rm_srv = await asyncio.start_server(remoteProxyRun, host=remoteProxyHost, port=port)
    addrList = list([s.getsockname() for s in rm_srv.sockets])
    log.info(f'LISTEN Client Proxy {addrList}')
    async with rm_srv:
        await rm_srv.serve_forever()

def init_database():
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute('''DROP TABLE IF EXISTS USER ;''')
    c.execute('''CREATE TABLE USER
               (USERNAME           TEXT    NOT NULL,
               PASSWORD           TEXT);''')
    print("Table created successfully")

    c.execute('''INSERT INTO USER(USERNAME, PASSWORD) VALUES ('u1', '11');''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD) VALUES ('u2', '22');''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD) VALUES ('u3', '33');''')
    c.execute("SELECT * FROM USER")
    for row in c:
        print("NAME = ", row[0])
        print("PASSWORD = ", row[1])

    #('127.0.0.1', 8889)
    c.execute('''CREATE TABLE INFO
                (USERNAME           TEXT    NOT NULL,
               PASSWORD           TEXT,
               ADDRESS          TEXT,
               PORT         TEXT,
               STATUS       BOOL    NOT NULL);
            ''')

async def main():
    init_database()
    t1 = asyncio.create_task(remoteTask(remoteProxyPort))  # 创建任务
    t2 = asyncio.create_task(remoteTask(remotesocksPort))
    await asyncio.gather(t1, t2)
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