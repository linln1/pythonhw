
import asyncio
import ipaddress
import logging
import signal
import struct
import sqlite3
import aiosqlite
import argparse
from time import time
from threading import RLock, Timer
import better_exceptions

from enum import Enum
ReadMode = Enum('ReadMod', ('EXACT', 'LINE', 'MAX', 'UNTIL'))

remoteProxyHost = '127.0.0.1'
remoteProxyPort = 8889
remotesocksPort = 8890
uBucketdict = dict()
sBucketdict = dict()
sendBandWidth = 0

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

async def aioRead( r, mode, *, logHint=None, exactData=None, exactLen=None, maxLen=-1, untilSep=b'\r\n', user = None, bucket = None):
    data = None
    uBucket = None
    # if user:
    #     uBucket = uBucketdict[user]
    # if bucket:
    #     uBucket = bucket
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
    # if uBucket:
    #     await uBucket.input(data)
    return data

async def aioWrite(w, data, *, logHint=''):
    try:
        w.write(data)
        await w.drain()
    except ConnectionAbortedError as exc:
        raise MyError(f'sendEXC={exc} {logHint}')

async def recieve_data_from_local(cl_reader, logHint=None, user=None):
    try:
        while True:
            data = await aioRead(cl_reader, ReadMode.MAX, maxLen=65535, logHint='', bucket=uBucketdict[user])
            print(data)
    except MyError as exc:
        log.info(f'{logHint} {exc}')

async def send_data_to_server(cl_reader, rm_writer, dpsr, dpsm, logHint= None, user=None):
    try:
        uBucket = uBucketdict[user]
        async with aiosqlite.connect('cache.db') as db:
            while True:
                tokenNum = 65535
                tokenNum = await uBucket.acquireToken(65535)
                dps = await aioRead(cl_reader, ReadMode.MAX, maxLen=tokenNum, logHint='')
                leftToken = tokenNum - len(dps)
                if leftToken:
                    uBucket.releaseToken(leftToken)
                await aioWrite(rm_writer, dps, logHint='')
                global sendBandWidth
                sendBandWidth = tokenNum
                await aioWrite(dpsm, data=(str(sendBandWidth)+'\r\n').encode(), logHint=logHint)
                # await db.execute("UPDATE USER SET BANDWIDTH='u1' WHERE USERNAME=?", (tokenNum, user,))
                #
                # async with db.execute("SELECT * FROM USER WHERE USERNAME = ?" , (user, )) as cur:
                #     async for row in cur:
                #         print(row[2])

                await db.commit()

    except MyError as exc:
        log.info(f'{logHint} {exc}')

async def transfer_client_remote(cl_reader, rm_writer, logHint=None, user=None):
    try:
        while True:
            data = await aioRead(cl_reader, ReadMode.MAX, maxLen=65535, logHint='')
            await aioWrite(rm_writer, data, logHint='')
    except MyError as exc:
        log.info(f'{logHint} {exc}')

async def transfer_remote_client(rm_reader, cl_writer, logHint=None, user=None):
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

async def remoteProxyRun(reader, writer, logHint=None):
    rm_reader, rm_writer = None, None
    submit = await aioRead(reader, ReadMode.LINE)
    if submit.decode().split(" ")[0] == "sumbit:":
        params = submit.decode().split(" ")
        username, password = params[1], params[2]
        current_throughput = 0
        async with aiosqlite.connect('cache.db') as db:
            async with db.execute('SELECT * FROM USER WHERE USERNAME=\'u1\' and PASSWORD=\'11\' ' ) as cur:
                async for row in cur:
                    current_throughput = row[2]
                # print("now into database")
                if current_throughput >= int(args.lim):
                    print("server is too busy, please try to connect again after a while")
                    return
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
                    i = uri.find(':')
                    if i:
                        dstHost, dstPort = uri[:i], uri[i + 1:]
                    else:
                        dstHost, dstPort = uri, 8889

                    if 'connect' == method.lower():
                        proxyType = 'HTTPS'
                        logHint = f'{logHint} {proxyType}'

                    # else:
                    #     raise MyError(f'RECV INVALID={line.strip()} EXPECT=CONNECT')

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

                dpsr, dpsm = await asyncio.open_connection(host='127.0.0.1', port=9999)

                if rm_writer:
                    await asyncio.wait({
                        #asyncio.create_task(recieve_data_from_local(reader, user=username)),
                        #asyncio.create_task(tokenLeakTask(username)),
                        asyncio.create_task(send_data_to_server(reader, rm_writer, dpsr, dpsm, user=username)),
                        # asyncio.create_task(recieve_data_from_server(rm_reader, user=username)),
                        # asyncio.create_task(send_data_to_client(writer, user=username))
                        # asyncio.create_task(transfer_client_remote(reader, rm_writer)),
                        asyncio.create_task(transfer_remote_client(rm_reader, writer))
                    })


