# monitoring_dashboard.py
# queries SQL SERVER Agent job history
# generate HTML monitoring dashboard sends alert email if job fails

import pandas as pd
import logging
import pyodbc
import smtplib
import os
from datetime import datetime
from email.mime.text import  MIMEText
from email.mime.multipart import MIMEMultipart

## logging setup
logger = logging.getLogger(__name__) 

## database connection
def get_connection():
    return pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=localhost;'
        'DATABASE=Ecommerce_Analytics;'
        'Trusted_Connection=yes;'
        'TrustServerCertificate=yes;'
    )
    
def get_job_history(job_name, last_n_runs=10):
    conn = get_connection()

    df = pd.read_sql(f"""
        SELECT TOP {last_n_runs}
            j.name AS job_name,
            h.step_id,
            h.step_name,
            h.run_date,
            h.run_time,
            h.run_duration,
            CASE h.run_status
                WHEN 0 THEN 'Failed'
                WHEN 1 THEN 'Succeeded'
                WHEN 2 THEN 'Retry'
                WHEN 3 THEN 'Cancelled'
                WHEN 4 THEN 'In Progress'
            END AS run_status,
            h.message
        FROM msdb.dbo.sysjobs j
        JOIN msdb.dbo.sysjobhistory h
            ON j.job_id = h.job_id
        WHERE j.name = ?
        ORDER BY h.run_date DESC, h.run_time DESC
    """, conn, params=[job_name])

    conn.close()
    return df


def get_dq_summary(last_n_runs=10):
    conn = get_connection()

    # Read run summary
    df = pd.read_sql(f"""
        SELECT TOP {last_n_runs}
            run_id,
            CONVERT(NVARCHAR, run_date, 120) AS run_date,
            total_checks, passed_checks,
            failed_checks, critical_fails, overall_status
        FROM Ecommerce_Analytics.dbo.dq_run_summary
        ORDER BY run_date DESC
    """, conn)

    # Read latest failures
    latest_fails = pd.read_sql("""
        SELECT TOP 20
            run_id, table_name, column_name,
            rule_name, severity, status,
            pass_rate, failed_records, details
        FROM Ecommerce_Analytics.dbo.dq_audit
        WHERE status = 'FAIL'
        ORDER BY run_date DESC
    """, conn)
    
    conn.close()
    return df, latest_fails

def generate_html_report(job_history, dq_summary,
                         dq_fails, output_path):
    def status_badge(status):
        colors = {
            'Succeeded': '#28a745',
            'PASSED': '#28a745',
            'Failed': '#dc3545',
            'FAILED': '#dc3545',
            'WARNING': '#fd7e14',
            'PASS': '#28a745',
            'FAIL': '#dc3545',
        }
        color = colors.get(status, '#6c757d')
        return (f'<span style="background:{color};color:white;'
                f'padding:2px 8px; border-radius:4px;'
                f'font-size:12px;font-weight:bold">'
                f'{status}</span>')
        
    job_rows = ""
    for _, row in job_history.iterrows():
            job_rows += f"""
            <tr>
                <td>{row['run_date']}</td>
                <td>{row['run_time']}</td>
                <td>{row['step_name']}</td>
                <td>{status_badge(row['run_status'])}</td>
                <td>{row['run_duration']}</td>
                <td style"font-size:11px">{str(row['message'])[:80]}</td>
            </tr>
            """
            
    dq_rows = ""
    for _, row in dq_summary.iterrows():
            dq_rows += f""" 
            <tr>
                <td>{row['run_date']}</td>
                <td>{row['total_checks']}</td>
                <td style="color:#28a745">{row['passed_checks']}</td>
                <td style="color:#dc3545">{row['failed_checks']}</td>
                <td style="color:#dc3545;font-weight:bold">{row['critical_fails']}</td>
                <td>{status_badge(row['overall_status'])}</td>
            </tr>
            """
            
    fail_rows = ""
    for _, row in dq_fails.iterrows():
            fail_rows += f"""
            <tr>
                <td>{row['table_name']}</td>
                <td>{row['column_name']}</td>
                <td>{row['rule_name']}</td>
                <td>{status_badge(row['severity'].upper())}</td>
                <td>{row['pass_rate']}%</td>
                <td>{row['failed_records']:,}%</td>
                <td style"font-size:11px">{row['details']}</td>
            </tr>
            """
        
    html = f"""
        <!DOCTYPE html>
        <html>
        <head>
        <title>Pipeline Monitoring Dashboard</title>
        <style>
        body {{ font-family: Arial, sans-serif;
                background: #f5f5f5; padding: 20px; }}
        h1   {{ color: #333; border-bottom: 2px solid #007bff;
                padding-bottom: 10px; }}
        h2   {{ color: #555; margin-top: 30px; }}
        table {{ width: 100%; border-collapse: collapse;
                background: white; margin-bottom: 20px;
                box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
        th   {{ background: #007bff; color: white;
                padding: 10px; text-align: left; }}
        td   {{ padding: 8px 10px;
                border-bottom: 1px solid #eee; }}
        tr:hover {{ background: #f9f9f9; }}
        .summary-box {{ display: inline-block;
                        background: white; padding: 15px 25px;
                        margin: 10px; border-radius: 8px;
                        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
                        text-align: center; }}
        .metric {{ font-size: 32px; font-weight: bold;
                    color: #007bff; }}
        .label  {{ font-size: 12px; color: #888; }}
        </style>
        </head>
        <body>
        <h1>Pipeline Monitoring Dashboard</h1>
        <p style="color:#888">
            Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        </p>

        <h2>SQL Agent Job History</h2>
        <table>
        <tr>
            <th>Date</th><th>Time</th><th>Step</th>
            <th>Status</th><th>Duration</th><th>Message</th>
        </tr>
        {job_rows}
        </table>

        <h2>Data Quality Run History</h2>
        <table>
        <tr>
            <th>Run Date</th><th>Total</th><th>Passed</th>
            <th>Failed</th><th>Critical</th><th>Status</th>
        </tr>
        {dq_rows}
        </table>

        <h2>Recent DQ Failures</h2>
        <table>
        <tr>
            <th>Table</th><th>Column</th><th>Rule</th>
            <th>Severity</th><th>Pass Rate</th>
            <th>Failed Rows</th><th>Details</th>
        </tr>
        {fail_rows if fail_rows else
        '<tr><td colspan="7" style="text-align:center;'
        'color:#28a745">No failures — all checks passed</td></tr>'}
        </table>

        </body>
        </html>
        """
        
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
            f.write(html)
    logger.info(f"Dashboard Saved: {output_path}")
    return output_path
    

