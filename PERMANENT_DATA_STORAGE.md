# Permanent Data Storage System

This document describes the comprehensive permanent data storage system implemented for the auction site to ensure all user data is saved permanently on the server.

## Overview

The system provides multiple layers of data protection and permanent storage:

1. **Automated Backup System** - Regular backups of all data
2. **Data Export Feature** - Users can download their own data
3. **Data Retention Policies** - Long-term storage policies for different data types
4. **Data Encryption** - Sensitive information is encrypted
5. **Database Optimization** - Optimized for better performance and persistence
6. **Restoration Tools** - Easy data restoration from backups

## Features Implemented

### 1. Automated Backup System

#### Management Commands
- `backup_user_data.py` - Backup specific user or all user data
- `scheduled_backup.py` - Automated scheduled backups
- `restore_data.py` - Restore data from backup files

#### Backup Types
- **Full System Backup** - Complete system data including media files
- **Incremental Backup** - Only data changed in last 24 hours
- **User Data Backup** - Individual user data exports
- **Scheduled Backup** - Based on retention policies

#### Usage Examples
```bash
# Backup all user data
python3 manage.py backup_user_data --output-dir=/tmp/backups

# Backup specific user
python3 manage.py backup_user_data --user-id=1 --output-dir=/tmp/backups

# Run scheduled backup
python3 manage.py scheduled_backup --backup-type=system_full --encrypt

# Restore data from backup
python3 manage.py restore_data /path/to/backup.json --dry-run
```

### 2. Data Export Feature

Users can export their complete data through the web interface:

- **Location**: Wallet page → "Export My Data" button
- **Format**: JSON with all user information
- **Includes**: Profile, transactions, bids, orders, wallet data, auction participations
- **Security**: Sensitive data is encrypted in exports

### 3. Data Retention Policies

Long-term storage policies for different data types:

| Data Type | Retention Period | Auto Delete | Backup Before Delete |
|-----------|------------------|-------------|---------------------|
| User Profiles | 7 years | No | Yes |
| Auction Items | 5 years | No | Yes |
| Bids | 5 years | No | Yes |
| Payments | 7 years | No | Yes |
| Orders | 5 years | No | Yes |
| Wallet Transactions | 7 years | No | Yes |
| Ledger Blocks | 10 years | No | Yes |
| Auction Participants | 3 years | No | Yes |

### 4. Data Encryption

Sensitive user information is encrypted using Fernet encryption:

- **Encrypted Fields**: Email, phone, bank details, UPI VPA
- **Encryption Method**: Fernet (AES 128 in CBC mode)
- **Key Management**: Configurable via settings
- **Automatic**: Encryption happens during backup and export

### 5. Database Models

New models added for data management:

#### DataBackup
- Tracks all backup operations
- Stores backup metadata and file paths
- Supports different backup types
- Includes encryption status

#### DataRetentionPolicy
- Defines retention periods for different data types
- Configurable auto-deletion settings
- Backup-before-delete options

#### UserDataExport
- Tracks user data export requests
- GDPR compliance support
- Download tracking and expiration

### 6. Automated Backup Setup

The system includes an automated setup script:

```bash
# Run the setup script
./setup_automated_backups.sh
```

This script:
- Creates backup directories
- Sets up cron jobs for regular backups
- Configures data retention policies
- Sets up log files

#### Cron Jobs
- **Incremental Backup**: Every 6 hours
- **Full System Backup**: Daily at 2 AM
- **Cleanup**: Removes backups older than 30 days

### 7. Data Integrity

#### Checksums
- All backups include SHA-256 checksums
- Integrity verification before restoration
- Automatic corruption detection

#### Verification
```python
# Verify data integrity
checksum = verify_data_integrity(data)
```

### 8. Security Features

#### Encryption
- Sensitive data encrypted at rest
- Configurable encryption keys
- Secure key management

#### Access Control
- User-specific data exports
- Admin-only backup management
- Secure file storage

## Configuration

### Environment Variables

Add to your `.env` file:

```env
# Data encryption key (generate a new one for production)
DATA_ENCRYPTION_KEY=your-32-character-base64-key-here

# Backup settings
BACKUP_DIR=/var/backups/auction_site
BACKUP_RETENTION_DAYS=30
```

### Settings Configuration

Add to `settings.py`:

```python
# Data encryption
DATA_ENCRYPTION_KEY = os.environ.get('DATA_ENCRYPTION_KEY', Fernet.generate_key())

# Backup settings
BACKUP_DIR = os.environ.get('BACKUP_DIR', '/tmp/auction_backups')
BACKUP_RETENTION_DAYS = int(os.environ.get('BACKUP_RETENTION_DAYS', '30'))
```

## Usage Guide

### For Users

1. **Export Your Data**:
   - Go to Wallet page
   - Click "Export My Data"
   - Download JSON file with all your information

### For Administrators

1. **Setup Automated Backups**:
   ```bash
   ./setup_automated_backups.sh
   ```

2. **Manual Backup**:
   ```bash
   python3 manage.py scheduled_backup --backup-type=system_full --encrypt
   ```

3. **Restore Data**:
   ```bash
   python3 manage.py restore_data /path/to/backup.json
   ```

4. **View Backup Status**:
   ```bash
   python3 manage.py shell
   >>> from auctions.models import DataBackup
   >>> DataBackup.objects.all().order_by('-created_at')[:10]
   ```

## Monitoring

### Log Files
- Backup operations: `/var/log/auction_backups.log`
- Django logs: Standard Django logging

### Database Queries
```sql
-- View recent backups
SELECT * FROM auctions_databackup ORDER BY created_at DESC LIMIT 10;

-- Check retention policies
SELECT * FROM auctions_dataretentionpolicy;

-- View user exports
SELECT * FROM auctions_userdataexport ORDER BY requested_at DESC;
```

## Best Practices

1. **Regular Monitoring**: Check backup logs regularly
2. **Test Restorations**: Periodically test data restoration
3. **Key Management**: Securely store encryption keys
4. **Storage Management**: Monitor disk space for backups
5. **Security Updates**: Keep encryption libraries updated

## Troubleshooting

### Common Issues

1. **Backup Fails**:
   - Check disk space
   - Verify permissions
   - Check log files

2. **Encryption Errors**:
   - Verify encryption key
   - Check cryptography library installation

3. **Restoration Issues**:
   - Verify backup file integrity
   - Check database constraints
   - Review error logs

### Support Commands

```bash
# Check backup status
python3 manage.py shell -c "from auctions.models import DataBackup; print(DataBackup.objects.count())"

# Verify data integrity
python3 manage.py shell -c "from auctions.utils import verify_data_integrity; print('OK')"

# Test encryption
python3 manage.py shell -c "from auctions.utils import DataEncryption; print(DataEncryption.encrypt_data('test'))"
```

## Compliance

This system helps with:
- **GDPR Compliance**: User data export and deletion
- **Data Retention**: Configurable retention policies
- **Audit Trail**: Complete backup and export tracking
- **Data Security**: Encryption and access controls

## Future Enhancements

1. **Cloud Storage**: Integration with AWS S3, Google Cloud
2. **Compression**: Better compression algorithms
3. **Incremental Restore**: Restore specific data ranges
4. **Monitoring Dashboard**: Web-based backup monitoring
5. **Automated Testing**: Regular backup/restore testing

---

**Note**: This system ensures that all user data is permanently stored on the server with multiple layers of protection and easy access for both users and administrators.