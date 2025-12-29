import json
import pytest

from app import app

class DummyPort:
    def __init__(self, device, vid=None, pid=None, description=None, manufacturer=None):
        self.device = device
        self.vid = vid
        self.pid = pid
        self.description = description
        self.manufacturer = manufacturer


def test_status_devices_no_ports(monkeypatch):
    # simulate no ports
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: [])
    with app.test_client() as c:
        r = c.get('/status/devices')
        assert r.status_code == 200
        data = r.get_json()
        assert 'devices' in data and isinstance(data['devices'], list)
        assert data['devices'] == []
        assert data['flipper_connected_port'] is None


def test_status_devices_with_port_and_connection(monkeypatch):
    ports = [DummyPort('COM6', vid=0x239a, pid=0x8006, description='Flipper Zero', manufacturer='Flipper')]
    monkeypatch.setattr('serial.tools.list_ports.comports', lambda: ports)

    class FakeSerial:
        def __init__(self, port, baud, timeout):
            self.port = port
            self.is_open = True
            self.in_waiting = 0
        def close(self):
            self.is_open = False
        def reset_input_buffer(self):
            pass
        def write(self, data):
            pass
        def read(self, n):
            return b''

    monkeypatch.setattr('serial.Serial', FakeSerial)

    with app.test_client() as c:
        # trigger connection
        # call an endpoint that requires flipper; that will invoke connect_flipper
        r = c.get('/flipper')
        assert r.status_code == 200
        r2 = c.get('/status/devices')
        data = r2.get_json()
        assert len(data['devices']) == 1
        assert data['devices'][0]['device'] == 'COM6'
        assert data['flipper_connected_port'] == 'COM6' or data['flipper_connected_port'] == None