async def tokenLeakTask():
    while True:
        log.info(f'tokenLeak...')
        await asyncio.sleep(1)
        for user, uBucket in uBucketdict.items():
            uBucket.releaseToken(args.lim)

async def remoteTask(port):
    rm_srv = await asyncio.start_server(remoteProxyRun, host=remoteProxyHost, port=port)
    addrList = list([s.getsockname() for s in rm_srv.sockets])
    log.info(f'LISTEN Client Proxy {addrList}')
    async with rm_srv:
        await rm_srv.serve_forever()

class leakyBucket(object):
    def __init__(self, username,  capacity, leak_rate):
        '''
        :param capacity: the total data in the bucket
        :param leak_rate: the rate data per seconds that the bucket leaks
        :param :
        '''
        self.owner = username
        self._capacity = float(capacity)
        self._used_tokens = 0
        self._leak_rate = leak_rate
        self._last_time = 0
        self.lock = asyncio.Lock()
        self.tokenSemaphore = asyncio.BoundedSemaphore(1)
        self._data = ""
        self.status = True

    def __del__(self):
        self.lock = None
        self.tokenSemaphore = None
        self.data = None
        self.owner = None

    async def acquireToken(self, count):
        await self.tokenSemaphore.acquire()
        tokenCount = min(self._used_tokens, count)
        self._used_tokens -= tokenCount
        if self._used_tokens > 0:
            try:
                self.tokenSemaphore.release()
            except ValueError:
                pass
        else:
            self._used_tokens = 0
        return tokenCount

    def releaseToken(self, count):
        # async with self.tokenLock:
        self._used_tokens = min(self._used_tokens + int(count), self._capacity)
        try:
            self.tokenSemaphore.release()
        except ValueError:
            pass

    async def input(self, data):
        data = str(data)
        newdatalen = len(data)
        self.lock.acquire()
        if len(self._data) + newdatalen < self._capacity:
            self._data = self._data + data
        else:
            self._data = self._data + data[:self._capacity - len(self._data)]
            print("data overflow out of the bucket {}" % data[self._capacity - len(self._data):])
        self._last_time = time()
        if len(data):
            self.status = True
        self.lock.release()

    def write(self, lens):
        lens = int(lens)
        self.lock.acquire()
        output = self._data[:lens] if (len(self._data) >= lens) else self._data
        self._data = self._data[lens:] if (len(self._data) >= lens) else ""
        if len(self._data) == 0:
            self.status = False
        self.lock.release()
        return output


def init_database():
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute('''DROP TABLE IF EXISTS USER ;''')
    c.execute('''CREATE TABLE USER
               (USERNAME           TEXT    NOT NULL,
               PASSWORD           TEXT      ,
               BANDWIDTH        DOUBLE      );''')
    print("Table created successfully")

    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u1', '11', 10);''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u2', '22', 10);''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u3', '33', 10);''')

    c.execute("SELECT * FROM USER")
    for row in c:
        print("NAME = ", row[0])
        print("PASSWORD = ", row[1])
        print("BANDWIDTH = ", row[2])

    #('127.0.0.1', 8889)
    c.execute('''CREATE TABLE INFO
                (USERNAME           TEXT    NOT NULL,
               PASSWORD           TEXT,
               ADDRESS          TEXT,
               PORT         TEXT,
               STATUS       BOOL    NOT NULL);
            ''')

async def main():
    #init_database()
    for user in ['u1', 'u2', 'u3']:
        uBucketdict[user] = leakyBucket(user, args.cap, args.lim)
        sBucketdict[user] = leakyBucket(user, args.cap, args.lim)

    t1 = asyncio.create_task(remoteTask(remoteProxyPort))
    t2 = asyncio.create_task(remoteTask(remotesocksPort))
    t3 = asyncio.create_task(tokenLeakTask())
    # tasks = [t1, t2, t3]
    # await asyncio.gather(*tasks)
    await asyncio.wait({
        asyncio.create_task(remoteTask(remoteProxyPort)),
        asyncio.create_task(remoteTask(remotesocksPort)),
        asyncio.create_task(tokenLeakTask())
    })
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

    _parser = argparse.ArgumentParser(description='add traffic control')
    _parser.add_argument('--limit', dest='lim', metavar='lim', default='1500000', help='the limit of the web ')
    _parser.add_argument('--capacity', dest='cap', metavar='cap', default = '10000000', help='the capacity of the bucket')

    args = _parser.parse_args()
    asyncio.run(main())