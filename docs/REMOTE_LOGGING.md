# Remote Execution with RotatingFileHandler

This guide explains how to run the PolyMarket Trading Agent script on a Linux server with proper log rotation using `RotatingFileHandler`.

## Overview

The script now uses `RotatingFileHandler` to automatically manage log files:
- **Maximum file size**: 5MB
- **Number of backups**: 5 files
- **Log location**: `logs/` directory (relative to project root)
- **Log filename format**: `trading_agent_YYYYMMDD_HHMMSS.log`

## Log File Structure

```
logs/
├── trading_agent_20260127_210815.log        # Current log file
├── trading_agent_20260127_210815.log.1      # First backup
├── trading_agent_20260127_210815.log.2      # Second backup
├── trading_agent_20260127_210815.log.3      # Third backup
├── trading_agent_20260127_210815.log.4      # Fourth backup
├── trading_agent_20260127_210815.log.5      # Fifth backup (oldest)
├── trading_agent_20260128_083022.log
└── ...
```

## Running on Linux Server

### Option 1: Direct Execution (Simple)

```bash
# Navigate to project directory
cd /path/to/PolyMarket-trading-AI-model

# Run the script (backgrounded)
nohup python -m scripts.python.cli run_autonomous_trader > logs/terminal_output.log 2>&1 &

# Check if process is running
ps aux | grep "run_autonomous_trader"
```

**Note**: Output will be sent to both the log file and terminal. Logs are written to `logs/trading_agent_YYYYMMDD_HHMMSS.log`.

### Option 2: Using Screen (Interactive)

```bash
# Navigate to project directory
cd /path/to/PolyMarket-trading-AI-model

# Create a new screen session
screen -S trading_agent

# Run the script
python -m scripts.python.cli run_autonomous_trader

# Press Ctrl+A then D to detach from screen
# Screen will continue running in background

# To reattach later:
screen -r trading_agent

# List all screen sessions:
screen -ls
```

### Option 3: Using tmux (Advanced)

```bash
# Navigate to project directory
cd /path/to/PolyMarket-trading-AI-model

# Create a new tmux session
tmux new -s trading_agent

# Run the script
python -m scripts.python.cli run-autonomous-trader

# Press Ctrl+B then D to detach
# To reattach:
tmux attach -t trading_agent
```

### Option 4: Systemd Service (Production Recommended)

#### Create the Service File

Create `/etc/systemd/system/polymarket-trading.service`:

```ini
[Unit]
Description=Polymarket AI Trading Agent
After=network.target

[Service]
Type=simple
User=your_username
Group=your_group
WorkingDirectory=/path/to/PolyMarket-trading-AI-model
Environment="PATH=/path/to/PolyMarket-trading-AI-model/.venv/bin"
ExecStart=/path/to/PolyMarket-trading-AI-model/.venv/bin/python -m scripts.python.cli run_autonomous_trader
Restart=always
RestartSec=10
StandardOutput=append:/var/log/polymarket-trading/output.log
StandardError=append:/var/log/polymarket-trading/error.log

[Install]
WantedBy=multi-user.target
```

#### Enable and Start the Service

```bash
# Reload systemd to recognize new service
sudo systemctl daemon-reload

# Enable the service to start on boot
sudo systemctl enable polymarket-trading

# Start the service
sudo systemctl start polymarket-trading

# Check service status
sudo systemctl status polymarket-trading

# View logs
sudo journalctl -u polymarket-trading -f
```

### Option 5: Cron Job (Scheduled Execution)

#### Running at Specific Intervals

```bash
# Edit crontab
crontab -e

# Add entry to run trading every 6 hours
0 */6 * * * cd /path/to/PolyMarket-trading-AI-model && /path/to/.venv/bin/python -m scripts.python.cli run_autonomous_trader >> logs/cron_output.log 2>&1
```

## Monitoring Logs

### View Current Log File

```bash
# Follow logs in real-time
tail -f logs/trading_agent_*.log

# View last 100 lines
tail -n 100 logs/trading_agent_*.log

# View logs with line numbers
tail -n 100 logs/trading_agent_*.log | cat -n
```

### Search Logs

```bash
# Search for ERROR level messages
grep "ERROR" logs/trading_agent_*.log

# Search for a specific trading strategy
grep "ai_one_best_trade" logs/trading_agent_*.log

# Search for recent activity in last 1 hour
grep "$(date -d '1 hour ago' '+%Y-%m-%d %H:%M')" logs/trading_agent_*.log
```

### Manage Log Files

```bash
# List all log files
ls -lh logs/

# Show disk usage of logs directory
du -sh logs/

# Clean up logs older than 30 days
find logs/ -name "*.log*" -mtime +30 -exec gzip {} \;

# Delete logs older than 90 days
find logs/ -name "*.log*" -mtime +90 -delete

# Count log files
ls -1 logs/*.log | wc -l
```

## Configuration Parameters

You can configure the log behavior by modifying the `setup_logging()` function in `scripts/python/cli.py`:

```python
# Current settings (lines 30-50)
log_dir = Path("logs")  # Change this to customize log directory
log_file = log_dir / f"trading_agent_{timestamp}.log"  # Customize filename format

# Adjust these parameters:
file_handler = RotatingFileHandler(
    log_file,
    maxBytes=5 * 1024 * 1024,  # Change to different size (e.g., 10 * 1024 * 1024 for 10MB)
    backupCount=5,              # Change to keep more or fewer backups
    encoding='utf-8'
)
```

## Troubleshooting

### Logs Not Being Created

1. **Check directory permissions**:
   ```bash
   ls -ld logs/
   # Should exist with write permissions
   ```

2. **Check Python environment**:
   ```bash
   # Make sure virtual environment is activated
   source .venv/bin/activate
   ```

3. **Check for errors**:
   ```bash
   python -m scripts.python.cli run_autonomous_trader
   # Run without backgrounding to see errors
   ```

### High Disk Usage

1. **Check log file sizes**:
   ```bash
   du -h logs/*.log
   ```

2. **Adjust backup count**:
   ```python
   backupCount=3  # Reduce to 3 backups instead of 5
   ```

3. **Set up log cleanup cron job**:
   ```bash
   # Delete logs older than 7 days
   0 0 * * * find /path/to/project/logs -name "*.log" -mtime +7 -delete
   ```

### Process Not Running

1. **Check if process is running**:
   ```bash
   ps aux | grep "run_autonomous_trader"
   ```

2. **Check systemd logs (if using systemd)**:
   ```bash
   sudo journalctl -u polymarket-trading -n 100
   ```

3. **Check if ports are already in use** (for trading strategies that open connections):
   ```bash
   netstat -tulpn | grep LISTEN
   ```

## Security Considerations

1. **Secure the logs directory**:
   ```bash
   chmod 700 logs/
   chown your_username:your_group logs/
   ```

2. **Protect sensitive data**:
   - Review logs to ensure no sensitive information is logged
   - Consider adding filters to exclude sensitive API keys

3. **Log rotation best practices**:
   - Keep regular backups of logs
   - Store logs on separate disk if possible
   - Monitor disk usage to prevent overfilling

## Best Practices

1. **Always run in background** when executing long-running commands:
   ```bash
   nohup command > output.log 2>&1 &
   ```

2. **Use systemd** for production deployments for better process management

3. **Monitor disk usage** regularly:
   ```bash
   du -sh logs/
   ```

4. **Regular log review**:
   - Check for ERROR level messages daily
   - Monitor trading activity logs
   - Review error patterns

5. **Test configuration** before deploying:
   ```bash
   # Test with a short duration first
   timeout 60 python -m scripts.python.cli run_autonomous_trader