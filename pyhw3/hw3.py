import argparse
import asyncio
import ipaddress
import logging
import signal
import socket
import struct
import sys
import traceback

from enum import Enum
from urllib.parse import urlparse, urlunparse

from anaconda_project.requirements_registry.network_util import urlparse

ReadMode = Enum('ReadMod', ('EXACT', 'LINE', 'MAX', 'UNTIL'))

remoteProxyHost = '127.0.0.1'
remoteProxyPort = 8889

class MyError(Exception):
    pass

def logExc(exc):
    if args.logExc:
        log.error(f'{traceback.format_exc()}')

async def aioClose(w):
    try:
        if w:
            w.close()
            await w.wait_closed()
    except Exception as exc:
        logExc(exc)

async def aioRead(r, mode, *, errHint=None, exactData=None, exactLen=None, maxLen=-1, utilSep=b'\r\n'):
    data = None
    try:
        if ReadMode.EXACT == mode:
            exactLen = len(exactData) if exactData else exactLen
            data = await r.readexactly(exactLen)
            if exactData and data != exactData:
                raise MyError(f'Error {errHint}={data} correct={exactData}')
            return data
        elif ReadMode.LINE == mode:
            data = await r.readline()
            return data
        elif ReadMode.MAX == mode:
            data = await r.read(maxLen)
            return data
        elif ReadMode.UNTIL == mode:
            data = await r.readuntil(utilSep)
            return data
        else:
            raise MyError(f'Error mode={mode}')
    except Exception as exc:
        logExc(exc)
        raise exc

async def aioWrite(w, data, *, errHint=None):
    try:
        w.write(data)
        await w.drain()
    except Exception as exc:
        logExc(exc)
        raise MyError(f'Exc={errHint}')

async def socks5ReadDstHost(r, atyp):
    dstHost = None
    if atyp == b'\x01':
        dstHost = await aioRead(r, ReadMode.EXACT, exactLen=4, errHint='ipv4')
        dstHost = str(ipaddress.ip_address(dstHost))
    elif atyp == b'\x03':
        dataLen = await aioRead(r, ReadMode.EXACT, exactLen=1, errHint='fqdnLen')
        dataLen = dataLen[0]
        dstHost = await aioRead(r, ReadMode.EXACT, exactLen=dataLen, errHint='fqdn')
        dstHost = dstHost.decode('utf8')
    elif atyp == b'\x04':
        dstHost = await aioRead(r, ReadMode.EXACT, exactLen=16, errHint='ipv6')
        dstHost = str(ipaddress.ip_address(dstHost))
    else:
        raise MyError(f'Error atyp={atyp}')
    return dstHost

async def socks5EncodeBindHost(bindHost):
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

async def socks_conn_init(clientR, clientW):
    try:
        await aioRead(clientR, ReadMode.EXACT, exactData=b'\x05', errHint='methods.ver')
        numMethods = await aioRead(clientR, ReadMode.EXACT, exactLen=1)
        await aioRead(clientR, ReadMode.EXACT, exactLen=numMethods[0])
        await aioWrite(clientW, b'\x05\x00', errHint='method.noAuth')

        await aioRead(clientR, ReadMode.EXACT, exactData=b'\x05', errHint='request.ver')
        await aioRead(clientR, ReadMode.EXACT, exactData=b'\x01', errHint='request.cmd')
        await aioRead(clientR, ReadMode.EXACT, exactData=b'\x00', errHint='request.rsv')
        atyp = await aioRead(clientR, ReadMode.EXACT, exactLen=1, errHint='request.atyp')
        dstHost = await socks5ReadDstHost(clientR, atyp)
        dstPort = await aioRead(clientR, ReadMode.EXACT, exactLen=2, errHint='request.dstPort')
        dstPort = int.from_bytes(dstPort, 'big')
        log.info(f'Receive dst={dstHost} port={dstPort}')

        return atyp, dstHost, dstPort
    except Exception as exc:
        logExc(exc)

async def socks5_run(clientR, clientW):
    _, dstHost, dstPort = await socks_conn_init(clientR, clientW)
    serverR, serverW = await asyncio.open_connection(dstHost, dstPort)
    bindHost, bindPort, *_ = serverW.get_extra_info('sockname')
    log.info(f'Connect bind={bindHost} port={bindPort}')

    atyp, hostData = socks5EncodeBindHost(bindHost)
    data = struct.pack(f'!ssss{len(hostData)}sH', b'\x05', b'\x00', b'\x00', atyp, hostData, int(bindPort))
    await aioWrite(clientW, data)

    tasks = [ transfer_client_server(clientR, serverW), transfer_server_client(serverR, clientW)]
    await asyncio.wait(tasks)
# tasks = [transfer_server_client(rm_reader, client_writer), transfer_client_server(client_reader, rm_writer)]
async def transfer_client_server(reader, remote_writer, logHint=None):
    try:
        while True:
        # 从客户端接收信息,并且发给远程服务器
            info = await aioRead(reader, ReadMode.MAX, exactLen=65535, errHint='65535')
            remote_writer.write(info)
            await remote_writer.drain()
    except MyError as exc:
        log.info(f'{logHint} {exc}')

    await aioClose(remote_writer, logHint)
    await aioClose(reader, logHint)

async def transfer_server_client(remote_reader, writer, logHint=None):
    try:
        while True:
        # 从远程服务器收到回答，转回客户端
            reply = await aioRead(remote_reader, ReadMode.MAX, maxLen=65535, errHint='65535')
            # reply = await remote_reader.read(4096)
            writer.write(reply)
            await writer.drain()
    except MyError as exc:
        log.info(f'{logHint} {exc}')

    await aioClose(writer, logHint)
    await aioClose(remote_reader, logHint)

