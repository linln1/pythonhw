import asyncio
import asyncio_dgram
import sqlite3

# async def udp_echo_client():
#     stream = await asyncio_dgram.connect('127.0.0.1', 8888)
#     await stream.send(b'Hello world!')
#     data, remote_addr = await stream.recv()
#     stream.close()
#
# async def udp_echo_server():
#     stream = await asyncio_dgram.bind('127.0.0.1', 8888)
#     while True:
#         data, remote_addr = await stream.recv()
#         await stream.send(data, remote_addr)

def main():
    conn = sqlite3.connect('temp.db')
    c = conn.cursor()
    c.execute('''DROP TABLE IF EXISTS USER ;''')
    c.execute('''CREATE TABLE USER
           (USERNAME           TEXT    NOT NULL,
           PASSWORD           TEXT);''')
    print("Table created successfully")
    # c.execute("INSERT INTO USER (ID,USERNAME,PASSWORD) \
    #       VALUES (1, 'root', '020900');")

    c.execute('''INSERT INTO USER(USERNAME, PASSWORD) VALUES ('u1', '11');''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD) VALUES ('u2', '22');''')
    c.execute('''INSERT INTO USER(USERNAME, PASSWORD) VALUES ('u3', '33');''')
    c.execute("SELECT * FROM USER")
    for row in c:
        print("NAME = ", row[0])
        print("PASSWORD = ", row[1])

    # c.execute('''UPDATE USER SET PASSWORD = '12' WHERE USERNAME = 'u1';''')
    # c.execute("SELECT * FROM USER")
    # for row in c:
    #     print("NAME = ", row[0])
    #     print("PASSWORD = ", row[1])
    #
    # c.execute('''DELETE FROM USER WHERE USERNAME = 'u1';''')
    # c.execute("SELECT * FROM USER")
    # for row in c:
    #     print("NAME = ", row[0])
    #     print("PASSWORD = ", row[1])

    conn.commit()
    conn.close()


if __name__ == '__main__':
    main()