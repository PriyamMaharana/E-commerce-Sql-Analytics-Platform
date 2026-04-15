-- creating data quality checker
-- DQ table
use Ecommerce_Analytics;
go

create table dq_rules (
	rule_id int primary key identity,
	table_name nvarchar(50),
	column_name nvarchar(50),
	rule_type nvarchar(50), -- null, duplicate, fk, range
	severity nvarchar(20) -- high, medium, low
);
go

create table dq_results (
	result_id int primary key identity,
	rule_id int,
	failed_rows int,
	total_rows int,
	status nvarchar(20),
	checked_at datetime default getdate(),
	failure_pct decimal(5,2),
	execution_time_ms int
);
go

-- inserting rules for tables
insert into dq_rules (
	table_name, column_name, rule_type, severity
) values 
-- orders
('stg_orders', 'order_id', 'NULL_CHECK', 'HIGH'),
('stg_orders', 'order_id', 'DUPLICATE_CHECK', 'HIGH'),
('stg_orders', 'customer_id', 'NULL_CHECK', 'HIGH'),
-- customers
('stg_customers', 'customer_id', 'NULL_CHECK', 'HIGH'),
('stg_customers', 'customer_unique_id', 'NULL_CHECK', 'HIGH'),
-- order items
('stg_order_items', 'order_id', 'NULL_CHECK', 'HIGH'),
('stg_order_items', 'product_id', 'NULL_CHECK', 'HIGH'),
('stg_order_items', 'price', 'RANGE_CHECK', 'MEDIUM'),
-- payments
('stg_payments', 'payment_value', 'RANGE_CHECK', 'HIGH');
go

CREATE OR ALTER PROCEDURE usp_dq_checks
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE
        @rule_id INT,
        @table_name NVARCHAR(100),
        @column_name NVARCHAR(100),
        @rule_type NVARCHAR(50),
        @sql NVARCHAR(MAX),
        @start_time DATETIME2;

    -- Clear today's results
    DELETE FROM dq_results
    WHERE CAST(checked_at AS DATE) = CAST(GETDATE() AS DATE);

    DECLARE dq_cursor CURSOR FOR
    SELECT rule_id, table_name, column_name, rule_type
    FROM dq_rules;

    OPEN dq_cursor;

    FETCH NEXT FROM dq_cursor
    INTO @rule_id, @table_name, @column_name, @rule_type;

    WHILE @@FETCH_STATUS = 0
    BEGIN
        SET @start_time = SYSDATETIME();

        ---------------------------------------------------
        -- NULL CHECK
        ---------------------------------------------------
        IF @rule_type = 'NULL_CHECK'
        BEGIN
            SET @sql = '
                DECLARE @total_rows INT;
                SELECT @total_rows = COUNT(*) FROM ' + @table_name + ';

                INSERT INTO dq_results (
                    rule_id, failed_rows, total_rows, failure_pct, status, execution_time_ms
                )
                SELECT 
                    ' + CAST(@rule_id AS NVARCHAR) + ',
                    COUNT(*) AS failed_rows,
                    @total_rows,
                    CASE 
                        WHEN @total_rows = 0 THEN 0
                        ELSE (COUNT(*) * 100.0 / @total_rows)
                    END,
                    CASE WHEN COUNT(*) > 0 THEN ''FAIL'' ELSE ''PASS'' END,
                    DATEDIFF(MILLISECOND, ''' + CAST(@start_time AS NVARCHAR) + ''', SYSDATETIME())
                FROM ' + @table_name + '
                WHERE ' + @column_name + ' IS NULL;
            ';
        END

        ---------------------------------------------------
        -- DUPLICATE CHECK
        ---------------------------------------------------
        ELSE IF @rule_type = 'DUPLICATE_CHECK'
        BEGIN
            SET @sql = '
                DECLARE @total_rows INT;
                SELECT @total_rows = COUNT(*) FROM ' + @table_name + ';

                INSERT INTO dq_results (
                    rule_id, failed_rows, total_rows, failure_pct, status, execution_time_ms
                )
                SELECT 
                    ' + CAST(@rule_id AS NVARCHAR) + ',
                    COUNT(*) AS failed_rows,
                    @total_rows,
                    CASE 
                        WHEN @total_rows = 0 THEN 0
                        ELSE (COUNT(*) * 100.0 / @total_rows)
                    END,
                    CASE WHEN COUNT(*) > 0 THEN ''FAIL'' ELSE ''PASS'' END,
                    DATEDIFF(MILLISECOND, ''' + CAST(@start_time AS NVARCHAR) + ''', SYSDATETIME())
                FROM (
                    SELECT ' + @column_name + '
                    FROM ' + @table_name + '
                    GROUP BY ' + @column_name + '
                    HAVING COUNT(*) > 1
                ) d;
            ';
        END

        -- Execute dynamic SQL
        EXEC sp_executesql @sql;

        FETCH NEXT FROM dq_cursor
        INTO @rule_id, @table_name, @column_name, @rule_type;
    END;

    CLOSE dq_cursor;
    DEALLOCATE dq_cursor;
