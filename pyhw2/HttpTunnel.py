import logging
import asyncio
import argparse
import socket, time
import sys
import struct
import urllib
import telnetlib
import uuid
import http.client

logging.basicConfig(level=logging.DEBUG)
BUFFER = 1024 * 4

local_port = 1234
local_addr = '127.0.0.1'
remote_addr = '' # a ip_addr outside the firewall

#tunnel 监听的 所有客户端组成clients,放入clients里面
clients = []


## 从client 获取请求，然后发向target端
async def send(http_conn, client_sock, id):
    data = client_sock.recv(BUFFER) #接受要转发的报文内容
    try:
        if data == '':
            await http_conn.close()
            print('Client\'s socket connection broken')
            return
        print("Sending data...%s" % data)
        #真正发送数据给target
        params = urllib.urlencode({"data": data})
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/plain"}
        try:
            http_conn.request("PUT", "http://{host}:{port}{url}".format(host=target_addr['host'],port=target_addr['port'], url="/"+id), params, headers)
            response = http_conn.getresponse()
            response.read()
            print
            response.status
        except (http.client.HTTPResponse, socket.error) as ex:
            print
            "Error Sending Data: %s" % ex
    except socket.timeout:
        print('Sending timeout...')


#从target端获取响应， 然后返回给client端
async def recieve(http_conn, data, id):
    try:
        http_conn.request("GET", "http://{host}:{port}{url}".format(host=remote_addr['host'],port=remote_addr['port'], url="/"+id))
        response = http_conn.getresponse()
        data = response.read()
        if response.status == 200:
            return data
        else:
            return None
    except (http.client.HTTPResponse, socket.error) as ex:
        print("Error Receiving Data: %s" % ex)
        return None


async def start_proxy(c_sock, proxy_addr, target_addr, remote_addr):
    server = await asyncio.start_server(proxy_addr)
    print("{}", server.getsockbyname())
    id = uuid.uuid4()

    data = c_sock.recv(BUFFER) #请求头的大小


    #{"data" : data}
    params = urllib.urlencode({"host": target_addr['host'], "port": target_addr['port']}) # 将host 和 port 翻译成参数
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/plain"}


    conn_dest = proxy_addr if proxy_addr else remote_addr
    print("Establishing connection with remote tunneld at %s:%s" % (conn_dest['host'], conn_dest['port']))
    http_conn = http.client.HTTPConnection(conn_dest['host'], conn_dest['port'])

    http_conn.request("POST", "http://{host}:{port}{url}".format(host=target_addr['host'],port=target_addr['port'], url="/"+id), params, headers)

    response = await http_conn.getresponse()
    response.read()
    status = response.status
    if status==200:
        print("Successfully create connection")
    else:
        print("Failure to establish connection: status %s because %s" %(response.status, response.reason))

    #将剩余的内容转发给远端
    tasks = [send(http_conn, c_sock, id), recieve(http_conn, c_sock, id)]
    await asyncio.run(tasks)

    print("Closing... connection to target at tuunel")
    http_conn.request("DELETE",  "http://{host}:{port}{url}".format(host=remote_addr['host'],port=remote_addr['port'], url="/"+id))
    await http_conn.getresponse()
    print("Closed")

    return http_conn

async def start_tunnel(listen_port, target_addr, remote_addr, proxy_addr):
    #监听的数量
    listen_num = 5
    '''start tunnel'''
    listen_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listen_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listen_sock.settimeout(None)
    listen_sock.bind(('', int(listen_port))) ## 监听的本地客户端的端口
    listen_sock.listen(listen_num)
    print("waiting for connection")

    try:
        while True:
            c_sock, addr = listen_sock.accept()
            c_sock.settimeout(20)
            print("connected by ", addr)
            client = start_proxy(c_sock, proxy_addr, target_addr, remote_addr)     #client 是一个tuple (reader, writer)
            clients.append(client)  #clietns 里面包含了多个 client tuple
    except (KeyboardInterrupt, SystemExit):
        listen_sock.close()
        for w in clients:
            c_reader = w[0]
            c_writer = w[1]
            await c_reader.close()
            await c_writer.close()
        for w in clients:
            w.join()
        sys.exit()

##                                           channel
## client  ->  tunnel client at localhost   <=======>   (tunnel server at proxy)  <->  remote server

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description = "Http tunnel")
    parser.add_argument('port', default = 8888, dest = 'listen_port', help = 'The port of tunnel listened to, defalut(8888) ', type = int)
    parser.add_argument('target', metavar = 'Target Address', help = 'the host:port of the target')
    parser.add_argument('remote', default = 'localhost:8888', help = 'the host:port of the http tunnel to the remote')
    parser.add_argument('proxy', default='localhost:1080', dest='proxy', help='the host:port of the proxy')

    args = parser.parse_args()

    listen_port = args.port
    target_addr = {"host":args.target[:].split(":")[0], "port":args.target[:].split(":")[1]}
    remote_addr = {"host":args.remote[:].split(":")[0], "port":args.remote[:].split(":")[1]}
    proxy_addr = {"host":args.proxy[:].split(":")[0], "port":args.proxy[:].split(":")[1]} if (args.proxy) else {}

    start_tunnel(listen_port, target_addr, remote_addr, proxy_addr)

## proxy_addr 和 remote_addr 的功能是一样的，如果proxy_addr为空，那么remote_addr就是远程的proxy代理
# async def start_client(client_socket, remote_addr, target_addr, proxy_addr):
#     #reader, writer = asyncio.start_server(local_addr, local_port)
#     if not proxy_addr:
#         proxy_addr = remote_addr
#     ## 这里不用open_connection 来建立连接，而是换了使用http.client.HTTPConnection来建立
#     http_to_proxy = http.client.HTTPConnection(proxy_addr['host'], proxy_addr['port'])
#
#     #想要请求的地址和端口
#     params = urllib.urlencode({"host": target_addr['host'], "port": target_addr['port']})
#     urllib.urlencode({"host": target_addr['host'], "port": target_addr['port']})
#
#     http_to_proxy.request("POST", "http://{host}:{port}{url}".format(host=remote_addr['host'],port=remote_addr['port'], url="/"+id))
#     # 链接到proxy代理上面去
#
#     response_from_proxy = http_to_proxy.getresponse()
#     response_from_proxy.read()
#     if response_from_proxy.status == 200:
#         print('Successfully create connection')
#         return True
#     else:
#         print("Fail to establish connection: status %s because %s " %(response_from_proxy.status, response_from_proxy.reason))
#         return False
#
#