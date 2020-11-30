import datetime
import os
import sys
import logging
from time import sleep

from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtNetwork import *
from PyQt5.QtWidgets import *
from PyQt5.QtWebSockets import *
import humanfriendly
import websockets
import traceback
import asyncio


class WindowClass(QWidget):

    def __init__(self,parent=None):

        super(WindowClass, self).__init__(parent)
        layout=QVBoxLayout()

        self.widgetstack = []

        self.startBtn = QPushButton()
        self.startBtn.setText("start")
        self.startBtn.clicked.connect(self.onclickStart)
        self.startBtn.setFixedSize(90, 150)

        self.exitBtn = QPushButton()
        self.exitBtn.clicked.connect(self.onclickExit)
        self.exitBtn.setText("exit")
        self.exitBtn.setFixedSize(90, 150)

        # self.btn=QPushButton()
        # self.btn.setText("显示对话框")
        # self.btn.clicked.connect(self.showDialog)
        self.resize(500,500)
        #layout.addWidget(self.btn)
        layout.addWidget(self.startBtn)
        layout.addWidget(self.exitBtn)
        layout.setAlignment(Qt.AlignCenter)
        self.setLayout(layout)

        self.processIdLine = QLineEdit()
        self.bandWidth = QLineEdit()
        self.websocket = None
        self.process = QProcess()
        self.process.setProcessChannelMode(QProcess.MergedChannels)

        self.process.started.connect(self.processStart)
        self.process.readyReadStandardOutput.connect(self.getStatus)
        self.process.finished.connect(self.processFinish)

    def onclickStart(self):
        w = QWidget()
        self.widgetstack.append(w)
        vbox = QVBoxLayout()  # 纵向布局
        hbox = QHBoxLayout()  # 横向布局
        vboxBtn = QVBoxLayout()
        # self.startBtn.hide()
        # self.exitBtn.hide()

        self.username = QLineEdit()
        self.username.setPlaceholderText('input username : ')
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText('input password')

        self.listenPort = QLineEdit()
        self.listenPort.setPlaceholderText('listenPort : ')
        self.listenHost = QLineEdit()
        self.listenHost.setPlaceholderText('listenHost : ')
        self.consolePort = QLineEdit()
        self.consolePort.setText(str(8896))
        self.remoteHost = QLineEdit()
        self.remoteHost.setPlaceholderText('remoteHost :')
        self.remotePort = QLineEdit()
        self.remotePort.setPlaceholderText('remotePort :')

        self.connectBtn = QPushButton()
        self.connectBtn.setText('conncet')
        self.connectBtn.clicked.connect(self.connect)
        self.backBtn = QPushButton()
        self.backBtn.setText('back')
        self.backBtn.clicked.connect(self.back)

        vbox.addWidget(self.username)
        vbox.addWidget(self.password)
        vbox.addWidget(self.listenHost)
        vbox.addWidget(self.listenPort)
        vbox.addWidget(self.remoteHost)
        vbox.addWidget(self.remotePort)

        vbox.addWidget(self.consolePort)

        vboxBtn.addWidget(self.connectBtn)
        vboxBtn.addWidget(self.backBtn)

        hbox.addLayout(vbox)
        hbox.addLayout(vboxBtn)
        w.setWindowModality(Qt.ApplicationModal)
        w.setLayout(hbox)
        w.show()

    def onclickExit(self):
        vbox = QVBoxLayout()
        hbox = QHBoxLayout()
        panel = QLabel()
        panel.setText("确定退出？")
        self.dialog = QDialog()
        self.dialog.resize(100, 100)
        self.okBtn = QPushButton("确定")
        self.cancelBtn = QPushButton("取消")
        self.okBtn.clicked.connect(self.ok)
        self.cancelBtn.clicked.connect(self.cancel)
        self.dialog.setWindowTitle("提示信息！")

        hbox.addWidget(self.okBtn)
        hbox.addWidget(self.cancelBtn)

        # 消息label与按钮组合纵向布局
        vbox.addWidget(panel)
        vbox.addLayout(hbox)
        self.dialog.setLayout(vbox)

        self.dialog.setWindowModality(Qt.ApplicationModal)  # 该模式下，只有该dialog关闭，才可以关闭父界面
        self.dialog.exec_()
        pass

    def ok(self):
        print("确定退出！")
        self.dialog.close()
        self.close()
    def cancel(self):
        print("取消退出！")
        self.dialog.close()
    def back(self):
        print("返回！")
        self.widgetstack[-1].close()
    def connect(self):
        username = self.username.text()
        password = self.password.text()
        listenHost = self.listenHost.text()
        listenPort = self.listenPort.text()
        consolePort = self.consolePort.text()
        remoteHost = self.remoteHost.text()
        remotePort = self.remotePort.text()
        pythonExec = os.path.basename(sys.executable)
        # 从localgui启动localproxy直接使用-w 提供用户密码，不再使用命令行交互输入，因为有些许问题
        # _parser.add_argument('--proto', dest='proto', metavar='protocol', default='http tunnel')
        # _parser.add_argument('--host', dest='listenHost', metavar='listen_host', default='127.0.0.1',
        #                      help='proxy listen host default listen all interfaces')
        # _parser.add_argument('--port', dest='listenPort', metavar='listen_port', default=8888, required=False,
        #                      help='proxy listen port')
        # _parser.add_argument('--username', dest='user', metavar='user', default='u1', help='username')
        # _parser.add_argument('--password', dest='pwd', metavar='pwd', default='11', help='password')

        cmdLine = f'{pythonExec} local.py --host={listenHost} --port={listenPort} --username={username} --password={password}'
        log.debug(f'cmd={cmdLine}')
        self.process.start(cmdLine)
        self.widgetstack.append(QWidget())
        self.process.waitForReadyRead()
        #
        # self.process.kill()
        # async with websockets.connect('ws://127.0.0.1:' + self.consolePort.text()) as websocket:
        #     await self.send_msg(websocket)

    async def send_msg(websocket, logHint=''):
        while True:
            recv_text = await websocket.recv()
            log.info(f'recv{logHint} bandwidth = {recv_text} per second')

    def getStatus(self, traceback=None):
        data = self.process.readAll()
        try:
            msg = data.data().decode().strip()
            print(msg)
            log.debug(f'msg={msg}')
        except Exception as exc:
            log.error(f'{traceback.format_exc()}')
            exit(1)



    def processStart(self):
        process = self.sender()  # 此处等同于 self.process 只不过使用sender适应性更好
        processId = process.processId()
        log.debug(f'pid={processId}')
        #self.startBtn.setText('Stop')
        self.processIdLine.setText(str(processId))

        # async with websockets.connect('ws://127.0.0.1:' + self.consolePort.text()) as websocket:
        #     await self.send_msg(websocket)

        self.websocket = QWebSocket()
        self.websocket.connected.connect(self.websocketConnected)
        self.websocket.disconnected.connect(self.websocketDisconnected)
        self.websocket.textMessageReceived.connect(self.websocketMsgRcvd)
        self.websocket.open(QUrl(f'ws://127.0.0.1:{self.consolePort.text()}/'))

    def processFinish(self):
        process = self.sender()
        processId = process.processId()
        log.debug(f'end process {processId}')
        self.process.kill()

    def websocketMsgRcvd(self, msg):
        if msg != None:
            # Successdia = QDialog()
            #             # SuccessBtn = QPushButton()
            #             # SuccessBtn.setText('connect success')
            #             # Successdia.showNormal()
            #             # Successdia.close()
            #self.widgetstack[-1].close()
            w = self.widgetstack[-1]
            self.widgetstack.append(w)
            vbox = QVBoxLayout()
            vbox.addWidget(self.processIdLine)
            log.debug(f'msg={msg}')
            sendBandwidth , *_ = msg.split()
            dt = datetime.datetime.now()
            nowTime = dt.strftime('%Y-%m-%d %H:%M:%S ')
            self.bandWidth.setText(f'{nowTime} {sendBandwidth}')
            vbox.addWidget(self.bandWidth)
            w.setLayout(vbox)
            w.show()

    def websocketConnected(self):#以加密形式发送数据
        self.websocket.sendTextMessage('secret')

    def websocketDisconnected(self):
        self.process.kill()


if __name__=="__main__":

    _logFmt = logging.Formatter('%(asctime)s %(levelname).1s %(lineno)-3d %(funcName)-20s %(message)s', datefmt='%H:%M:%S')
    _consoleHandler = logging.StreamHandler()
    _consoleHandler.setLevel(logging.DEBUG)
    _consoleHandler.setFormatter(_logFmt)

    log = logging.getLogger(__file__)
    log.addHandler(_consoleHandler)
    log.setLevel(logging.DEBUG)

    app = QApplication(sys.argv)
    win = WindowClass()
    win.show()
    sys.exit(app.exec_())