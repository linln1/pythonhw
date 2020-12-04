import sqlite3

from sanic import Sanic, response
from sanic.response import json
import time
import aiosqlite
import logging
import signal
import asyncio

app = Sanic("App Name")
app.config.DB_NAME = 'cache.db'

@app.route("/")
async def run(request):
    return json({"hello": "world"})

# get
@app.get("/users")
async def getusers(req):
    userList = list()
    async with aiosqlite.connect('cache.db') as db:
        async with db.execute("SELECT * FROM user;") as cur:
            async for row in cur:
                user = {'username' : row[0], 'password' : row[1], 'dataRate' : row[2]}
                timenow = time.time()
                log.debug(f'{timenow} : {row[0]}, {row[2]}')
                userList.append(user)
    return response.json(userList)

@app.get('/user/<name>' )
async def getuser(req, name):
    dataRate = 0
    user = None
    async with aiosqlite.connect(app.config.DB_NAME) as db:
        async with db.execute("SELECT * FROM user WHERE USERNAME = ?;", (str(name), )) as cur:
            async for row in cur:
                user = {'username' : row[0], 'dataRate' : row[2]}
                dataRate = row[2]
                timenow = time.time()
                log.debug(f'{timenow} : {name}, {dataRate}')
    return response.json(user)


# add
@app.post('/user')
async def userAdd(req):
    name =  req.args['name'][0]
    password = req.args['password'][0]
    dataRate = req.args['dataRate'][0]
    if not name or not password or not dataRate:
        return response.text(f'err name={name} password={password} datarate={dataRate}')
    async with aiosqlite.connect(app.config.DB_NAME) as db:
        await db.execute('INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES(?,?,?)', (name, password, int(dataRate), ))
        await db.commit()
    return response.json({})

# change
@app.put('/user')
async def userModify(req):
    name = req.args['name'][0]
    password = req.args['password'][0]
    newpassword = req.args['newpassword'][0]
    async with aiosqlite.connect(app.config.DB_NAME) as db:
        await db.execute('UPDATE USER SET PASSWORD=? WHERE USERNAME=? AND PASSWORD=?', (newpassword, name, password, ))
        await db.commit()
    return response.json({})

# delete
@app.delete('/user/<name>')
async def userDelete(req, name):
    async with aiosqlite.connect(app.config.DB_NAME) as db:
        await db.execute('DELETE FROM USER WHERE USERNAME=?', (name,))
        await db.commit()
    return response.json({})


# async def init_database():
#     async with aiosqlite.connect(app.config.DB_NAME) as db:
#         await db.execute('''DROP TABLE IF EXISTS USER;''')
#         await db.execute('''CREATE TABLE USER
#                 (USERNAME           TEXT    NOT NULL,
#                 PASSWORD           TEXT      ,
#                 BANDWIDTH        DOUBLE      );''')
#         await db.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u1', '11', 10);''')
#         await db.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u2', '22', 10);''')
#         await db.execute('''INSERT INTO USER(USERNAME, PASSWORD, BANDWIDTH) VALUES ('u3', '33', 10);''')
#         await db.commit()

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s',
                                datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)
    # asyncio.run(init_database())
    app.run(host="127.0.0.1", port=8000)

