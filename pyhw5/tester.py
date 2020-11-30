
import time
import struct
import asyncio
import socket
import aiosqlite
import sqlite3
SOCKS_VERSION = 5

# 对token_list的访问需加锁
global lock_token_list_remote_socks5
global token_list_remote_socks5
global lock_token_list_remote_http
global token_list_remote_http


class TokenBucket(object):
    # 一个令牌 -> 1byte数据
    # rate是令牌发放速度（个/s）（相当于byte/s），capacity是桶的大小（设为rate x1），socket_account是连接从属于的账户
    def __init__(self, socket_account, rate):
        self._account = socket_account
        self._rate = rate
        self._capacity = rate * 1
        self._current_amount = 0
        self._last_consume_time = time.time()  # 单位是s
        self._lock = asyncio.Lock()

    def getRate(self):
        return self._rate

    def getAccount(self):
        return self._account

    # token_size_byte是发送数据的大小（byte），token_amount是发送数据需要的令牌数
    async def output(self, token_size_byte):
        #print("output", self._account, self._rate)
        async with self._lock:
            token_amount = token_size_byte
            increment = (time.time() - self._last_consume_time) * self._rate  # 计算从上次发送到这次发送，新发放的令牌数量
            self._current_amount = min(increment + self._current_amount, self._capacity)  # 令牌数量不能超过桶的容量
            if token_amount > self._current_amount:  # 如果没有足够的令牌，则阻塞一段时间，直到有足够的令牌
                timeval = (token_amount - self._current_amount) / self._rate
                #print("sleep for ", timeval)
                await asyncio.sleep(timeval)
                self._last_consume_time = time.time()
                self._current_amount = 0
                #print(self._current_amount)
                return
            self._last_consume_time = time.time()
            self._current_amount -= token_amount
            #print(self._current_amount)
            return
def init_db():
    conn = sqlite3.connect('cache.db')
    c = conn.cursor()
    c.execute('''DROP TABLE IF EXISTS USER ;''')
    c.execute('''CREATE TABLE USER
                   (USERNAME           TEXT    NOT NULL,
                   PASSWORD           TEXT      ,
                   BANDWIDTH        DOUBLE      );''')
    print("Table created successfully")

    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u1', '11', 10000);''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u2', '22', 200000);''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u3', '33', 3000000);''')

    # # 为每个用户创建俩个桶，一个向服务器发送请求，控制发送方的流量，另一个接受来自服务器的响应，控制服务器下行流量，用来缓存数据
    # for user in ['u1', 'u2', 'u3']:
    #     uBucketdict[user] = leakyBucket(user, args.cap, args.lim)
    #     sBucketdict[user] = leakyBucket(user, args.cap, args.lim)

    c.execute("SELECT * FROM USER")
    for row in c:
        print("NAME = ", row[0])
        print("PASSWORD = ", row[1])
        print("BANDWIDTH = ", row[2])

    # ('127.0.0.1', 8889)
    c.execute('''CREATE TABLE INFO
                    (USERNAME           TEXT    NOT NULL,
                   PASSWORD           TEXT,
                   ADDRESS          TEXT,
                   PORT         TEXT,
                   STATUS       BOOL    NOT NULL);
                ''')

# 可能异步 加锁
async def add_token_tolist(account_verify, token_list, token_list_lock):
    rate = 0
    async with token_list_lock:
        #print("上锁")
        for index in range(len(token_list)):
            if token_list[index].getAccount() == account_verify:
                print(f"用户{account_verify} 已经在列表中了")
                return
        # 如果列表中没有找到，添加新用户
        async with aiosqlite.connect('user.db') as db:
            async with db.execute("SELECT account,band_width FROM userlist") as cursor:
                async for row in cursor:
                    if account_verify == row[0]:  # 查找成功
                        rate = row[1]
                    else:
                        rate = 0
        if rate != 0:
            new_token = TokenBucket(account_verify, rate)
            print(f"add userlist {new_token.getAccount()} bandwidth{new_token.getRate()} to list")
            token_list.append(new_token)

async def write_to_onRemote(reader, writer, account_verify, token_list):
    while True:
        buf = await reader.read(66535)
        if not buf:
            print("读不出来，推出!", writer.get_extra_info("sockname"))
            writer.close()
            await writer.wait_closed()
            break
        for i in range(len(token_list)):
            #print("exchange-------", token_list[i].getAccount())
            if token_list[i].getAccount() == account_verify:
                await token_list[i].output(len(buf))
                writer.write(buf)
                await writer.drain()
                #print("(---限流中---)向", writer.get_extra_info("sockname"), "转发", buf)
