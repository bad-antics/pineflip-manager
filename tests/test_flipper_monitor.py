import pytest
from app import app

class FakeSerialNoOpen:
    def __init__(self, *args, **kwargs):
        self.is_open = False

class FakeSerialOpen:
    def __init__(self, *args, **kwargs):
        self.is_open = True
        self.port = 'COM6'
        self.in_waiting = 0
    def reset_input_buffer(self):
        pass
    def write(self, data):
        pass
    def read(self, n):
        return b''


def test_flipper_monitor_not_connected(monkeypatch):
    # Ensure connect_flipper will fail (no serial)
    monkeypatch.setattr('serial.Serial', FakeSerialNoOpen)
    with app.test_client() as c:
        r = c.get('/flipper_monitor')
        assert r.status_code == 200
        data = r.get_json()
        assert data['connected'] == False
        assert 'error' in data


def test_flipper_monitor_connected(monkeypatch):
    monkeypatch.setattr('serial.Serial', FakeSerialOpen)
    # Ensure list_ports returns our fake
    class DummyPort:
        def __init__(self, device):
            self.device = device
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [DummyPort('COM6')])

    with app.test_client() as c:
        # Access an endpoint that triggers connect
        c.get('/flipper')
        r = c.get('/flipper_monitor')
        assert r.status_code == 200
        data = r.get_json()
        assert data['connected'] == True
        assert 'info' in data and isinstance(data['info'], list)
        assert 'last_updated' in data
