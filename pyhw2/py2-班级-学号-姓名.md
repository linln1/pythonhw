# Python程序设计#2作业

截止时间：2020年11月02日23:59:59

## 作业题目

实现localProxy双协议（SOCKS5和HTTP tunnel）本地代理。

支持（SOCKS5代理）基于#1作业的成果。

支持HTTP tunnel（ 即HTTP CONNECT method）可用于HTTPS代理。

关于HTTP tunnel可以参见：https://www.zhihu.com/question/21955083

## 作业内容

程序源代码嵌入下方的code block中。

```python
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
import urllib.parse

ReadMode = Enum('ReadMod', ('EXACT', 'LINE', 'MAX', 'UNTIL'))

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
    ...

async def socks5EncodeBindHost(bindHost):
    ...

async def socks_conn_init(clientR, clientW):
    ...

async def socks5_run(clientR, clientW):
    ...

async def transfer_client_server(reader, remote_writer):
    try:
        while True:
        # 从客户端接收信息,并且发给远程服务器
            info = await aioRead(reader, ReadMode.MAX, maxLen=65535, errHint='65535')
            await aioWrite(remote_writer, info)
    except Exception as exc:
        logExc(exc)

    await aioClose(remote_writer)
    await aioClose(reader)

async def transfer_server_client(remote_reader, writer):
    try:
        while True:
        # 从远程服务器收到回答，转回客户端
            reply = await aioRead(remote_reader, ReadMode.MAX, maxLen=65535, errHint='65535')
            await aioWrite(writer, reply)
    except Exception as exc:
        logExc(exc)

    await aioClose(writer)
    await aioClose(remote_reader)

async def parse_header(raw_headers):
    request_lines = raw_headers.split('\r\n')
    first_line = request_lines[0].split(' ')
    method = first_line[0]
    full_path = first_line[1]
    version = first_line[2]
    print("%s %s" % (method, full_path))
    (scm, netloc, path, params, query, fragment) = urllib.urlparse(full_path, 'http')
    # 如果url中有':'就指定端口，没有则为默认80端口
    i = netloc.find(':')
    if i >= 0:
        address = netloc[:i], int(netloc[i + 1:])
    else:
        address = netloc, 80
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
        if line is None:
            break
        elif line == '\r\n':
            break
        else:
            headers += line

    return headers

async def tunnel_run(client_reader, client_writer):
    try:
        req_headers = await get_header(client_reader)
        method, version, scm, address, path, params, query, fragment = await parse_header(req_headers)

        path = urllib.urlunparse(("", "", path, params, query, ""))
        req_headers = " ".join([method, path, version]) + "\r\n" + "\r\n".join(req_headers.split('\r\n')[1:])

        # 连接URL指定的机器
        # 数据转发
        try:
            rm_reader, rm_writer = asyncio.open_connection(str(address[0]), str(address[1]))
        except Exception as exc:
            logExc(exc)
            reply = "HTTP/1.1" + str(exc) + " Fail\r\n\r\n"
            aioWrite(client_writer, reply)
        else:  # 若连接成功
            reply = "HTTP/1.1 200 Connection Established\r\n"
            aioWrite(client_writer, reply)

        # 把HTTP头中连接设置为中断
        # 如果不想让火狐卡在那里不继续加载的话
        if req_headers.find('Connection') >= 0:
            req_headers = req_headers.replace('keep-alive', 'close')
        else:
            req_headers += req_headers + 'Connection: close\r\n'
        # 发送形如`GET path/params/query HTTP/1.1`
        # 结束HTTP头
        req_headers += '\r\n'
        aioWrite(rm_writer, req_headers)

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
```

## 代码说明（可选）

源代码中不要出现大段的说明注释，如果需要可以可以在本节中加上说明。