# '''
#     @author linln1
#     @copyright(C) 2020
# '''
#
# import asyncio
# import struct
#
# async def client(message):
#     reader, writer = await asyncio.open_connection('127.0.0.1', 1080)
#     print(f'Send: {message!r}')
#
#     data = struct.pack("!BBB",0x5,0x1,0x0)
#     writer.write(data)
#     await writer.drain()
#
#     data = await reader.read(2)
#     version, status = struct.unpack("!BB", data)
#     assert version == 5
#     assert status == 0
#
#     data = struct.pack("!BB", 0x1, 0x0)
#     writer.write(data)
#     await writer.drain()
#
#
#     data = struct.pack("!BBBB", 0x5, 0x1, 0x0, 0x1)
#     writer.write(data)
#     await writer.drain()
#     # remote address
#     data = struct.pack("!BBBB", 0x7f, 0x0, 0x0, 0x1)
#     writer.write(data)
#     await writer.drain()
#
#     # remote port
#     data =struct.pack("!BB", 0x04, 0x38)
#     writer.write(data)
#     await writer.drain()
#
#
#     writer.write(message.encode())
#     await writer.drain()
#
#     data = await reader.read()
#     print(f'Received: {data!r}')
#
#     print('Close the connection')
#     writer.close()
#
#
# async def main():
#     await asyncio.gather(
#         client('20201021'),
#     # client('@author linln1'),
#     # client('Hello world'),
#     )
#
#
# if __name__ == '__main__':
#     asyncio.run(main())

'''
    @author linln1
    @copyright(C) 2020
'''

import logging
import asyncio
import struct
import socket

local_addr = '127.0.0.1'
local_port = 1080
socks5_version = 5

logging.basicConfig(level=logging.DEBUG)


async def transfer_client_server(reader, remote_writer):
    flag = True
    while True:
    # 从客户端接收信息,并且发给远程服务器
        info = await reader.read(4096)
        if len(info) != 4096:
            flag = False
        remote_writer.write(info)
        await remote_writer.drain()

async def transfer_server_client(remote_reader, writer):
    flag = True
    while True:
    # 从远程服务器收到回答，转回客户端
        reply = await remote_reader.read(4096)
        if len(reply) != 4096:
            flag = False
        writer.write(reply)
        await writer.drain()


async def run(reader, writer):
    # step1
    data = await reader.read(2)
    version, nmethods = struct.unpack("!BB", data)

    # assert version == socks5_versiontim
    # assert nmethods > 0
    # 读入方法
    methods = []
    for i in range(nmethods):
        data = await reader.read(1)
        methods.append(ord(data))

    if 0 not in set(methods):
        print("do not support NO AUTHENTICATION REQUIRED METHOD!")

    # step2
    data = struct.pack("!BB", version, 0x00)
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
        length = data[0]
        address = await reader.read(length)
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
            await writer.close()
        data = struct.pack("!BBBBIH", socks5_version, 0x00, 0x00, 1, 0, 0)
    except Exception as err:
        logging.error(err)
        data = struct.pack("!BBBBIH", socks5_version, 0x5, 0x0, protocol_type, 0x0, 0x0)
    writer.write(data)
    await writer.drain()

    # step6
    if cmd == 1 and data[1] == 0:
        # task = asyncio.gather(
        #     transfer_client_server(reader, remote_writer),
        #     transfer_server_client(remote_reader, writer),
        # )
        print("transfering data")
        tasks = [transfer_client_server(reader, remote_writer), transfer_server_client(remote_reader, writer)]
        await asyncio.wait(tasks)
        # loop = asyncio.get_event_loop()
        # loop.run_forever(task)


async def main():
    server = await asyncio.start_server(run, '127.0.0.1', 1080)
    addr = server.sockets[0].getsockname()
    print(f'Serving on {addr}')

    async with server:
        await server.serve_forever()


if __name__ == '__main__':
    asyncio.run(main())