async def write_to(reader, writer):
    while True:
        buf = await reader.read(4096)
        if not buf:
            print("error exit because of read out", writer.get_extra_info("sockname"))
            writer.close()
            await writer.wait_closed()
            break
        writer.write(buf)
        await writer.drain()
        #print("向", writer.get_extra_info("sockname"), "转发", buf)
async def verify_userinfo(account_req, password_req):
    # 在数据库认证用户名和密码
    async with aiosqlite.connect('user.db') as db:
        async with db.execute("SELECT account,password FROM userlist") as cursor:
            async for row in cursor:
                if account_req == row[0] and password_req == row[1]:  # 查找成功
                    print("用户", account_req, "认证成功")
                    return True
        print("用户", account_req, "认证失败")
        return False

async def handle_http(reader, writer):

    # 客户端认证请求
    header = await reader.readuntil(b"\r\n\r\n")
    header = bytes.decode(header)
    header = (header.split("\r\n"))[0]
    header_list = header.split(' ')

    if header_list[0] == "CONNECT":  # CONNECT请求
        header = "CONNECT"
        address_dst = header_list[1].split(":")[0]
        port_dst = int(header_list[1].split(":")[1], 10)
        ver_http = header_list[2].split("\r")[0]

        if ver_http != "HTTP/1.1":  # 仅支持HTTP/1.1
            writer.close()
            await writer.wait_closed()
            return

        #print("this is a connect method")

        # 服务端建立远程连接并回应认证
        try:
            reader_remote, writer_remote = await asyncio.open_connection(address_dst, port_dst)
            bind_address = writer_remote.get_extra_info('sockname')
            print('已建立http tunnel连接：', address_dst, port_dst, bind_address)
        except Exception as exc:
            print(exc)
            writer.close()
            await writer.wait_closed()
        reply = f"{ver_http} 200 Connection Established\r\n\r\n"
        writer.write(reply.encode('UTF-8'))
        await writer.drain()

        # 开始交换数据
        print("开始交换数据")
        await asyncio.gather(
            asyncio.create_task(write_to(reader_remote, writer)),
            asyncio.create_task(write_to(reader, writer_remote))
        )
        print("Close the connection")
        writer.close()
        await writer.wait_closed()

    else:  # 检测到 不是 CONNECTION方法的操作
        print("Close the connection")
        writer.close()
        await writer.wait_closed()
async def handle_http_remote(reader, writer):
    # 数据库验证账号密码
    userinfo_req = bytes.decode(await reader.readuntil(b"\r\n\r\n"))
    account_verify = userinfo_req.split(" ")[0]
    password_verify = userinfo_req.split(" ")[1]
    if not (await verify_userinfo(account_verify, password_verify)):
        # 认证失败，断开连接
        writer.close()
        await writer.wait_closed()
        return

    # 添加用户
    global lock_token_list_remote_http
    global token_list_remote_http
    await add_token_tolist(account_verify, token_list_remote_http, lock_token_list_remote_http)

    # 客户端认证请求
    header = await reader.readuntil(b"\r\n\r\n")
    header = bytes.decode(header)
    header = (header.split("\r\n"))[0]
    header_list = header.split(' ')

    if header_list[0] == "CONNECT":  # CONNECT请求
        header = "CONNECT"
        address_dst = header_list[1].split(":")[0]
        port_dst = int(header_list[1].split(":")[1], 10)
        ver_http = header_list[2].split("\r")[0]

        if ver_http != "HTTP/1.1":  # 仅支持HTTP/1.1
            writer.close()
            await writer.wait_closed()
            return

        #print("this is a connect method")

        # 服务端建立远程连接并回应认证
        try:
            reader_remote, writer_remote = await asyncio.open_connection(address_dst, port_dst)
            bind_address = writer_remote.get_extra_info('sockname')
            print('已建立http tunnel连接：', address_dst, port_dst, bind_address)
        except Exception as exc:
            print(exc)
            writer.close()
            await writer.wait_closed()
        reply = f"{ver_http} 200 Connection Established\r\n\r\n"
        writer.write(reply.encode('UTF-8'))
        await writer.drain()

        # 开始交换数据
        await asyncio.gather(
            asyncio.create_task(write_to_onRemote(reader_remote, writer, account_verify, token_list_remote_http)),
            asyncio.create_task(write_to(reader, writer_remote))
        )
        print("Close the connection")
        writer.close()
        await writer.wait_closed()

    else:  # 检测到 不是 CONNECTION方法的操作
        print("Close the connection")
        writer.close()
        await writer.wait_closed()