END;
GO


-- adding severity index
create index idx_dq_results_severity
on dq_results(rule_id);
go

create table etl_job_log (
	job_name nvarchar(100),
	run_time datetime default getdate(),
	status nvarchar(20),
	message nvarchar(500)
);
go


CREATE OR ALTER PROCEDURE usp_dq_monitor
AS
BEGIN
    SET NOCOUNT ON;

    DECLARE 
        @fail_count INT = 0,
        @email_body NVARCHAR(MAX);

    -------------------------------------------------------
    -- Count HIGH severity failures
    -------------------------------------------------------
    SELECT @fail_count = COUNT(*)
    FROM dq_results dr
    JOIN dq_rules r ON dr.rule_id = r.rule_id
    WHERE dr.status = 'FAIL'
        AND r.severity = 'HIGH'
        AND CAST(dr.checked_at AS DATE) = CAST(GETDATE() AS DATE);

    -------------------------------------------------------
    -- If HIGH failures exist
    -------------------------------------------------------
    IF ISNULL(@fail_count, 0) > 0
    BEGIN
        PRINT '🚨 HIGH severity DQ issues detected!';

        ---------------------------------------------------
        -- Build dynamic email body (VERY POWERFUL)
        ---------------------------------------------------
        SELECT @email_body = STRING_AGG(
            CONCAT(
                'Table: ', r.table_name,
                ' | Column: ', r.column_name,
                ' | Rule: ', r.rule_type,
                ' | Failed Rows: ', dr.failed_rows,
                ' | Failure %: ', CAST(dr.failure_pct AS VARCHAR)
            ), CHAR(10)
        )
        FROM dq_results dr
        JOIN dq_rules r ON dr.rule_id = r.rule_id
        WHERE dr.status = 'FAIL'
            AND r.severity = 'HIGH'
            AND CAST(dr.checked_at AS DATE) = CAST(GETDATE() AS DATE);

        ---------------------------------------------------
        -- Log failure
        ---------------------------------------------------
        INSERT INTO etl_job_log (
            job_name, status, message, run_time
        )
        VALUES (
            'DQ_MONITOR',
            'FAIL',
            'High severity DQ issues found',
            GETDATE()
        );

        ---------------------------------------------------
        -- Send email (SAFE)
        ---------------------------------------------------
        BEGIN TRY
            EXEC msdb.dbo.sp_send_dbmail
                @profile_name = 'DQProfile',
                @recipients = 'priyam.webui@gmail.com',
                @subject = '🚨 Data Quality Alert - E-Commerce',
                @body = @email_body;
        END TRY
        BEGIN CATCH
            PRINT 'Email failed: ' + ERROR_MESSAGE();
        END CATCH
    END

    -------------------------------------------------------
    -- If everything is OK
    -------------------------------------------------------
    ELSE
    BEGIN
        PRINT '✅ Data Quality OK!';

        INSERT INTO etl_job_log (
            job_name, status, message, run_time
        )
        VALUES (
            'DQ_MONITOR',
            'SUCCESS',
            'All checks passed',
            GETDATE()
        );
    END
END;
GO
