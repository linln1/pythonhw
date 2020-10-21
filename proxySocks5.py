import logging
import asyncio
import struct
import socket

local_addr = '127.0.0.1'
local_port = 8888
socks5_version = 5

logging.basicConfig(level=logging.DEBUG)


async def run(reader, writer):
    # step1
    data = await reader.read(2)
    print("the decode of data is {}".format(data))
    version, nmethods = struct.unpack("!BB", data)
    assert version == socks5_version
    assert nmethods > 0

    # 读入方法
    methods = []
    for i in range(nmethods):
        data = await reader.read(1)
        methods.append(struct.unpack("!B", data)[0])
    if 0x00 not in set(methods):
        print("do not support NO AUTHENTICATION REQUIRED METHOD!")

    # step2
    data = struct.pack("!BB", version, 0x00)
    writer.write(data)
    await writer.drain()

    # step3
    await asyncio.sleep(1)
    data = await reader.read(2)
    subprotocol, status = struct.unpack("!BB", data)
    assert status == 0

    # step4
    data = await reader.read(4)
    version, cmd, _, protocol_type = struct.unpack("!BBBB", data)
    assert version == socks5_version

    if protocol_type == 1:  # IPv4
        data = await reader.read(4)
        address = socket.inet_ntoa(data)
    elif protocol_type == 3:  # domain name
        data = await reader.read(1)
        length = data[0]
        address = reader.read(length).decode()
    elif protocol_type == 4:  # IPv6
        data = await reader.read(16)
        address = socket.inet_ntop(socket.AF_INET6, data)
    else:
        return
    data = await reader.read(2)
    port = struct.unpack("!H", data)[0]
    print(address, port)


    # step5
    try:
        if cmd == 1:
            # 作为一个客户端，向remote_server发起连接
            remote_reader, remote_writer = await asyncio.open_connection(address, port)
            print('Connect to {} {} successfully'.format(address, port))
        else:
            print('Do not support this service now')
            await writer.close()
        print("connect to remote Server {} {}".format(address, port))
        data = struct.pack("!BBBBIH", socks5_version, 0, 0, protocol_type, address, port)
    except Exception as err:
        logging.error(err)
        data = struct.pack("!BBBBIH", socks5_version, 5, 0, protocol_type, 0, 0)
    writer.write(data)
    await writer.drain()

    # step6
    if data[0] == 0 and cmd == 1:
        # 从客户端接收信息,并且发给远程服务器
        info = await reader.read()
        remote_writer.write(info)
        await remote_writer.drain()
        # 从远程服务器收到回答，转回客户端
        reply = await remote_reader.read()
        writer.write(reply)
        await writer.drain()


async def main():
    server = await asyncio.start_server(run, '10.28.255.3', 8888)
    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())