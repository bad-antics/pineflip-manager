from flask import Flask, render_template, request, jsonify, session, has_request_context
from flask import Response
from flask_bootstrap import Bootstrap
import serial
import requests
import time
from datetime import datetime
import logging
from functools import wraps
import os
import subprocess
import re
import ipaddress

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'change_this_secret_key_in_production')
Bootstrap(app)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === Configuration (override via config.py or environment) ===
FLIPPER_PORT = os.getenv('FLIPPER_PORT', 'COM3' if os.name == 'nt' else '/dev/ttyACM0')  # default per OS; override via env
FLIPPER_BAUD = 230400
FLIPPER_TIMEOUT = 2

# Auto-connect controls
AUTO_CONNECT_FLIPPER = os.getenv('AUTO_CONNECT_FLIPPER', 'true').lower() in ('1','true','yes')
AUTO_CONNECT_PINEAPPLE = os.getenv('AUTO_CONNECT_PINEAPPLE', 'true').lower() in ('1','true','yes')
AUTO_CONNECT_INTERVAL = int(os.getenv('AUTO_CONNECT_INTERVAL', '10'))  # seconds between checks

PINEAPPLE_URL = os.getenv('PINEAPPLE_URL', 'http://172.16.42.1:1471')
PINEAPPLE_USERNAME = os.getenv('PINEAPPLE_USER', 'root')
PINEAPPLE_PASSWORD = os.getenv('PINEAPPLE_PASS', 'your_password_here')

# Internal cache for Pineapple URL probing
_pineapple_url_last_probe = 0.0

def _probe_pineapple(base_url: str, timeout: float = 3.0) -> bool:
    """Return True if Pineapple API appears reachable at base_url."""
    try:
        # status endpoint is lightweight; fallback to root if needed
        u = f"{base_url}/api/status" if not base_url.endswith('/api/status') else base_url
        r = requests.get(u, timeout=timeout)
        return r.status_code == 200 or r.status_code in (401, 403)
    except Exception:
        return False

def _discover_windows_pineapple_candidates() -> list:
    """On Windows, parse ipconfig to detect 172.16.X.0/24 USB/RNDIS networks and return likely base URLs.
    Prefers the classic 172.16.42.1 but also considers any 172.16.<octet>.1 observed.
    """
    cands = []
    try:
        out = subprocess.check_output(['ipconfig'], text=True, timeout=5, errors='ignore')
        # Find IPv4 addresses; if any are in 172.16.X.0/24, assume device is 172.16.X.1
        for m in re.finditer(r'IPv4 Address[^:]*:\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})', out):
            ip = m.group(1)
            try:
                addr = ipaddress.ip_address(ip)
                if addr in ipaddress.ip_network('172.16.0.0/16'):
                    octets = ip.split('.')
                    base = f"http://{octets[0]}.{octets[1]}.{octets[2]}.1"
                    if f"{base}:1471" not in cands:
                        cands.append(f"{base}:1471")
                    if base not in cands:
                        cands.append(base)
            except Exception:
                continue
    except Exception:
        pass
    # Always include common defaults to try
    if 'http://172.16.42.1:1471' not in cands:
        cands.append('http://172.16.42.1:1471')
    if 'http://172.16.42.1' not in cands:
        cands.append('http://172.16.42.1')
    return cands

def ensure_pineapple_url(force: bool = False) -> str:
    """Ensure `PINEAPPLE_URL` points to a reachable Pineapple API. Attempts quick discovery on Windows.
    Returns the selected base URL (may be unchanged).
    """
    global PINEAPPLE_URL, _pineapple_url_last_probe
    now = time.time()
    if not force and (now - _pineapple_url_last_probe) < 30:
        return PINEAPPLE_URL
    # Try the current value first
    if _probe_pineapple(PINEAPPLE_URL):
        _pineapple_url_last_probe = now
        return PINEAPPLE_URL
    # Build candidate list
    candidates = []
    if os.name == 'nt':
        candidates.extend(_discover_windows_pineapple_candidates())
    else:
        candidates.extend(['http://172.16.42.1:1471', 'http://172.16.42.1'])
    # Probe candidates
    for base in candidates:
        if _probe_pineapple(base):
            with _state_lock:
                PINEAPPLE_URL = base
            _pineapple_url_last_probe = now
            logger.info('Detected Pineapple base URL: %s', base)
            return base
    _pineapple_url_last_probe = now
    return PINEAPPLE_URL

# Optional: load local config if exists
if os.path.exists('config.py'):
    app.config.from_pyfile('config.py')

# Flipper connection state
flipper_connected = False
flipper_ser = None

# Pineapple token (global fallback for background worker) and locks
pineapple_token = None
_state_lock = __import__('threading').Lock()

