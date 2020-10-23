'''
    @author linln1
    @copyright(C) 2020
'''

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
    version, nmethods = struct.unpack("!BB", data)
    # assert version == socks5_version
    # assert nmethods > 0
    # 读入方法
    methods = []
    for i in range(nmethods):
        data = await reader.read(1)
        methods.append(ord(data))

    if 0 not in set(methods):
        return

    # step2
    data = struct.pack("!BB", socks5_version, 0x00)
    writer.write(data)
    await writer.drain()

    # step3
    # data = await reader.read(2)
    # subprotocol, status = struct.unpack("!BB", data)

    # step4
    data = await reader.read(4)
    version, cmd, _, protocol_type = struct.unpack("!BBBB", data)

    if protocol_type == 1:  # IPv4
        data = await reader.read(4)
        address = socket.inet_ntoa(data)
    elif protocol_type == 3:  # domain name
        data = await reader.read(1)
        address = await reader.read(data[0])
    elif protocol_type == 4:  # IPv6
        data = await reader.read(16)
        address = socket.inet_ntop(socket.AF_INET6, data)
    else:
        writer.close()
        return
    data = await reader.read(2)
    port = struct.unpack("!H", data)[0]
    print(address, port)


    # step5
    try:
        if cmd == 1:
            # 作为一个客户端，向remote_server发起连接
            remote_reader, remote_writer = await asyncio.open_connection(address, port)
            # print('Connect to {} {} successfully'.format(address, port))
        else:
            print('Do not support this service now')
            await writer.close()
        data = struct.pack("!BBBBIH", socks5_version, 0, 0, 1, 0, 0)
    except Exception as err:
        logging.error(err)
        data = struct.pack("!BBBBIH", socks5_version, 5, 0, protocol_type, 0, 0)
    writer.write(data)
    await writer.drain()

    # step6
    if cmd == 1 and data[1] == 0:
        info = await reader.read(100)
        remote_writer.write(info)
        await remote_writer.drain()

        reply = await remote_reader.read(100)
        writer.write(reply)
        await writer.drain()
        # task = asyncio.gather(
        #     transfer_client_server(reader, remote_writer),
        #     transfer_server_client(remote_reader, writer),
        # )

        # print("transfering data")
        # task = [transfer_client_server(reader, remote_writer), transfer_server_client(remote_reader, writer)]
        # await asyncio.wait(task)
        # loop = asyncio.get_event_loop()
        # loop.run_forever(task)

# async def transfer_client_server(reader, remote_writer):
#     # 从客户端接收信息,并且发给远程服务器
#     info = await reader.read(2048)
#     remote_writer.write(info)
#     await remote_writer.drain()
#
# async def transfer_server_client(remote_reader, writer):
#     # 从远程服务器收到回答，转回客户端
#     reply = await remote_reader.read(4096)
#     writer.write(reply)
#     await writer.drain()

async def main():
    server = await asyncio.start_server(run, '127.0.0.1', 8888)
    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()


asyncio.run(main())
