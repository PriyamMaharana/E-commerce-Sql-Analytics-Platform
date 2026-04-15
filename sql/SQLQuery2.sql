use Ecommerce_Analytics;

select * from dq_results;

select * from dq_rules;

select * from etl_job_log;

UPDATE TOP (5) stg_orders
SET order_id = NULL
WHERE order_id IS NOT NULL;

exec usp_dq_checks;

SELECT *
FROM dq_results dr
JOIN dq_rules r ON dr.rule_id = r.rule_id
WHERE r.severity = 'HIGH';

exec usp_dq_monitor;

EXEC msdb.dbo.sp_send_dbmail
    @profile_name = 'DQProfile',
    @recipients = 'priyam.webui@gmail.com',
    @subject = 'Test Email',
    @body = 'Mail working!';

SELECT 
    mailitem_id,
    subject,
    recipients,
    sent_status,
    send_request_date
FROM msdb.dbo.sysmail_allitems
ORDER BY send_request_date DESC;

SELECT *
FROM msdb.dbo.sysmail_event_log
ORDER BY log_date DESC;