def connect_flipper():
    """Attempt to open configured FLIPPER_PORT, and if that fails, try to auto-detect serial ports.
    Returns True on successful open and False otherwise.
    """
    global flipper_ser, flipper_connected
    import threading
    with _state_lock:
        try:
            # If a specific port is configured, try it first
            try_ports = [FLIPPER_PORT] if FLIPPER_PORT else []
            # Append all available ports to try auto-detect
            try:
                from serial.tools import list_ports
                for p in list_ports.comports():
                    # log detailed device metadata when available
                    try:
                        logger.debug('Found serial port: %s (vid=%s pid=%s desc=%s)', p.device, getattr(p, 'vid', None), getattr(p, 'pid', None), getattr(p, 'description', None))
                    except Exception:
                        logger.debug('Found serial port: %s', getattr(p, 'device', None))
                    if p.device not in try_ports:
                        try_ports.append(p.device)
            except Exception:
                logger.debug('Could not enumerate serial ports for auto-detect')

            for port in try_ports:
                if not port:
                    continue
                try:
                    if flipper_ser and flipper_ser.is_open:
                        flipper_ser.close()
                    logger.info(f'Trying Flipper on port {port}')
                    candidate = serial.Serial(port, FLIPPER_BAUD, timeout=FLIPPER_TIMEOUT)
                    # Optionally perform a quick handshake (non-blocking)
                    time.sleep(0.1)
                    if candidate.is_open:
                        flipper_ser = candidate
                        flipper_connected = True
                        logger.info(f"Flipper Zero connected on {port}")
                        return True
                except Exception as e:
                    logger.debug(f"Failed to open {port}: {e}")
            # If none succeeded
            flipper_connected = False
            return False
        except Exception as e:
            logger.error(f"Flipper connection failed: {e}")
            flipper_connected = False
            return False

# Do not auto-connect on import; connect on-demand when a route needs the device

