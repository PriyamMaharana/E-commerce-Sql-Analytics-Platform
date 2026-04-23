## etl - pipeline
## load kaggle csv + live currency rate into sql server

import pandas as pd
import numpy as np
import requests
from datetime import datetime, date
import os, logging
import pyodbc

## Logging Setup
os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler('logs/load_data.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

DATA_PATH = 'dataset/'
API_KEY = '90213c8ddbd50987b3c3957c'  


## Database Connection
def get_connection():
    return pyodbc.connect(
        'DRIVER={ODBC Driver 17 for SQL Server};'
        'SERVER=localhost;'
        'DATABASE=Ecommerce_Analytics;'
        'Trusted_Connection=yes;'
        'TrustServerCertificate=yes;'
    )


### 1. Get exchange rate
def get_exchange_rate():
    try:
        url = f"https://v6.exchangerate-api.com/v6/{API_KEY}/pair/BRL/INR"
        response = requests.get(url, timeout=10)
        data = response.json()

        if data.get('result') == 'success':
            rate = data['conversion_rate']
            logger.info(f"Live exchange rate: 1 BRL = {rate} INR")
            return rate
        else:
            logger.warning("API failed - using fallback rate 18.5")
            return 18.5

    except Exception as e:
        logger.warning(f"API error: {e} - using fallback 18.5")
        return 18.5


## Data cleaning function
def clean_dataframe(df):
    df.columns = [col.lower().strip() for col in df.columns]

    # Replace NaN, inf
    df = df.replace({np.nan: None})
    df = df.replace([np.inf, -np.inf], None)

    # Clean numeric columns
    for col in df.columns:
        if df[col].dtype in ['float64', 'int64']:
            df[col] = pd.to_numeric(df[col], errors='coerce')
            df[col] = df[col].replace({np.nan: None})

    return df


### 2. Load Stagging Table
def load_staging(conn):
    logger.info("Loading staging tables...")

    files = {
        'stg_orders': 'olist_orders_dataset.csv',
        'stg_order_items': 'olist_order_items_dataset.csv',
        'stg_customers': 'olist_customers_dataset.csv',
        'stg_products': 'olist_products_dataset.csv',
        'stg_sellers': 'olist_sellers_dataset.csv',
        'stg_payments': 'olist_order_payments_dataset.csv',
        'stg_reviews': 'olist_order_reviews_dataset.csv',
    }

    cursor = conn.cursor()
    cursor.fast_executemany = True

    for table, filename in files.items():
        filepath = os.path.join(DATA_PATH, filename)

        if not os.path.exists(filepath):
            logger.warning(f"File not found: {filepath}")
            continue

        logger.info(f"Loading {filename}...")
        df = pd.read_csv(filepath)
        df = clean_dataframe(df)

        cursor.execute(f"TRUNCATE TABLE {table}")

        cols = ', '.join(df.columns)
        placeholders = ','.join(['?' for _ in df.columns])
        sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"

        chunk_size = 5000
        for i in range(0, len(df), chunk_size):
            chunk = df.iloc[i:i+chunk_size]
            cursor.executemany(
                sql,
                [tuple(row) for row in chunk.itertuples(index=False)]
            )

        conn.commit()
        logger.info(f"Loaded {len(df):,} rows into {table}")
        

## Data quality framework - DQ function
def data_quality_check(conn):
    logger.info(f"Running Data Quality Checks...")
    cursor = conn.cursor()
    
    #run sql DQ procedure
    cursor.execute("EXEC usp_dq_checks")
    
    #check failures
    cursor.execute(
        """ select
                r.table_name, r.column_name, r.rule_type, r.severity,
                dr.failed_rows, dr.total_rows, dr.status
            from dq_results dr
            join dq_rules r on dr.rule_id = r.rule_id
            where cast(dr.checked_at as DATE) = cast(getdate() as DATE)
        """
    )
    
    results = cursor.fetchall()
    high_fail = 0
    
    for row in results:
        table, col, rule, severity, failed, total, status = row  
        msg = f"{severity} | {table}.{col} | {rule} | Failed: {failed}/{total} | {status}"
        
        if severity == 'HIGH' and status == 'FAIL':
            logger.error("X "+msg)
            high_fail +=1
        elif severity == 'MEDIUM' and status == 'FAIL':
            logger.warning("! "+msg)
        elif severity == 'LOW' and status == 'FAIL':
            logger.info("i "+msg)
        else:
            logger.info(" "+msg)
        
        # stop only if HIGH
        if high_fail >0:
            raise Exception(f"Stopping pipeline due to HIGH severity failures")
        
        logger.info(f"Data Quality Checks Completed!!")
    

### 3. Laod dim_date
def load_dim_date(conn):
    logger.info("Loading dim_date...")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM dim_date")

    start = date(2016, 1, 1)
    end = date(2019, 12, 31)

    rows = []
    current = start

    while current <= end:
        rows.append((
            int(current.strftime('%Y%m%d')),
            str(current),
            current.day,
            current.month,
            current.strftime('%B'),
            (current.month - 1)//3 + 1,
            current.year,
            1 if current.weekday() >= 5 else 0,
            current.strftime('%A')
        ))
        current = date.fromordinal(current.toordinal() + 1)

    cursor.executemany("""
        INSERT INTO dim_date(
            date_sk, full_date, day, month, month_name,
            quarter, year, is_weekend, day_of_week
        ) VALUES (?,?,?,?,?,?,?,?,?)
    """, rows)

    conn.commit()
    logger.info(f"Loaded {len(rows):,} date rows")


### 4. Load dimensions
def load_dimensions(conn):
    cursor = conn.cursor()

    # dim_customer
    logger.info("Loading dim_customer...")
    cursor.execute("DELETE FROM dim_customer")
    cursor.execute("""
        INSERT INTO dim_customer(customer_id, customer_unique_id, city, state, zip_code)
        SELECT customer_id, customer_unique_id, customer_city, customer_state, customer_zip_code_prefix
        FROM stg_customers
    """)
    conn.commit()

    # dim_seller
    logger.info("Loading dim_seller...")
    cursor.execute("DELETE FROM dim_seller")
    cursor.execute("""
        INSERT INTO dim_seller(seller_id, city, state, zip_code)
        SELECT seller_id, seller_city, seller_state, seller_zip_code_prefix
        FROM stg_sellers
    """)
    conn.commit()

    # dim_product
    logger.info("Loading dim_product...")
    cursor.execute("DELETE FROM dim_product")
    cursor.execute("""
        INSERT INTO dim_product(product_id)
        SELECT DISTINCT product_id FROM stg_products
    """)
    conn.commit()

    logger.info("Dimensions Loaded!")

## clear fact_table
def clear_fact_tables(conn):
    logger.info("Clearing fact tables...")

    cursor = conn.cursor()
    cursor.execute("DELETE FROM fact_orders")
    conn.commit()

### 5. Laod fact_oreds table
def load_fact(conn, rate):
    logger.info("Loading fact_orders...")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM fact_orders")

    query = f"""
        INSERT INTO fact_orders(
            order_id, customer_sk, product_sk, seller_sk, date_sk,
            order_item_id, order_status, price_brl, freight_brl,
            price_inr, freight_inr, payment_value, payment_type,
            review_score, delivery_days, is_late_delivery
        )
        SELECT 
            o.order_id,
            dc.customer_sk,
            dp.product_sk,
            ds.seller_sk,
            CAST(FORMAT(CAST(o.order_purchase_timestamp AS DATE), 'yyyyMMdd') AS INT),
            oi.order_item_id,
            o.order_status,
            oi.price,
            oi.freight_value,
            ROUND(oi.price * {rate}, 2),
            ROUND(oi.freight_value * {rate}, 2),
            ISNULL(p.payment_value, 0),
            ISNULL(p.payment_type, 'unknown'),
            r.review_score,
            CASE 
                WHEN o.order_delivered_customer_date IS NOT NULL
                THEN DATEDIFF(day,
                    CAST(o.order_purchase_timestamp AS DATE),
                    CAST(o.order_delivered_customer_date AS DATE)
                )
                ELSE NULL
            END,
            CASE
                WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date
                THEN 1 ELSE 0
            END
        FROM stg_orders o
        JOIN stg_order_items oi ON o.order_id = oi.order_id
        JOIN dim_customer dc ON o.customer_id = dc.customer_id
        JOIN dim_product dp ON oi.product_id = dp.product_id
        JOIN dim_seller ds ON oi.seller_id = ds.seller_id
        LEFT JOIN (
            SELECT order_id,
                SUM(payment_value) AS payment_value,
                MAX(payment_type) AS payment_type
            FROM stg_payments
            GROUP BY order_id
        ) p ON o.order_id = p.order_id
        LEFT JOIN (
            SELECT order_id,
                AVG(review_score) AS review_score
            FROM stg_reviews
            GROUP BY order_id
        ) r ON o.order_id = r.order_id
        WHERE o.order_purchase_timestamp IS NOT NULL
    """

    cursor.execute(query)
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM fact_orders")
    count = cursor.fetchone()[0]
    logger.info(f"Loaded {count:,} rows into fact_orders")


## Main pipeline
def run_pipeline():
    logger.info("="*60)
    logger.info(f"E-Commerce ETL Pipeline - {datetime.now()}")
    logger.info("="*60)

    rate = get_exchange_rate()
    conn = get_connection()

    try:
        load_staging(conn)
        data_quality_check(conn)
        clear_fact_tables(conn)
        load_dim_date(conn)
        load_dimensions(conn)
        load_fact(conn, rate)

        logger.info("Pipeline Completed Successfully.")

    except Exception as e:
        logger.error(f"Pipeline FAILED: {e}")
        conn.rollback()
        raise

    finally:
        conn.close()


if __name__ == "__main__":
    run_pipeline()
    