async def parse_header(raw_headers):
    request_lines = raw_headers.split('\r\n')
    first_line = request_lines[0].split(' ')
    method = first_line[0]
    full_path = first_line[1]
    version = first_line[2]
    #print("%s %s" % (method, full_path))
    (scm, netloc, path, params, query, fragment) = urlparse.urlparse(full_path, 'http')
    # 如果url中有':'就指定端口，没有则为默认80端口
    i = netloc.find(':')
    address = netloc, 80
    if i >= 0:
        address = netloc[:i], int(netloc[i + 1:])

    return method, version, scm, address, path, params, query, fragment

async def get_header(reader):
    '''
    取出不含\r\n的header 的部分
    :param reader:
    :return:
    '''
    headers = ""
    while True:
        line = await aioRead(reader, ReadMode.LINE)
        line = str(line, "utf-8")
        #print(line)
        if line == '':
            return headers
        elif line == '\r\n' :
            return headers
        else:
            headers += line

    return headers

async def remote_proxy(reader, writer):
    address = await aioRead(reader, ReadMode.LINE, logHint='methods')#address 的长度
    host_port = address.decode().split('\r\n')
    host = host_port.split(":")[0]
    port = host_port.split(":")[1]
    try:
        rm_reader, rm_writer = await asyncio.open_connection(host, port)
        reply = "HTTP/1.1 200 OK\r\n"
        await aioWrite(writer, reply)
    except Exception as Err:
        logExc(Err)
        reply = "HTTP/1.1" + str(Err) + " Fail\r\n\r\n"
        await aioWrite(writer, reply.encode())

    tasks = [transfer_server_client(reader, rm_writer), transfer_client_server(rm_reader, writer)]
    await asyncio.wait(tasks)

async def tunnel_run(client_reader, client_writer):
    try:
        req_headers = await get_header(client_reader)
        method, version, scm, address, path, params, query, fragment = await parse_header(req_headers)

        path = urlunparse(("", "", path, params, query, ""))
        req_headers = " ".join([method, path, version]) + "\r\n" + "\r\n".join(req_headers.split('\r\n')[1:])
        print(address)
        i = path.find(':')
        host = ''
        port = 0
        if i >= 0:
            host, port = path[:i], int(path[i + 1:])
        else:
            host = path
            port = 80

        if args.proto == 'http tunnel':
            remoteProxyHost = host
            remoteProxyPort = port

        try:
            rm_reader, rm_writer = await asyncio.open_connection(remoteProxyHost, remoteProxyPort)
            # reply = "HTTP/1.1 200 OK\r\n\r\n"
            # client_writer.write(reply.encode())
            # await client_writer.drain()
            reply = "Connection with remote Proxy OK\r\n"
            client_writer.write(reply)
            await client_writer.drain()
            address += '\r\n'
            rm_writer.write(address.encode())
            await rm_writer.drain()
        except Exception as exc:
            logExc(exc)
            reply = "HTTP/1.1" + str(exc) + " Fail\r\n\r\n"
            await aioWrite(client_writer, reply.encode())

        # 把HTTP头中连接设置为中断
        # 如果不想让火狐卡在那里不继续加载的话
        # if req_headers.find('Connection') >= 0:
        #     req_headers = req_headers.replace('keep-alive', 'close')
        # else:
        #     req_headers += req_headers + 'Connection: close\r\n'
        # 发送形如`GET path/params/query HTTP/1.1`
        # 结束HTTP头
        # req_headers += '\r\n'
        # await aioWrite(rm_writer, req_headers.encode())

        tasks = [transfer_server_client(rm_reader, client_writer), transfer_client_server(client_reader, rm_writer)]
        await asyncio.wait(tasks)
    except Exception as exc:
        logExc(exc)

async def localTask():
    if args.proto == 'socks5':
        socks5_srv = await asyncio.start_server(socks5_run, host=args.listenHost, port=args.listenPort)
        socks5_addrList = list([s.getsockname() for s in socks5_srv.sockets])
        log.info(f'Listen {socks5_addrList} and use socks5 protocol')
        async with socks5_srv:
            await socks5_srv.serve_forever()


    elif args.proto == 'http tunnel':
        tunnel_srv = await asyncio.start_server(tunnel_run, host=args.listenHost, port=args.listenPort)
        tunnel_addrList = list([t.getsockname() for t in tunnel_srv.sockets])
        log.info(f'Listen {tunnel_addrList} and use http_tunnel protocol')
        async with tunnel_srv:
            await tunnel_srv.serve_forever()

    elif args.proto == 'multi level proxy':
        local_srv = await asyncio.start_server(tunnel_run, host=args.listenHost, port=args.listenPort)
        tunnel_addrList = list([t.getsockname() for t in local_srv.sockets])
        remote_srv = await asyncio.start_server(remote_proxy, host=remoteProxyHost,port=remoteProxyPort)
        log.info(f'Listen {tunnel_addrList} and use two level proxy')
        async with local_srv and remote_srv:
            await local_srv.serve_forever()
            await remote_srv.serve_forever()

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

    _parser = argparse.ArgumentParser(description='server')
    _parser.add_argument('--protocol', dest='proto', default='http tunnel', action='store_true', help='choose protocol : socks5 / http_tunnel')

    _parser.add_argument('--exc', dest='logExc', default=False, action='store_true', help='show exception traceback')
    _parser.add_argument('--host', dest='listenHost', default='127.0.0.1', metavar='listen_host', help='proxy listen host default listen all interfaces')
    _parser.add_argument('--port', dest='listenPort', default=8888, metavar='listen_port', help='proxy listen port')


    args = _parser.parse_args()

    # if sys.platform == 'win32':
    #     asyncio.set_event_loop(asyncio.ProactorEventLoop())

    asyncio.run(main())