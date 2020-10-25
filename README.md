# To record the 8 homework and the final project of course

> # ***2020/10/20 First HW***: Using asyncio  high level APIs to implements a  socks5 proxy server

## Stream APIs

- coroutine
  - asyncio.open_connection(host=None,*,loop=None,limit=None,ssl=None,family=0,proto=0,flags=0,sock=None,local_addr=None,server_hostname=None,ssl_handshake_timeout=None)
    - 创建一个网络连接，并返回一对（reader,writer）对象
    - reader和writer对象是StreamReader和StreamWriter类的实例
    - loop是可选参数
    - limit限定返回的StreamReader实例使用的缓冲区大小, default_size = 64KB
  - asyncio.start_server(client_connected_cb,host=None,port=None,*,loop=None,limit=None,family=socket.AF_UNSPEC,flags=socket.AI_PASSIVE,sock=None,backlog=100,ssl=None,reuse_address=None,reuse_port=None,ssl_handshake_timeout=None,start_serving=True)
    - 启动一个socket服务端。 
    - client_connected_cb指定的回调函数，在新连接建立的时候被调用。该回调函数接收StreamReader和StreamWriter类的‘实例对’(reader,writer)作为两个参数。
    - client_connected_cb可以是普通的可调用函数，也可以是协程函数。如果是协程函数，那么会被自动封装为Task对象处理
- StreamReader
  -  read(n=-1)
    -  最多读取n字节数据。如果n未设置，或被设置为-1，则读取至EOF标志，并返回读到的所有字节。
- StreamWriter
  - write(data)
    - 向数据流中写入数据。
    - write()应同drain()一同使用。
  - drain()
    - 这是一个与底层IO输入缓冲区交互的流量控制方法。当缓冲区达到上限时，drain()阻塞，待到缓冲区回落到下限时，写操作可以被恢复。当不需要等待时，drain()会立即返回。
  
## socks协议
- *socks协议的设计初衷是在保证网络隔离的情况下，提高部分人员的网络访问权限，但是国内似乎很少有组织机构这样使用。一般情况下，大家都会使用更新的网络安全技术来达到相同的目的。*
- *但是由于socksCap32和PSD这类软件，人们找到了socks协议新的用途：突破网络通信限制，这和该协议的设计初衷正好相反。另外，socks协议也可以用来内网穿透。*
- *socks支持多种用户身份验证方式和通信加密方式*
- *socks工作在比HTTP代理更低的层次：socks使用握手协议来通知代理软件其客户端试图进行的连接socks，然后尽可能透明地进行操作，而常规代理可能会解释和重写报头（例如，使用另一种底层协议，例如FTP；然而，HTTP代理只是将HTTP请求转发到所需的HTTP服务器）。虽然HTTP代理有不同的使用模式，CONNECT方法允许转发TCP连接；然而，socks代理还可以转发UDP流量和反向代理，而HTTP代理不能。HTTP代理通常更适合HTTP协议，执行更高层次的过滤（虽然通常只用于GET和POST方法，而不用于CONNECT方法）。socks不管应用层是什么协议，只要是传输层是TCP/UDP协议就可以代理。*
- ![image](socksProxy.png)


## 运行截图
![image](socks5.png)
![image](proxy.png)
![image](baidu.png)