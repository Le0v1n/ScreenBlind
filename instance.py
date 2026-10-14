"""Keep one tray instance per Windows user and activate it on a second launch."""
import hashlib
from i18n import tr
from PyQt6.QtCore import QLockFile, QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket


class InstanceGuard(QObject):
    activated = pyqtSignal()

    def __init__(self, folder, parent=None):
        super().__init__(parent)
        self._lock = QLockFile(str(folder / 'instance.lock'))
        self._lock.setStaleLockTime(0)
        self._name = 'ScreenBlind-' + hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:24]
        self._server = QLocalServer(self)

    def acquire(self):
        if not self._lock.tryLock(0):
            socket = QLocalSocket(self)
            socket.connectToServer(self._name)
            if not socket.waitForConnected(3000):
                raise RuntimeError(tr('ScreenBlind is already running but could not be reached. Try again shortly.'))
            socket.disconnectFromServer()
            return False
        QLocalServer.removeServer(self._name)
        if not self._server.listen(self._name):
            self._lock.unlock()
            raise RuntimeError(tr('Cannot create the ScreenBlind instance communication service.'))
        self._server.newConnection.connect(self._activate)
        return True

    def _activate(self):
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            socket.close()
            socket.deleteLater()
        self.activated.emit()

    def close(self):
        self._server.close()
        self._lock.unlock()
