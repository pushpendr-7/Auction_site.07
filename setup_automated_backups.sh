#!/bin/bash

# Setup automated backups for permanent data storage
# This script sets up cron jobs for regular data backups

echo "Setting up automated data backups for permanent storage..."

# Create backup directory
BACKUP_DIR="/var/backups/auction_site"
sudo mkdir -p $BACKUP_DIR
sudo chown -R $USER:$USER $BACKUP_DIR

# Create backup script
cat > /tmp/backup_script.sh << 'EOF'
#!/bin/bash
# Automated backup script for auction site data

BACKUP_DIR="/var/backups/auction_site"
LOG_FILE="/var/log/auction_backups.log"
PROJECT_DIR="/workspace"

# Create timestamp
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# Log function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> $LOG_FILE
}

log "Starting automated backup process"

# Change to project directory
cd $PROJECT_DIR

# Run scheduled backup
python manage.py scheduled_backup --backup-type=scheduled --output-dir=$BACKUP_DIR --encrypt

if [ $? -eq 0 ]; then
    log "Scheduled backup completed successfully"
else
    log "ERROR: Scheduled backup failed"
fi

# Run incremental backup (daily)
python manage.py scheduled_backup --backup-type=incremental --output-dir=$BACKUP_DIR --encrypt

if [ $? -eq 0 ]; then
    log "Incremental backup completed successfully"
else
    log "ERROR: Incremental backup failed"
fi

# Cleanup old backups (keep last 30 days)
find $BACKUP_DIR -name "*.json" -mtime +30 -delete
find $BACKUP_DIR -name "*.zip" -mtime +30 -delete

log "Backup process completed"
EOF

# Make backup script executable
chmod +x /tmp/backup_script.sh
sudo mv /tmp/backup_script.sh /usr/local/bin/auction_backup.sh

# Create log file
sudo touch /var/log/auction_backups.log
sudo chown $USER:$USER /var/log/auction_backups.log

# Setup cron jobs
echo "Setting up cron jobs..."

# Add cron jobs (run every 6 hours for incremental, daily for full backup)
(crontab -l 2>/dev/null; echo "0 */6 * * * /usr/local/bin/auction_backup.sh") | crontab -
(crontab -l 2>/dev/null; echo "0 2 * * * cd /workspace && python manage.py scheduled_backup --backup-type=system_full --output-dir=$BACKUP_DIR --encrypt") | crontab -

# Setup data retention policies
echo "Setting up data retention policies..."
cd /workspace
python manage.py setup_data_retention

echo "Automated backup setup completed!"
echo "Backup directory: $BACKUP_DIR"
echo "Log file: /var/log/auction_backups.log"
echo ""
echo "Cron jobs added:"
echo "- Incremental backup every 6 hours"
echo "- Full system backup daily at 2 AM"
echo ""
echo "To view cron jobs: crontab -l"
echo "To view backup logs: tail -f /var/log/auction_backups.log"