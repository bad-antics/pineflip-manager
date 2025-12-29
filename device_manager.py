"""
Device management module for Flipper Zero and WiFi Pineapple
Extracted from Flask app.py for reuse in PyQt6 desktop application
"""

import serial
from serial.tools import list_ports
import requests
import time
import logging
import os
import subprocess
import re
import ipaddress
import threading
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)


class FlipperDevice:
    """Manages Flipper Zero serial connection"""
    
    def __init__(self, port: str = None, baud: int = 230400, timeout: float = 2.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.ser = None
        self.connected = False
        self._lock = threading.Lock()
    
    def connect(self, port: str = None) -> bool:
        """Attempt to connect to Flipper Zero"""
        if port:
            self.port = port
        
        with self._lock:
            try:
                if self.ser and self.ser.is_open:
                    self.ser.close()
                
                ports_to_try = []
                if self.port:
                    ports_to_try.append(self.port)
                
                # Add all available ports for auto-detect
                try:
                    for p in list_ports.comports():
                        if p.device not in ports_to_try:
                            ports_to_try.append(p.device)
                except Exception as e:
                    logger.debug(f"Could not enumerate serial ports: {e}")
                
                for port_candidate in ports_to_try:
                    if not port_candidate:
                        continue
                    
                    try:
                        logger.info(f'Trying Flipper on port {port_candidate}')
                        candidate = serial.Serial(port_candidate, self.baud, timeout=self.timeout)
                        time.sleep(0.1)
                        
                        if candidate.is_open:
                            self.ser = candidate
                            self.port = port_candidate
                            self.connected = True
                            logger.info(f"Flipper Zero connected on {port_candidate}")
                            return True
                    except Exception as e:
                        logger.debug(f"Failed to open {port_candidate}: {e}")
                
                self.connected = False
                return False
            
            except Exception as e:
                logger.error(f"Flipper connection failed: {e}")
                self.connected = False
                return False
    
    def disconnect(self):
        """Close Flipper connection"""
        with self._lock:
            if self.ser and self.ser.is_open:
                self.ser.close()
            self.connected = False
    
    def send_command(self, command: str) -> str:
        """Send command to Flipper and receive response"""
        if not self.connected:
            raise RuntimeError("Flipper not connected")
        
        with self._lock:
            try:
                self.ser.reset_input_buffer()
                self.ser.write((command + '\r\n').encode())
                time.sleep(0.6)
                response = self.ser.read(self.ser.in_waiting).decode(errors='ignore').strip()
                return response or 'Command sent.'
            except Exception as e:
                logger.error(f"Flipper command failed: {e}")
                raise
    
    def get_monitor_info(self) -> Dict:
        """Get Flipper monitor info (device info, uptime, memory)"""
        result = {'connected': self.connected, 'port': self.port, 'info': [], 'uptime': '', 'memory': ''}
        
        if not self.connected:
            return result
        
        try:
            result['info'] = [line.strip() for line in self.send_command('info device').splitlines() if line.strip()]
        except Exception as e:
            logger.error(f"Failed to get device info: {e}")
        
        try:
            result['uptime'] = self.send_command('uptime').strip()
        except Exception as e:
            logger.error(f"Failed to get uptime: {e}")
        
        try:
            result['memory'] = self.send_command('free').strip()
        except Exception as e:
            logger.error(f"Failed to get memory: {e}")
        
        return result
    
    def list_files(self, path: str = '/ext') -> List[str]:
        """List files in Flipper storage"""
        if not self.connected:
            return []
        
        for cmd in [f'storage list {path}', f'ls {path}', 'storage list', 'ls']:
            try:
                out = self.send_command(cmd)
                if out and out.strip():
                    return [line.strip() for line in out.splitlines() if line.strip()]
            except Exception:
                continue
        
        return []
    
    def read_file(self, path: str) -> str:
        """Read file from Flipper storage"""
        if not self.connected:
            return ''
        
        for cmd in [f'storage read {path}', f'cat {path}']:
            try:
                return self.send_command(cmd)
            except Exception:
                continue
        
        return ''
    
    def delete_file(self, path: str) -> bool:
        """Delete file from Flipper storage"""
        if not self.connected:
            return False
        
        for cmd in [f'storage delete {path}', f'rm {path}']:
            try:
                result = self.send_command(cmd)
                return bool(result and 'error' not in result.lower())
            except Exception:
                continue
        
        return False


class PineappleDevice:
    """Manages WiFi Pineapple connection and API"""
    
    def __init__(self, url: str = 'http://172.16.42.1', username: str = 'root', password: str = ''):
        self.base_url = url
        self.username = username
        self.password = password
        self.token = None
        self._last_probe = 0.0
        self._lock = threading.Lock()
    
    def _discover_candidates(self) -> List[str]:
        """Discover possible Pineapple addresses on Windows"""
        candidates = []
        
        try:
            out = subprocess.check_output(['ipconfig'], text=True, timeout=5, errors='ignore')
            for m in re.finditer(r'IPv4 Address[^:]*:\s*([0-9]{1,3}(?:\.[0-9]{1,3}){3})', out):
                ip = m.group(1)
                try:
                    addr = ipaddress.ip_address(ip)
                    if addr in ipaddress.ip_network('172.16.0.0/16'):
                        octets = ip.split('.')
                        base = f"http://{octets[0]}.{octets[1]}.{octets[2]}.1"
                        if f"{base}:1471" not in candidates:
                            candidates.append(f"{base}:1471")
                        if base not in candidates:
                            candidates.append(base)
                except Exception:
                    continue
        except Exception:
            pass
        
        # Always include common defaults
        if 'http://172.16.42.1:1471' not in candidates:
            candidates.append('http://172.16.42.1:1471')
        if 'http://172.16.42.1' not in candidates:
            candidates.append('http://172.16.42.1')
        
        return candidates
    
    def _probe_url(self, url: str, timeout: float = 3.0) -> bool:
        """Check if Pineapple is reachable at given URL"""
        try:
            test_url = f"{url}/api/status" if not url.endswith('/api/status') else url
            r = requests.get(test_url, timeout=timeout)
            return r.status_code == 200 or r.status_code in (401, 403)
        except Exception:
            return False
    
    def discover_url(self, force: bool = False) -> str:
        """Auto-discover Pineapple URL"""
        now = time.time()
        
        # Use cached result if recent enough
        if not force and (now - self._last_probe) < 30:
            return self.base_url
        
        # Try current URL first
        if self._probe_url(self.base_url):
            self._last_probe = now
            return self.base_url
        
        # Try candidates
        candidates = self._discover_candidates()
        for candidate in candidates:
            if self._probe_url(candidate):
                with self._lock:
                    self.base_url = candidate
                self._last_probe = now
                logger.info(f'Discovered Pineapple at: {candidate}')
                return candidate
        
        self._last_probe = now
        return self.base_url
    
    def authenticate(self) -> bool:
        """Authenticate with Pineapple and get token"""
        try:
            self.discover_url()
            resp = requests.post(
                f'{self.base_url}/api/login',
                json={'username': self.username, 'password': self.password},
                timeout=8
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self.token = data.get('token')
                if self.token:
                    logger.info('Pineapple authenticated')
                    return True
            
            # Retry with forced discovery
            self.discover_url(force=True)
            resp = requests.post(
                f'{self.base_url}/api/login',
                json={'username': self.username, 'password': self.password},
                timeout=8
            )
            
            if resp.status_code == 200:
                data = resp.json()
                self.token = data.get('token')
                if self.token:
                    logger.info('Pineapple authenticated (after rediscovery)')
                    return True
        
        except Exception as e:
            logger.error(f"Pineapple authentication failed: {e}")
        
        return False
    
    def is_authenticated(self) -> bool:
        """Check if we have a valid token"""
        if not self.token:
            return self.authenticate()
        return True
    
    def api_call(self, endpoint: str, method: str = 'GET', data: dict = None) -> Dict:
        """Make API call to Pineapple"""
        if not self.is_authenticated():
            return {'error': 'Pineapple authentication failed'}
        
        headers = {'Authorization': f'Bearer {self.token}'}
        url = f'{self.base_url}{endpoint}'
        
        try:
            resp = requests.request(method, url, headers=headers, json=data, timeout=10)
            
            if resp.status_code == 200:
                try:
                    return resp.json()
                except ValueError:
                    return {'result': resp.text}
            else:
                return {'error': f'{resp.status_code}: {resp.text}'}
        
        except requests.Timeout:
            return {'error': 'Pineapple request timed out'}
        except requests.ConnectionError:
            return {'error': 'Cannot reach WiFi Pineapple'}
        except Exception as e:
            return {'error': str(e)}
    
    def get_status(self) -> Dict:
        """Get Pineapple status"""
        return self.api_call('/api/status')
    
    def get_logs(self) -> Dict:
        """Get Pineapple logs"""
        return self.api_call('/api/pineap/log')
    
    def get_notifications(self) -> Dict:
        """Get Pineapple notifications"""
        return self.api_call('/api/notifications')