async def handle_http_local(reader, writer):
    # 连接远端服务器
    reader_remote, writer_remote = await asyncio.open_connection("127.0.0.1", 2091)
    writer_remote.write(user_str.encode('UTF-8'))
    await writer.drain()

    await asyncio.gather(
        asyncio.create_task(write_to(reader_remote, writer)),
        asyncio.create_task(write_to(reader, writer_remote))
    )
    writer.close()
    await writer.wait_closed()
async def main_http_tunnel():
    server = await asyncio.start_server(handle_http, '127.0.0.1', 2080)

    addr = server.sockets[0].getsockname()
    print(f'http tunnel --- Serving on {addr}')

    async with server:
        await server.serve_forever()
async def http_tunnel_remote():
    server = await asyncio.start_server(handle_http_remote, '127.0.0.1', 2091)

    # 初始化全局变量
    global lock_token_list_remote_http
    global token_list_remote_http
    lock_token_list_remote_http = asyncio.Lock()
    token_list_remote_http = []

    addr = server.sockets[0].getsockname()
    print(f'http tunnel(remote) --- Serving on {addr}')

    async with server:
        await server.serve_forever()
async def http_tunnel_local():
    server = await asyncio.start_server(handle_http_local, '127.0.0.1', 2090)

    addr = server.sockets[0].getsockname()
    print(f'http tunnel(local) --- Serving on {addr}')

    async with server:
        await server.serve_forever()

async def handle_socks5(reader, writer):
    # 一、客户端认证请求
    header = await reader.read(2)
    VER, NMETHODS = struct.unpack("!BB", header)
    assert VER == SOCKS_VERSION, 'version error'
    # 接受支持的方法
    # 无需认证：0x00
    # assert NMETHODS > 0

    methods = []
    for i in range(NMETHODS):
        methods.append(ord(await reader.read(1)))

    if 0 not in set(methods):
        writer.close()
        await writer.wait_closed()
        return

    # 二、服务端回应认证
    # 发送协商响应数据包
    writer.write(struct.pack("!BB", SOCKS_VERSION, 0))
    await writer.drain()

    # 三、客户端连接请求(连接目的网络)
    version, cmd, _, address_type = struct.unpack("!BBBB", await reader.read(4))
    assert version == SOCKS_VERSION, 'version error'
    if address_type == 1:  # IPv4
        # 转换IPV4地址字符串（xxx.xxx.xxx.xxx）成为32位打包的二进制格式（长度为4个字节的二进制字符串）
        address = socket.inet_ntoa(await reader.read(4))
    elif address_type == 3:  # Domain
        domain_length = ord(await reader.read(1))
        address = await reader.read(domain_length)
    elif address_type == 4:
       address = socket.inet_ntoa(await reader.read(16))
       print("==============ipv6", address)
    port = struct.unpack('!H', await reader.read(2))[0]

    # 四、服务端回应连接
    # 响应，只支持CONNECT请求
    try:
        if cmd == 1:  # CONNECT
            reader_remote, writer_remote = await asyncio.open_connection(address, port)
            bind_address = writer_remote.get_extra_info('sockname')
            print('connection established：', address, port, bind_address)
        else:
            writer.close()
            await writer.wait_closed()
        addr = struct.unpack("!I", socket.inet_aton(bind_address[0]))[0]
        port = bind_address[1]
        if socket.inet_pton(socket.AF_INET6, bind_address[0]):
            address_type = 4
        else:
            address_type = 1
        reply = struct.pack("!BBBBIH", SOCKS_VERSION, 0, 0, address_type, addr, port)
    except Exception as err:
        print(err)
        # 响应拒绝连接的错误
        reply = struct.pack("!BBBBIH", SOCKS_VERSION, 5, 0, address_type, 0, 0)
    writer.write(reply)
    await writer.drain()
    if reply[1] == 0 and cmd == 1:
        await asyncio.gather(
            asyncio.create_task(write_to(reader_remote, writer)),
            asyncio.create_task(write_to(reader, writer_remote))
        )
    print("Close the connection")
    writer.close()
    await writer.wait_closed()
