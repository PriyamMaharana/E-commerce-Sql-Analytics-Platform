use Ecommerce_Analytics; 
go

use msdb; 
go


-- create sql agent job
-- runs etl + dq daily at 6:00 am
exec sp_add_job
	@job_name = N'Ecom_ETL_&_DQ_Pipeline',
	@enabled = 1,
	@description = N'Daily ETL laod + Data Quality Checks
					for E-Commerce Analytics platform',
	@category_name = N'Data Collector';
go

-- s1: run ETL pipeline
exec sp_update_jobstep
	@job_name = N'Ecom_ETL_&_DQ_Pipeline',
	@step_name = N'S1_Run_ETL',
	@step_id = 1,
	@command = N'"E:\SQL-ETL-Resume-Project\E-commerce SQL Analytics Platform\.venv\Scripts\python.exe" "E:\SQL-ETL-Resume-Project\E-commerce SQL Analytics Platform\load-data.py"',
    @subsystem = N'CmdExec',
	@on_success_action = 3,
	@on_fail_action = 2;
go

-- s2: run DQ checks
exec sp_update_jobstep
	@job_name = N'Ecom_ETL_&_DQ_Pipeline',
	@step_name = N'S2_Run_DQ_Checks',
	@step_id = 2,
	@command = N'"E:\SQL-ETL-Resume-Project\E-commerce SQL Analytics Platform\.venv\Scripts\python.exe" "E:\SQL-ETL-Resume-Project\E-commerce SQL Analytics Platform\dq_runner.py"',
	@subsystem = N'CmdExec',
	@on_success_action = 1,
	@on_fail_action = 2;
go

-- s3: schedule daily at 6:00 am
exec sp_add_schedule
	@schedule_name = N'Daily_6AM',
	@freq_type = 4,
	@freq_interval = 1,
	@active_start_time = 60000;
go

SELECT 
    schedule_id,
    name,
    enabled,
    freq_type,
    active_start_time
FROM msdb.dbo.sysschedules
WHERE name = 'Daily_6AM';

EXEC msdb.dbo.sp_delete_schedule @schedule_id = 14;
EXEC msdb.dbo.sp_delete_schedule @schedule_id = 15;
EXEC msdb.dbo.sp_delete_schedule @schedule_id = 16;

SELECT 
    j.name AS job_name,
    s.schedule_id,
    s.name
FROM msdb.dbo.sysjobs j
JOIN msdb.dbo.sysjobschedules js 
    ON j.job_id = js.job_id
JOIN msdb.dbo.sysschedules s 
    ON js.schedule_id = s.schedule_id
WHERE j.name = 'Ecom_ETL_&_DQ_Pipeline';


exec sp_attach_schedule
	@job_name = N'Ecom_ETL_&_DQ_Pipeline',
	@schedule_name = N'Daily_6AM';
go

exec sp_add_jobserver
	@job_name = N'Ecom_ETL_&_DQ_Pipeline';
go

print 'SQL Agent job created successfully!';
go