def send_alert(dq_summary_df, fails_df, sender,
               password, recipient):
    if dq_summary_df.empty:
        return
    
    latest = dq_summary_df.iloc[0]
    if latest['critical_fails'] == 0:
        logger.info(f"No critical failures - no alert sent")
        return
    
    critical_fails = fails_df[
        fails_df['severity'] == 'critical'
    ]
    
    fail_details = "\n".join([
        f" {r['table_name']}.{r['column_name']} "
        f"[{r['rule_name']}] - "
        f"{r['failed_records']:,} rows failed "
        f"({r['pass_rate']}% pass rate)"
        for _, r in critical_fails.iterrows()
    ])
    
    msg = MIMEMultipart()
    msg['Subject'] = (
        f"CRITICAL: DQ Pipeline Alert - "
        f"{latest['critical_fails']} critical failures"
    )
    msg['From'] = sender
    msg['To'] = recipient
    
    body = f"""
    Data Quality Alert - Ecommerce Analytics Pipeline
    
    Run ID: {latest['run_id']}
    Run Date: {latest['run_date']}
    Status: {latest['overall_status']}
    
    Results:
    Total Checks: {latest['total_checks']}
    Passed: {latest['passed_checks']}
    Failed: {latest['failed_checks']}
    Critical Fails: {latest['critical_fails']}
    
    Critical Failures:
    {fail_details}
    
    Action Required: Review dq_audit table and return pipeline.
    """
    
    msg.attach(MIMEText(body, 'plain'))
    
    try: 
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(sender, password)
            smtp.send_message(msg)
        logger.warning(f"Alert email sent to {recipient}")
    except Exception as e:
        logger.warning(f"Email failed: {e}")
        

def run_monitoring(send_email=False):
    logger.info("Running monitoring dashboard...")

    job_name  = 'Ecom_ETL_&_DQ_Pipeline'
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path  = f'reports/monitoring_{timestamp}.html'
    
    job_history = get_job_history(job_name)
    dq_summary, dq_fails = get_dq_summary()

    report_path = generate_html_report(
        job_history, dq_summary, dq_fails, out_path
    )
    
    if not report_path:
        raise ValueError("Report generation failed")

    if send_email:
        send_alert(
            dq_summary, dq_fails,
            sender    = 'priyam.webui@gmail.com',
            password  = 'kclqdshzerurmlwv',
            recipient = 'priyam.webui@gmail.com'
        )

    return report_path

if __name__ == "__main__":
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)s | %(message)s'
    )
    send_email = '--email' in sys.argv
    run_monitoring(send_email=send_email)