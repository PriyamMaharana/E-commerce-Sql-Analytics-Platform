# dq_framework.py
# runs automatically after every ETL laod
# validates fact_orders and all dimension tables

import pyodbc
import pandas as pd
import logging
import smtplib
import os
import uuid
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import sys

# File handler — utf-8 supports emoji
file_handler = logging.FileHandler(
    'logs/dq_framework.log', encoding='utf-8'
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s'
))

# Stream handler — no emoji, cp1252 safe
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setFormatter(logging.Formatter(
    '%(asctime)s | %(levelname)s | %(message)s'
))

logging.basicConfig(level=logging.INFO,
                    handlers=[file_handler, stream_handler])
logger = logging.getLogger(__name__)

## database connection
def get_connection():
    return pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=localhost;'
        'DATABASE=Ecommerce_Analytics;'
        'Trusted_Connection=yes;'
        'TrustedServerCertificate=yes;'
    )


## DQ AUDIT table setup
## Run this once in SSMS before first DQ run
DQ_SETUP_SQL = """
    if not exists (
        select 1 from sys.tables where name = 'dq_audit'
    )
    begin
        create table dq_audit (
            audit_id int identity(1,1) primary key,
            run_id nvarchar(50),
            run_date datetime2 default getdate(),
            table_name nvarchar(100),
            column_name nvarchar(100),
            rule_name nvarchar(100),
            rule_type nvarchar(50),
            severity nvarchar(20),
            status nvarchar(10),
            total_records int,
            failed_records int,
            pass_rate decimal(5,2),
            threshold decimal(5,2),
            details nvarchar(MAX)
        );
        
        create table dq_run_summary (
            run_id nvarchar(50) primary key,
            run_date datetime2 default getdate(),
            total_checks int default 0,
            passed_checks int default 0,
            failed_checks int default 0,
            critical_fails int default 0,
            overall_status nvarchar(20),
            report_path nvarchar(500)    
        );
    end
"""

class DataQualityChecker:
    """ Reusbale DQ engine - runs configuarble rules
        against any table and logs results to dq_audit.
    """
    
    def __init__(self, table_name, run_id, conn):
        self.table_name = table_name
        self.run_id = run_id
        self.conn = conn
        self.results = []
        self.total_rows = self._count()
        
        logger.info(
            f"DQ Checker: {table_name} "
            f"({self.total_rows:,} rows)"
        )
      
        
    def _count(self):
        cursor = self.conn.cursor()
        cursor.execute(
            f"select count(*) from {self.table_name}"
        )
        return cursor.fetchone()[0]
    
    
    def _save(self, col, rule, rule_type, 
              severity, failed, threshold, details):
        """ save one rule to dq_audot table """
        pass_rate = round(
            (self.total_rows - failed) / max(self.total_rows, 1) * 100, 2
        )
        status = 'PASS' if pass_rate >= threshold else 'FAIL'
        # REPLACE THIS:
        icon = '✅' if status == 'PASS' else '❌'
        logger.info(f"{icon} {self.table_name}...")

        # WITH THIS — ascii safe:
        icon = 'PASS' if status == 'PASS' else 'FAIL'
        logger.info(
            f"[{icon}] {self.table_name}.{col} "
            f"[{rule}] ({pass_rate}% / threshold {threshold}%)"
        )
        
        cursor = self.conn.cursor()
        query = """
            insert into dq_audit(run_id, table_name, column_name, rule_name,
            rule_type, severity, status, total_records, failed_records,
            pass_rate, threshold, details) values(?,?,?,?,?,?,?,?,?,?,?,?)
        """
        cursor.execute(
            query,
            self.run_id, self.table_name,
            col, rule, rule_type, severity, status,
            self.total_rows, failed, pass_rate, 
            threshold, details   
        )
        self.conn.commit()
        
        self.results.append({
            'table': self.table_name,
            'column': col,
            'rule': rule,
            'severity': severity,
            'status': status,
            'pass_rate': pass_rate,
            'failed': failed,
            'details': details
        })
        return status
    
    
    ### rule 1: not null
    def check_not_null(self, col, threshold=95.0, severity='critical'):
        cursor = self.conn.cursor()
        cursor.execute(
            f""" select count(*) from {self.table_name}
            where {col} is null
            """
        )
        
        nulls = cursor.fetchone()[0]
        
        self._save(
            col, 'not_null', 'completeness', severity,
            nulls, threshold, f"{nulls:,} null values found"
        )
        
    ### rule 2: no duplicates
    def check_no_duplicates(self, col, threshold=100.0, 
                            severity='critical'):
        cursor = self.conn.cursor()
        
        cursor.execute(
            f""" select isnull(sum(cnt-1),0)
            from (
                select count(*) as cnt
                from {self.table_name}
                group by {col}
                having count(*) > 1
            ) d
            """
        )
        
        dup_rows = cursor.fetchone()[0]
        
        self._save(
            col, 'no_duplicates', 'uniqueness', severity, 
            dup_rows, threshold, f"{dup_rows:,} duplicate row found"
        )
        
    ### rule 3: value range
    def check_value_range(self, col, min_val=None, max_val=None,
                          threshold=95.0, severity='warning'):
        conditions = []
        if min_val is not None:
            conditions.append(f"{col} < {min_val}")
        if max_val is not None:
            conditions.append(f"{col} > {max_val}")
        if not conditions:
            return
        
        where = " OR ".join(conditions)
        cursor = self.conn.cursor()
        cursor.execute(
            f""" select count(*) from {self.table_name}
            where ({where}) and {col} is not null
            """
        )
        
        out_of_range = cursor.fetchone()[0]
        
        self._save(
            col,
            f"value_range({min_val}, {max_val})",
            'validity', severity, out_of_range, threshold,
            f"{out_of_range:,} values outside "
            f"[{min_val}, {max_val}]"
        )
        
    
    ### rule 4: allowed values
    def check_allowed_values(self, col, allowed, threshold=98.0,
                             severity='warning'):
        placeholders = ','.join(['?' for _ in allowed])
        cursor = self.conn.cursor()
        cursor.execute(
            f""" select count(*) from {self.table_name}
            where {col} is not null and {col} not in ({placeholders})
            """, allowed
        )
        
        invalid = cursor.fetchone()[0]
        
        self._save(
            col, 'allowed_values', 'validity', severity, invalid,
            threshold, f"{invalid:,} values not in {allowed}"
        )
        
        
    ### rule 5: referential integrity
    def check_referential_integrity(self, col, ref_table, ref_col,
                                    threshold=100.0, severity='critical'):
        cursor = self.conn.cursor()
        cursor.execute(
            f""" select count(*) from {self.table_name} t where t.{col}
            is not null and not exists (select 1 from {ref_table} r
            where r.{ref_col} = t.{col})
            """
        )
        
        orphans = cursor.fetchone()[0]
        
        self._save(
            col, f"rel_integrity -> {ref_table}.{ref_col}",
            'integrity', severity, orphans, threshold,
            f"{orphans:,} orphan records "
            f"(no match in {ref_table})"
        )
        
    ### rule 6: date logic
    ## delivery_date must be >= order_date
    def check_date_logic(self, date_col1, date_col2, operator='>=',
                         threshold=99.0, severity='warning'):
        cursor = self.conn.cursor()
        cursor.execute(
            f""" select count(*) from {self.table_name} where
            {date_col1} is not null and {date_col2} is not null
            and not ({date_col2} {operator} {date_col1})
            """
        )
        
        violations = cursor.fetchone()[0]
        
        self._save(
            f"{date_col1} / {date_col2}",
            f"date_logic({date_col2}{operator}{date_col1})",
            'validity', severity, violations, threshold,
            f"{violations:,} date logic violations"
        )
        
    def get_results(self):
        return self.results
    
    
