
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

from enum import Enum
ReadMode = Enum('ReadMod', ('EXACT', 'LINE', 'MAX', 'UNTIL'))

remoteProxyHost = '127.0.0.1'
remoteProxyPort = 8889
remotesocksPort = 8890
uBucketdict = dict()
sBucketdict = dict()
DataBaseLock = RLock()

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
    if user:
        uBucket = uBucketdict[user]  # 取出这个用户拥有的桶，所有的数据经过桶过滤一次之后再发出去就可以，每次发送出去的数据是从桶里面取出来的
    if bucket:
        uBucket = bucket
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
    if uBucket:
        uBucket.input(data)
    return data

async def aioWrite(w, data, *, logHint=''):
    try:
        w.write(data)
        await w.drain()
    except ConnectionAbortedError as exc:
        raise MyError(f'sendEXC={exc} {logHint}')

async def recieve_data_from_local(cl_reader, logHint=None, user=None):
    if user:
        uBucket = uBucketdict[user]
    try:
        while True:
            data = await aioRead(cl_reader, ReadMode.MAX, maxLen=65535, logHint='', bucket=uBucket)
    except MyError as exc:
        log.info(f'{logHint} {exc}')

# 这个函数和上面的不同，只要有数据，就会不停的发
async def send_data_to_server(rm_writer, user=None):
    if user:
        uBucket = uBucketdict[user]
        conn = sqlite3.connect('cache.db')
        c = conn.cursor()
    while True:
        start = time()
        if uBucket.status:
            dps = uBucket.write(args.lim)
            DataBaseLock.acquire()
            c.execute("UPDATE USER SET BANDWITH=? WHERE USERNAME=?", (len(dps), user,))
            DataBaseLock.release()
            await aioWrite(rm_writer, uBucket.write(args.lim), logHint='')
        await asyncio.sleep(1 - (time() - start))

async def recieve_data_from_server(rm_reader, logHint=None, user=None):
    if user:
        sBucket = sBucketdict[user]
    try:
        while True:
            data = await aioRead(rm_reader, ReadMode.MAX, maxLen=65535, logHint='', bucket=sBucket)
    except MyError as exc:
        log.info(f'{logHint} {exc}')

async def send_data_to_client(cl_writer, user=None):
    if user:
        sBucket = sBucketdict[user]

    while True:
        start = time()
        if sBucket.status:
            dps = sBucket.write(args.lim)
            await aioWrite(cl_writer, dps, logHint='')
        await asyncio.sleep(1 - (time() - start))

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
            async with db.execute('SELECT * FROM USER WHERE USERNAME=? and PASSWORD=?', (username, password, ) ) as cur:
                async for row in cur:
                    current_throughput = row[2]
                if current_throughput >= int(args.lim):
                    print("server is too busy, please try to connect again after a while")
                    return
                version = await aioRead(reader, ReadMode.EXACT, exactLen=1, logHint=f'1stByte', user = username)
                if b'\x05' == version:
                    proxyType = 'SOCKS5'
                    numMethods = await aioRead(reader, ReadMode.EXACT, exactLen=1, logHint='nMethod',user =username)
                    await aioRead(reader, ReadMode.EXACT, exactLen=numMethods[0], logHint='methods', user = username)
                    await aioWrite(writer, b'\x05\x00', logHint='method.noAuth')
                    await aioRead(reader, ReadMode.EXACT, exactData=b'\x05\x01\x00', logHint='verCmdRsv', user = username)
                    atyp = await aioRead(reader, ReadMode.EXACT, exactLen=1, logHint='atyp', user = username)
                    dstHost = await socks5ReadDstHost(reader, atyp, logHint='dstHost')
                    dstPort = await aioRead(reader, ReadMode.EXACT, exactLen=2, logHint='dstPort', user = username)
                    dstPort = int.from_bytes(dstPort, 'big')
                    # 连接远程代理服务器

                    rm_reader, rm_writer = await asyncio.open_connection(dstHost, dstPort)
                    bindHost, bindPort, *_ = rm_writer.get_extra_info('sockname')

                    atyp, hostData = socks5EncodeBindHost(bindHost)
                    data = struct.pack(f'!ssss{len(hostData)}sH', b'\x05', b'\x00', b'\x00', atyp, hostData, int(bindPort))
                    await aioWrite(writer, data, logHint='reply')

                else:
                    proxyType = 'HTTP TUNNEL'
                    line = await aioRead(reader, ReadMode.LINE, logHint='Connection Request Header', user = username)
                    line = version + line
                    req_headers = await aioRead(reader, ReadMode.UNTIL, untilSep=b'\r\n\r\n',
                                                logHint='Request Header', user = username)
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
                        asyncio.create_task(recieve_data_from_local(reader, user=username)),
                        asyncio.create_task(send_data_to_server(rm_writer,user=username)),
                        asyncio.create_task(recieve_data_from_server(rm_reader, user=username)),
                        asyncio.create_task(send_data_to_client(writer, user=username))
                    })


async def remoteTask(port): #启动远程代理服务器
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
        :param is_lock:
        '''
        self.owner = username
        self._capacity = float(capacity)
        self._used_tokens = 0
        self._leak_rate = leak_rate
        self._last_time = 0
        self._lock = RLock()
        self._data = str()
        self.status = False

    #要更新现在桶的数据量
    def input(self, data):
        data = data.decode()
        newdatalen = len(data)
        self._lock.acquire()
        if len(self._data) + newdatalen < self._capacity:
            self._data = self._data + str(data)
        else:
            self._data = self._data + str(data)[:self._capacity - len(self._data)]
            print("data overflow out of the bucket {}" % str(data)[self._capacity - len(self._data):])
        self._last_time = time()
        self.status = True
        self._lock.release()

    def write(self, lens):
        self._lock.acquire()
        output = self._data[:lens] if (len(self._data) >= lens) else self._data
        self._data = self._data[lens:] if (len(self._data) >= lens) else str()
        if len(self._data) == 0:
            self.status = False
        self._lock.release()
        return output.encode()


def init_database():
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute('''DROP TABLE IF EXISTS USER ;''')
    c.execute('''CREATE TABLE USER
               (USERNAME           TEXT    NOT NULL,
               PASSWORD           TEXT      ,
               BANDWIDTH        DOUBLE      );''')
    print("Table created successfully")

    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u1', '11', 0);''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u2', '22', 0);''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u3', '33', 0);''')

    # 为每个用户创建俩个桶，一个向服务器发送请求，控制发送方的流量，另一个接受来自服务器的响应，控制服务器下行流量，用来缓存数据
    for user in ['u1', 'u2', 'u3']:
        uBucketdict[user] = leakyBucket(user, args.cap, args.lim)
        sBucketdict[user] = leakyBucket(user, args.cap, args.lim)

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

    _parser = argparse.ArgumentParser(description='add traffic control')
    _parser.add_argument('--limit', dest='lim', metavar='lim', default='1500000', help='the limit of the web ')# default = 150KB/s 就是桶每秒流出的数据量
    _parser.add_argument('--capacity', dest='cap', metavar='cap', default = '10000000', help='the capacity of the bucket')

    args = _parser.parse_args()
    asyncio.run(main())