async def handle_socks5_local(reader, writer):
    # 一、客户端认证请求
    header = await reader.read(2)
    VER, NMETHODS = struct.unpack("!BB", header)
    assert VER == SOCKS_VERSION, 'SOCKS版本错误'

    methods = []
    for i in range(NMETHODS):
        methods.append(ord(await reader.read(1)))
    # 检查是否支持该方式，不支持则断开连接
    if 0 not in set(methods):
        writer.close()
        await writer.wait_closed()
        return

    # 二、服务端回应认证
    # 发送协商响应数据包
    writer.write(struct.pack("!BB", SOCKS_VERSION, 0))
    await writer.drain()

    # 三、连接远端服务器
    # 剩下的处理都放在远端服务器上
    reader_remote, writer_remote = await asyncio.open_connection("127.0.0.1", 1091)
    writer_remote.write(user_str.encode('UTF-8'))
    await writer.drain()

    await asyncio.gather(
        asyncio.create_task(write_to(reader_remote, writer)),
        asyncio.create_task(write_to(reader, writer_remote))
    )
    writer.close()
    await writer.wait_closed()
async def handle_socks5_remote(reader, writer):

    # 数据库验证账号密码
    userinfo_req = bytes.decode(await reader.readuntil(b"\r\n\r\n"))
    account_verify = userinfo_req.split(" ")[0]
    password_verify = userinfo_req.split(" ")[1]
    if not (await verify_userinfo(account_verify,  password_verify)):
        # 认证失败，断开连接
        writer.close()
        await writer.wait_closed()
        return

    # 添加用户
    global lock_token_list_remote_socks5
    global token_list_remote_socks5
    await add_token_tolist(account_verify, token_list_remote_socks5, lock_token_list_remote_socks5)

    # 三、客户端连接请求(连接目的网络)
    version, cmd, _, address_type = struct.unpack("!BBBB", await reader.read(4))
    assert version == SOCKS_VERSION, 'socks版本错误'
    if address_type == 1:  # IPv4
        # 转换IPV4地址字符串（xxx.xxx.xxx.xxx）成为32位打包的二进制格式（长度为4个字节的二进制字符串）
        address = socket.inet_ntoa(await reader.read(4))
    elif address_type == 3:  # Domain
        domain_length = ord(await reader.read(1))
        address = await reader.read(domain_length)
    port = struct.unpack('!H', await reader.read(2))[0]

    # 四、服务端回应连接
    # 响应，只支持CONNECT请求
    try:
        if cmd == 1:  # CONNECT
            reader_remote, writer_remote = await asyncio.open_connection(address, port)
            bind_address = writer_remote.get_extra_info('sockname')
            print('已建立socks5连接：', address, port, bind_address)
        else:
            writer.close()
            await writer.wait_closed()
        addr = struct.unpack("!I", socket.inet_aton(bind_address[0]))[0]
        port = bind_address[1]
        if socket.inet_pton(socket.AF_INET6, bind_address[0]):
            address_type = 4
        else:
            address_type = 1
        reply = struct.pack("!BBBBIH", SOCKS_VERSION, 0, 0, address_type, addr, port)
    except Exception as err:
        print(err)
        # 响应拒绝连接的错误
        reply = struct.pack("!BBBBIH", SOCKS_VERSION, 5, 0, address_type, 0, 0)
    writer.write(reply)
    await writer.drain()

    # 建立连接成功，开始交换数据
    print("开始交换数据")
    if reply[1] == 0 and cmd == 1:
        await asyncio.gather(
            asyncio.create_task(write_to_onRemote(reader_remote, writer, account_verify, token_list_remote_socks5)),
            asyncio.create_task(write_to(reader, writer_remote))
        )
    print("Close the connection")
    writer.close()
    await writer.wait_closed()

async def socks5_local():
    server = await asyncio.start_server(handle_socks5, '127.0.0.1', 8888)

    addr = server.sockets[0].getsockname()
    print(f'socks5 --- Serving on {addr}')

    async with server:
        await server.serve_forever()
async def socks5_remote():
    server = await asyncio.start_server(handle_socks5_remote, '127.0.0.1', 1091)

    # 初始化全局变量
    global lock_token_list_remote_socks5
    global token_list_remote_socks5
    lock_token_list_remote_socks5 = asyncio.Lock()
    token_list_remote_socks5 = []

    addr = server.sockets[0].getsockname()
    print(f'sock5(remote) --- Serving on {addr}')

    async with server:
        await server.serve_forever()


async def main():
    init_db()
    await asyncio.gather(
        #asyncio.create_task(main_socks5()),
        #asyncio.create_task(main_http_tunnel()),
        asyncio.create_task(socks5_local()),
        asyncio.create_task(http_tunnel_local()),
        asyncio.create_task(socks5_remote()),
        asyncio.create_task(http_tunnel_remote())
    )

# 读入的账号密码存储在user里
if __name__ == '__main__':
    print("请输入账号：")
    account = input()
    print("请输入密码：")
    password = input()
    user = (account, password)
    user_str = user[0] + " " + user[1] + " \r\n\r\n"

    asyncio.run(main())