def with_flipper(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not flipper_connected:
            if not connect_flipper():
                # If we're in a request context, return an HTTP response; otherwise raise to let non-request callers handle
                if has_request_context():
                    return jsonify({'error': 'Flipper Zero not connected'}), 503
                raise RuntimeError('Flipper Zero not connected')
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception("Flipper error during command")
            # Try to reconnect asynchronously to avoid blocking the request
            try:
                import threading
                threading.Thread(target=connect_flipper, daemon=True).start()
            except Exception:
                logger.debug('Failed to start reconnect thread')
            if has_request_context():
                return jsonify({'error': str(e)}), 500
            raise
    return wrapper

@with_flipper
def send_flipper_command(command):
    try:
        flipper_ser.reset_input_buffer()
        flipper_ser.write((command + '\r\n').encode())
        time.sleep(0.6)
        response = flipper_ser.read(flipper_ser.in_waiting).decode(errors='ignore').strip()
        return response or 'Command sent.'
    except Exception:
        raise

def get_pineapple_token():
    """Return a valid pineapple token.
    Prefer session token (per-user), otherwise fall back to global token retrieved by the background worker.
    """
    global pineapple_token
    # Try session token when a request context exists
    try:
        if 'pineapple_token' in session:
            return session['pineapple_token']
    except RuntimeError:
        # No request context, ignore
        pass

    # Fallback to global token
    with _state_lock:
        if pineapple_token:
            return pineapple_token

    # If nothing yet, try to fetch a token (non-session) and store globally
    # Ensure base URL is sane before attempting login
    ensure_pineapple_url()
    try:
        resp = requests.post(f'{PINEAPPLE_URL}/api/login',
                             json={'username': PINEAPPLE_USERNAME, 'password': PINEAPPLE_PASSWORD},
                             timeout=8)
        if resp.status_code == 200:
            try:
                data = resp.json()
                token = data.get('token')
                if token:
                    with _state_lock:
                        pineapple_token = token
                    return token
            except ValueError:
                logger.error('Pineapple login returned non-JSON response')
    except Exception as e:
        logger.error(f"Pineapple login failed: {e}")
        # Retry once after forced discovery
        try:
            ensure_pineapple_url(force=True)
            resp = requests.post(f'{PINEAPPLE_URL}/api/login',
                                 json={'username': PINEAPPLE_USERNAME, 'password': PINEAPPLE_PASSWORD},
                                 timeout=8)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    token = data.get('token')
                    if token:
                        with _state_lock:
                            pineapple_token = token
                        return token
                except ValueError:
                    logger.error('Pineapple login returned non-JSON response (retry)')
        except Exception as e2:
            logger.error('Pineapple forced discovery/login retry failed: %s', e2)
    return None

def pineapple_api_call(endpoint, method='GET', data=None, timeout=10):
    token = get_pineapple_token()
    if not token:
        return {'error': 'Pineapple authentication failed'}
    headers = {'Authorization': f'Bearer {token}'}
    url = f'{PINEAPPLE_URL}{endpoint}'
    try:
        resp = requests.request(method, url, headers=headers, json=data, timeout=timeout)
        try:
            return resp.json() if resp.status_code == 200 else {'error': f'{resp.status_code}: {resp.text}'}
        except ValueError:
            # Return text if not JSON
            return {'result': resp.text}
    except requests.Timeout:
        return {'error': 'Pineapple request timed out'}
    except requests.ConnectionError:
        return {'error': 'Cannot reach WiFi Pineapple'}
    except Exception as e:
        return {'error': str(e)}

# Background auto-connect worker

def _auto_connect_worker():
    """Background loop that periodically attempts to connect to the Flipper and Pineapple when disabled.
    Runs as a daemon thread and respects the AUTO_CONNECT_* flags.
    """
    logger.info('Auto-connect worker started (interval=%s)', AUTO_CONNECT_INTERVAL)
    while True:
        try:
            if AUTO_CONNECT_FLIPPER and not flipper_connected:
                logger.debug('Auto-connect: attempting flipper connection')
                connect_flipper()
            if AUTO_CONNECT_PINEAPPLE:
                # Refresh URL and try to get a token and store globally
                try:
                    ensure_pineapple_url()
                except Exception:
                    pass
                t = None
                try:
                    t = get_pineapple_token()
                except Exception:
                    t = None
                if t:
                    logger.debug('Auto-connect: pineapple auth succeeded')
            time.sleep(AUTO_CONNECT_INTERVAL)
        except Exception as e:
            logger.error('Auto-connect worker error: %s', e)
            time.sleep(max(1, AUTO_CONNECT_INTERVAL))


# Ensure background worker is started once (use before_request guard for compatibility)
_auto_worker_started = False
@app.before_request
def _start_auto_connect():
    global _auto_worker_started
    if _auto_worker_started:
        return None
    # Start the worker only if either auto-connect flag is enabled
    if not (AUTO_CONNECT_FLIPPER or AUTO_CONNECT_PINEAPPLE):
        logger.info('Auto-connect disabled by configuration')
        _auto_worker_started = True
        return None
    import threading
    worker = threading.Thread(target=_auto_connect_worker, daemon=True, name='auto-connect')
    worker.start()
    _auto_worker_started = True
    return None

# Utility: list serial devices with metadata
def list_serial_devices():
    out = []
    try:
        from serial.tools import list_ports
        for p in list_ports.comports():
            out.append({
                'device': getattr(p, 'device', None),
                'vid': getattr(p, 'vid', None),
                'pid': getattr(p, 'pid', None),
                'description': getattr(p, 'description', None),
                'manufacturer': getattr(p, 'manufacturer', None)
            })
    except Exception:
        logger.debug('Could not enumerate serial ports')
    return out


# Status/devices endpoint
@app.route('/status/devices')
def status_devices():
    devices = list_serial_devices()
    connected_port = getattr(flipper_ser, 'port', None) if flipper_ser else None
    pineapple_ok = bool(get_pineapple_token())
    return jsonify({'devices': devices, 'flipper_connected_port': connected_port, 'pineapple_authenticated': pineapple_ok})


# Routes
@app.route('/')
def home():
    return render_template('home.html')

@app.route('/flipper')
def flipper():
    return render_template('flipper.html', connected=flipper_connected)

@app.route('/pineapple')
def pineapple():
    return render_template('pineapple.html', connected=bool(get_pineapple_token()))

@app.route('/flipper_monitor')
def flipper_monitor():
    if not flipper_connected:
        return jsonify({'error': 'Not connected', 'connected': False})

    error_msg = None
    # Gather raw responses
    try:
        info_raw = send_flipper_command('info device') or ''
    except Exception as e:
        info_raw = ''
        error_msg = str(e)
    try:
        uptime_raw = send_flipper_command('uptime') or ''
    except Exception as e:
        uptime_raw = ''
        error_msg = error_msg or str(e)
    try:
        memory_raw = send_flipper_command('free') or ''
    except Exception as e:
        memory_raw = ''
        error_msg = error_msg or str(e)

    # Normalize into structured fields
    info_lines = [line.strip() for line in info_raw.splitlines() if line.strip()]

    result = {
        'connected': True,
        'port': getattr(flipper_ser, 'port', None) if flipper_ser else None,
        'info': info_lines,
        'uptime': uptime_raw.strip() if isinstance(uptime_raw, str) else uptime_raw,
        'memory': memory_raw.strip() if isinstance(memory_raw, str) else memory_raw,
        'last_updated': datetime.utcnow().isoformat() + 'Z',
        'raw': {
            'info': info_raw,
            'uptime': uptime_raw,
            'memory': memory_raw
        }
    }

    if error_msg:
        result['error'] = error_msg

    return jsonify(result)

@app.route('/flipper_command', methods=['POST'])
def flipper_command():
    cmd = request.form.get('command', '').strip()
    if not cmd:
        return jsonify({'error': 'Empty command'})
    return jsonify({'result': send_flipper_command(cmd)})

@app.route('/flipper_subghz_tx', methods=['POST'])
def flipper_subghz_tx():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'Invalid or missing JSON payload'}), 400
    action = data.get('action')
    cmd = ""

    if action == 'carrier':
        cmd = 'subghz tx carrier 433920000 0'
    elif action == 'static':
        cmd = 'subghz tx 123456 433920000 100 10 0'
    elif action == 'custom_key':
        key = data.get('key', '').strip().upper()
        if not key or not all(c in '0123456789ABCDEF' for c in key):
            return jsonify({'error': 'Invalid hex key'}), 400
        cmd = f"subghz tx {key} {data.get('freq', '433920000')} {data.get('te', '100')} {data.get('repeat', '10')} 0"
    elif action == 'from_file':
        path = data.get('path', '').strip()
        if not path or not os.path.isabs(path):
            return jsonify({'error': 'Invalid file path'}), 400
        cmd = f"subghz tx_from_file {path} {data.get('repeat', '1')} 0"
    elif action == 'raw':
        raw = data.get('raw_data', '').strip()
        if not raw:
            return jsonify({'error': 'Raw data required'}), 400
        cmd = f"subghz raw tx {data.get('freq', '433920000')} {raw}"
    else:
        return jsonify({'error': 'Unknown action'}), 400

    try:
        res = send_flipper_command(cmd)
        return jsonify({'result': res})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/pineapple_status')
