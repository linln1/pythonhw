'''
    @author linln1
    @copyright(C) 2020
'''

import asyncio
import struct

async def client(message):
    reader, writer = await asyncio.open_connection('127.0.0.1', 1080)
    print(f'Send: {message!r}')

    data = struct.pack("!BBB",0x5,0x1,0x0)
    writer.write(data)
    await writer.drain()

    data = await reader.read(2)
    version, status = struct.unpack("!BB", data)
    assert version == 5
    assert status == 0

    data = struct.pack("!BB", 0x1, 0x0)
    writer.write(data)
    await writer.drain()


    data = struct.pack("!BBBB", 0x5, 0x1, 0x0, 0x1)
    writer.write(data)
    await writer.drain()
    # remote address
    data = struct.pack("!BBBB", 0x7f, 0x0, 0x0, 0x1)
    writer.write(data)
    await writer.drain()

    # remote port
    data =struct.pack("!BB", 0x04, 0x38)
    writer.write(data)
    await writer.drain()


    writer.write(message.encode())
    await writer.drain()

    data = await reader.read()
    print(f'Received: {data!r}')

    print('Close the connection')
    writer.close()


async def main():
    await asyncio.gather(
        client('20201021'),
    # client('@author linln1'),
    # client('Hello world'),
    )


if __name__ == '__main__':
    asyncio.run(main())
