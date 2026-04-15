
EXEC sp_configure 'show advanced options', 1;
RECONFIGURE;

EXEC sp_configure 'Database Mail XPs', 1;
RECONFIGURE;

EXEC msdb.dbo.sp_send_dbmail
    @profile_name = 'DQProfile',
    @recipients = 'priyam.webui@gmail.com',
    @subject = 'Test Email',
    @body = 'Database Mail is working!';

SELECT * FROM msdb.dbo.sysmail_profile;

EXEC msdb.dbo.sysmail_add_account_sp
    @account_name = 'DQMailAccount',
    @description = 'DQ Alerts',
    @email_address = 'priyam.webui@gmail.com',
    @display_name = 'DQ Alerts',
    @mailserver_name = 'smtp.gmail.com',
    @port = 587,
    @enable_ssl = 1,
    @username = 'priyam.webui@gmail.com',
    @password = 'kclqdshzerurmlwv';

EXEC msdb.dbo.sysmail_update_account_sp
    @account_name = 'DQMailAccount',
    @password = 'kclqdshzerurmlwv';

EXEC msdb.dbo.sysmail_add_profile_sp
    @profile_name = 'DQProfile';

EXEC msdb.dbo.sysmail_add_profileaccount_sp
    @profile_name = 'DQProfile',
    @account_name = 'DQMailAccount',
    @sequence_number = 1;

EXEC msdb.dbo.sysmail_add_principalprofile_sp
    @profile_name = 'DQProfile',
    @principal_name = 'public',
    @is_default = 1;


-- delete mail setup
EXEC msdb.dbo.sysmail_delete_profileaccount_sp
    @profile_name = 'DQProfile',
    @account_name = 'DQMailAccount';

EXEC msdb.dbo.sysmail_delete_profile_sp
    @profile_name = 'DQProfile';

SELECT * FROM msdb.dbo.sysmail_profile;
SELECT * FROM msdb.dbo.sysmail_account;
SELECT * FROM msdb.dbo.sysmail_profileaccount;


EXEC msdb.dbo.sysmail_delete_mailitems_sp @sent_before = GETDATE();
EXEC msdb.dbo.sysmail_delete_log_sp @logged_before = GETDATE();