def pineapple_status():
    return jsonify(pineapple_api_call('/api/status'))

@app.route('/pineapple_logs')
def pineapple_logs():
    return jsonify(pineapple_api_call('/api/pineap/log'))

@app.route('/pineapple_notifications')
def pineapple_notifications():
    return jsonify(pineapple_api_call('/api/notifications'))

@app.route('/pineapple_settings', methods=['POST'])
def pineapple_settings():
    return jsonify(pineapple_api_call('/api/pineap/settings', 'PUT', request.json))

@app.route('/status/pineapple_network')
def pineapple_network_status():
    """Diagnostics for Pineapple network auto-discovery and reachability."""
    ensure_pineapple_url()
    reachable = _probe_pineapple(PINEAPPLE_URL)
    return jsonify({'pineapple_url': PINEAPPLE_URL, 'reachable': reachable})

# Flipper FS helpers and endpoints
def _try_fs_list(path: str) -> str:
    for cmd in [f'storage list {path}', f'ls {path}', 'storage list', 'ls']:
        try:
            out = send_flipper_command(cmd)
            if out and isinstance(out, str) and out.strip():
                return out
        except Exception:
            continue
    return ''

def _try_fs_read(path: str) -> str:
    for cmd in [f'storage read {path}', f'cat {path}']:
        try:
            out = send_flipper_command(cmd)
            if out and isinstance(out, str):
                return out
        except Exception:
            continue
    return ''

def _try_fs_delete(path: str) -> str:
    for cmd in [f'storage delete {path}', f'rm {path}']:
        try:
            out = send_flipper_command(cmd)
            if out and isinstance(out, str):
                return out
        except Exception:
            continue
    return ''

@app.route('/flipper_fs/list')
def flipper_fs_list():
    path = request.args.get('path', '/ext').strip() or '/ext'
    out = _try_fs_list(path)
    entries = [line.strip() for line in out.splitlines() if line.strip()] if out else []
    return jsonify({'path': path, 'entries': entries, 'raw': out})

@app.route('/flipper_fs/read')
def flipper_fs_read():
    path = request.args.get('path', '').strip()
    if not path:
        return jsonify({'error': 'Path required'}), 400
    out = _try_fs_read(path)
    return jsonify({'path': path, 'content': out})

@app.route('/flipper_fs/delete', methods=['POST'])
def flipper_fs_delete():
    data = request.get_json(silent=True) or {}
    path = str(data.get('path', '')).strip()
    if not path:
        return jsonify({'error': 'Path required'}), 400
    out = _try_fs_delete(path)
    if not out:
        return jsonify({'error': 'Delete failed or unsupported'}), 500
    return jsonify({'path': path, 'result': out})

@app.route('/flipper_fs/download')
def flipper_fs_download():
    path = request.args.get('path', '').strip()
    if not path:
        return jsonify({'error': 'Path required'}), 400
    content = _try_fs_read(path)
    if content == '':
        return jsonify({'error': 'Read failed'}), 500
    filename = path.split('/')[-1] or 'flipper_file.txt'
    return Response(content, headers={'Content-Disposition': f'attachment; filename="{filename}"'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)