## run all DQ Checks on Ecommerce schema
def run_dq_checks(run_id=None):
    if run_id is None:
        run_id = f"DQ_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
    logger.info("="*60)
    logger.info(f"Data Quality Run: {run_id}")
    logger.info("="*60)
    
    conn = get_connection()
    all_results = []
    
    ## check 1: fact_orders
    logger.info("\n -- fact_orders --")
    fact = DataQualityChecker('fact_orders', run_id, conn)
    fact.check_not_null('order_id', threshold=100.0)
    fact.check_not_null('customer_sk', threshold=100.0)
    fact.check_not_null('product_sk', threshold=100.0)
    fact.check_not_null('date_sk',threshold=100.0)
    fact.check_not_null('price_brl', threshold=99.0)
    fact.check_not_null('price_inr', threshold=99.0)
    fact.check_value_range(
        'price_inr', min_val=0, threshold=99.0, severity='critical'
    )
    fact.check_value_range(
        'review_score', min_val=1, max_val=5,
        threshold=95.0, severity='warning'
    )
    fact.check_value_range(
        'delivery_days', min_val=0, max_val=365,
        threshold=95.0, severity='warning'
    )
    fact.check_allowed_values(
        'order_status', ['delivered', 'shipped', 'canceled', 'processing'
                         'invoiced', 'unavailable', 'approved'],
        threshold=99.0
    )
    fact.check_referential_integrity(
        'customer_sk', 'dim_customer', 'customer_sk'
    )
    fact.check_referential_integrity(
        'product_sk', 'dim_product', 'product_sk'
    )
    fact.check_referential_integrity(
        'seller_sk', 'dim_seller', 'seller_sk'
    )
    all_results.extend(fact.get_results())
    
    ## check 2: dim_customer
    logger.info(f"\n--- dim_customer ---") 
    cust = DataQualityChecker('dim_customer', run_id, conn)
    cust.check_not_null('customer_id', threshold=100.0)
    cust.check_no_duplicates('customer_id', threshold=100.0)
    cust.check_not_null('state', threshold=95.0, severity='warning')
    all_results.extend(cust.get_results())
    
    ## check 3: dim_product
    logger.info(f"\n--- dim_product ---")
    prod = DataQualityChecker('dim_product', run_id, conn)
    prod.check_not_null('product_id', threshold=100.0)
    prod.check_no_duplicates('product_id', threshold=100.0)
    prod.check_value_range('weight_g', min_val=0, threshold=95.0, severity='warning')
    all_results.extend(prod.get_results())
    
    ### Save Run Summary
    df = pd.DataFrame(all_results)
    total = len(df)
    passed = len(df[df['status'] == 'PASS'])
    failed = len(df[df['status'] == 'FAIL'])
    critical = len(df[
        (df['status'] == 'FAIL') &
        (df['severity'] == 'critical')
    ])
    overall = (
        'FAILED' if critical > 0 else
        'WARNING' if failed > 0 else
        'PASSED'
    )
    
    cursor = conn.cursor()
    query = """
    insert into dq_run_summary(run_id, total_checks, passed_checks,
    failed_checks, critical_fails, overall_status) values(?,?,?,?,?,?)
    """
    cursor.execute(
        query, run_id, total, passed, failed, critical, overall
    )
    conn.commit()
    
    logger.info(f"\n{'='*60}")
    logger.info(f"DQ Run Complete: {run_id}")
    logger.info(f"Total: {total} | Pass: {passed} | Fail: {failed} | Critical: {critical}")
    logger.info(f"Overall Status: {overall}")
    logger.info(f"{'='*60}")
    
    conn.close()
    return run_id, overall, df

