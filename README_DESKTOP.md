# Bad-Antics Device Manager - Desktop App

A native Windows desktop application for managing Flipper Zero and WiFi Pineapple devices.

## Features

- **Flipper Zero Management**
  - Auto-detect and connect to Flipper Zero via serial connection
  - Real-time device monitoring (port, info, uptime, memory)
  - Send custom commands to Flipper CLI
  - File explorer - list, read, and delete files from Flipper storage
  - Sub-GHz transmission controls

- **WiFi Pineapple Management**
  - Auto-discover Pineapple on local network
  - View device status and logs
  - Manage notifications
  - Configure device settings

## Requirements

- Windows 10 or later
- Python 3.10+ (for running from source)
- USB connection to Flipper Zero
- Network access to WiFi Pineapple

## Installation

### Option 1: Run from Source (Recommended for Development)

1. Clone or download this repository
2. Navigate to the `flipper-pineapple-manager` directory
3. Install dependencies:
   ```
   py -3.13 -m pip install PyQt6 requests pyserial
   ```
4. Run the application:
   ```
   py -3.13 desktop_app.py
   ```

### Option 2: Create Standalone Executable

1. Ensure Python 3.13 is installed
2. Navigate to the `flipper-pineapple-manager` directory
3. Run the build script:
   ```
   build_exe.bat
   ```
4. The executable will be created in the `dist` folder

## Usage

### Flipper Zero Tab

1. **Connect**: 
   - Select the COM port or use "Auto-detect"
   - Click "Connect"
   - Status will change to "Connected" (green) on success

2. **Monitor Device**:
   - Device info, uptime, and memory usage updates automatically
   - Shown in the Monitor panel

3. **Send Commands**:
   - Enter any Flipper CLI command (e.g., `info device`, `uptime`, `free`)
   - Click "Send" to execute
   - Results appear in the monitor

4. **File Explorer**:
   - Specify a path (e.g., `/ext`, `/int`)
   - Click "List Files" to view contents
   - Files are displayed in the panel below

### WiFi Pineapple Tab

1. **Connect**:
   - Enter Pineapple URL (auto-detected as `http://172.16.42.1`)
   - Enter username and password
   - Click "Connect"

2. **View Status**:
   - Connected status shows in green
   - Click "Refresh Status" to get current Pineapple info

## Architecture

- **device_manager.py**: Core device communication logic
  - `FlipperDevice`: Handles Flipper Zero serial communication
  - `PineappleDevice`: Handles WiFi Pineapple API calls
  
- **desktop_app.py**: PyQt6 desktop GUI
  - `FlipperTab`: Flipper device interface
  - `PineappleTab`: Pineapple device interface
  - `DeviceWorker`: Background thread for auto-connect and status updates

## Configuration

The app supports environment variables for default values:

- `FLIPPER_PORT`: Serial port for Flipper (default: auto-detect)
- `FLIPPER_BAUD`: Baud rate (default: 230400)
- `PINEAPPLE_URL`: Pineapple address (default: http://172.16.42.1)
- `PINEAPPLE_USER`: Pineapple username (default: root)
- `PINEAPPLE_PASS`: Pineapple password

Set these before launching the app:
```powershell
$env:PINEAPPLE_USER = "root"
$env:PINEAPPLE_PASS = "your_password"
py -3.13 desktop_app.py
```

## Troubleshooting

### Flipper Won't Connect
- Check USB cable is properly connected
- Verify COM port in Device Manager
- Try a different USB port
- Check that no other application has the port open

### Pineapple Won't Connect
- Ensure WiFi Pineapple is powered on and on the network
- Check IP address with `ipconfig` (should be 172.16.42.x)
- Verify credentials (default: root/flooding)
- Try clicking "Connect" again to force rediscovery

## Building Executable

To create a standalone `.exe` file:

```bash
build_exe.bat
```

This uses PyInstaller to package the app with all dependencies into a single executable.

## Development

### Adding Features

1. Device logic goes in `device_manager.py`
2. UI components go in `desktop_app.py`
3. Use signals/slots for thread communication
4. Test with actual devices before committing

## License

Part of Bad-Antics project

## Credits

- Flipper Zero community
- WiFi Pineapple community
- PyQt6 developers
