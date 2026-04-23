# dq_runner.py
# Master runner — ETL + DQ + Monitoring in one command

import logging
import os
import uuid
from datetime import datetime

os.makedirs('logs', exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.FileHandler(
            f"logs/pipeline_{datetime.now().strftime('%Y%m%d')}.log"
        ),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

from dq_framework import run_dq_checks
from monitoring_dashboard import run_monitoring

def run_full_pipeline():
    logger.info("=" * 60)
    logger.info("ECOMMERCE ANALYTICS — FULL PIPELINE")
    logger.info(f"Started: {datetime.now()}")
    logger.info("=" * 60)

    # Step 1: Run DQ checks
    run_id, overall, results = run_dq_checks()

    # Step 2: Generate monitoring dashboard
    report = run_monitoring()

    # Step 3: Open report in browser automatically
    import webbrowser
    if report:
        webbrowser.open(f"file://{os.path.abspath(report)}")
    else:
        print("Report not generated")

    logger.info(f"\nPipeline complete.")
    logger.info(f"DQ Status:  {overall}")
    logger.info(f"Report:     {report}")
    logger.info("=" * 60)

if __name__ == "__main__":
    run_full_pipeline()