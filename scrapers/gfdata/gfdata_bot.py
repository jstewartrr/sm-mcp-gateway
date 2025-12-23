"""
GF Data Automation Bot
======================
Automated extraction of PE transaction data from GF Data portal.
Uses Playwright for browser automation and Snowflake for data storage.

Author: Sovereign Mind Intelligence System
Created: December 2024
"""

import asyncio
import os
import json
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
import snowflake.connector
from playwright.async_api import async_playwright, Page, Browser

# Configuration
GFDATA_LOGIN_URL = "https://gfdata.sigmify.com/signin.html"
GFDATA_DASHBOARD_URL = "https://gfdata.sigmify.com/dashboard"
DOWNLOAD_DIR = Path("/tmp/gfdata_downloads")


class SnowflakeCredentialStore:
    """Retrieve credentials from Snowflake secure storage."""
    
    def __init__(self):
        self.conn = snowflake.connector.connect(
            user=os.environ.get('SNOWFLAKE_USER', 'JOHN_CLAUDE'),
            password=os.environ.get('SNOWFLAKE_PASSWORD'),
            account=os.environ.get('SNOWFLAKE_ACCOUNT'),
            warehouse=os.environ.get('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH'),
            database='SOVEREIGN_MIND',
            schema='CREDENTIALS'
        )
    
    def get_credential(self, service_name: str, credential_type: str) -> Optional[str]:
        """Retrieve a credential value from secure storage."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                SELECT credential_value 
                FROM SERVICE_CREDENTIALS 
                WHERE service_name = %s 
                AND credential_type = %s 
                AND is_active = TRUE
            """, (service_name, credential_type))
            result = cursor.fetchone()
            return result[0] if result else None
        finally:
            cursor.close()
    
    def update_last_used(self, service_name: str):
        """Update the last_used_at timestamp for a service."""
        cursor = self.conn.cursor()
        try:
            cursor.execute("""
                UPDATE SERVICE_CREDENTIALS 
                SET last_used_at = CURRENT_TIMESTAMP()
                WHERE service_name = %s
            """, (service_name,))
            self.conn.commit()
        finally:
            cursor.close()
    
    def close(self):
        self.conn.close()


class GFDataBot:
    """
    Automated bot for extracting data from GF Data portal.
    
    Features:
    - Secure credential retrieval from Snowflake
    - Browser automation via Playwright
    - Excel download and parsing
    - Direct load to Snowflake MARKET_INTEL schema
    """
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.credential_store = SnowflakeCredentialStore()
        self.download_dir = DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # Snowflake connection for data loading
        self.snowflake_conn = snowflake.connector.connect(
            user=os.environ.get('SNOWFLAKE_USER', 'CLAUDE_FULL_ACCESS'),
            password=os.environ.get('SNOWFLAKE_PASSWORD'),
            account=os.environ.get('SNOWFLAKE_ACCOUNT'),
            warehouse=os.environ.get('SNOWFLAKE_WAREHOUSE', 'COMPUTE_WH'),
            database='HURRICANE',
            schema='MARKET_INTEL'
        )
    
    async def start_browser(self, headless: bool = True):
        """Initialize Playwright browser."""
        playwright = await async_playwright().start()
        self.browser = await playwright.chromium.launch(
            headless=headless,
            args=['--no-sandbox', '--disable-dev-shm-usage']
        )
        context = await self.browser.new_context(
            accept_downloads=True,
            viewport={'width': 1920, 'height': 1080}
        )
        self.page = await context.new_page()
        
        # Set download behavior
        await self.page.context.set_default_timeout(60000)
        
        print("[GFData Bot] Browser initialized")
    
    async def login(self) -> bool:
        """Log into GF Data portal using stored credentials."""
        username = self.credential_store.get_credential('GF_DATA', 'USERNAME')
        password = self.credential_store.get_credential('GF_DATA', 'PASSWORD')
        
        if not username or not password:
            raise ValueError("GF Data credentials not found in secure storage")
        
        print(f"[GFData Bot] Logging in as {username}...")
        
        await self.page.goto(GFDATA_LOGIN_URL)
        await self.page.wait_for_load_state('networkidle')
        
        # Fill login form - adjust selectors based on actual page structure
        await self.page.fill('input[type="email"], input[name="email"], #email', username)
        await self.page.fill('input[type="password"], input[name="password"], #password', password)
        
        # Click login button
        await self.page.click('button[type="submit"], input[type="submit"], .login-btn, #login-btn')
        
        # Wait for navigation to dashboard
        try:
            await self.page.wait_for_url('**/dashboard**', timeout=30000)
            print("[GFData Bot] Login successful")
            self.credential_store.update_last_used('GF_DATA')
            return True
        except Exception as e:
            print(f"[GFData Bot] Login failed: {e}")
            # Take screenshot for debugging
            await self.page.screenshot(path=str(self.download_dir / "login_error.png"))
            return False
    
    async def navigate_to_database(self):
        """Navigate to the valuation database search interface."""
        print("[GFData Bot] Navigating to database...")
        
        # Click on Database link - adjust selector based on actual UI
        await self.page.click('a[href*="database"], .database-link, text="Database"')
        await self.page.wait_for_load_state('networkidle')
        
        print("[GFData Bot] Database page loaded")
    
    async def run_query(self, 
                        naics_codes: Optional[List[str]] = None,
                        deal_date_start: Optional[str] = None,
                        deal_date_end: Optional[str] = None,
                        tev_min: Optional[float] = None,
                        tev_max: Optional[float] = None,
                        ebitda_min: Optional[float] = None,
                        ebitda_max: Optional[float] = None) -> Path:
        """
        Execute a query on GF Data database and download results.
        
        Args:
            naics_codes: List of NAICS codes to filter (e.g., ['423', '332'])
            deal_date_start: Start date for deals (YYYY-MM-DD)
            deal_date_end: End date for deals (YYYY-MM-DD)
            tev_min: Minimum total enterprise value ($M)
            tev_max: Maximum total enterprise value ($M)
            ebitda_min: Minimum EBITDA ($M)
            ebitda_max: Maximum EBITDA ($M)
        
        Returns:
            Path to downloaded Excel file
        """
        print(f"[GFData Bot] Running query with filters:")
        print(f"  NAICS: {naics_codes}")
        print(f"  Date Range: {deal_date_start} to {deal_date_end}")
        print(f"  TEV Range: ${tev_min}M - ${tev_max}M")
        
        # Apply filters - selectors will need adjustment based on actual UI
        if naics_codes:
            for code in naics_codes:
                # Multi-select NAICS codes
                await self.page.click('.naics-filter, #naics-select')
                await self.page.fill('.naics-search, input[placeholder*="NAICS"]', code)
                await self.page.click(f'text="{code}"')
        
        if deal_date_start:
            await self.page.fill('input[name="date_start"], #date-start', deal_date_start)
        
        if deal_date_end:
            await self.page.fill('input[name="date_end"], #date-end', deal_date_end)
        
        if tev_min:
            await self.page.fill('input[name="tev_min"], #tev-min', str(tev_min))
        
        if tev_max:
            await self.page.fill('input[name="tev_max"], #tev-max', str(tev_max))
        
        # Click search/apply button
        await self.page.click('button:has-text("Search"), button:has-text("Apply"), .search-btn')
        await self.page.wait_for_load_state('networkidle')
        
        print("[GFData Bot] Query executed, downloading results...")
        
        # Download to Excel
        download_path = await self._download_excel()
        return download_path
    
    async def _download_excel(self) -> Path:
        """Click download button and save Excel file."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"gfdata_export_{timestamp}.xlsx"
        filepath = self.download_dir / filename
        
        # Start download
        async with self.page.expect_download() as download_info:
            await self.page.click('button:has-text("Excel"), button:has-text("Download"), .export-btn, .download-excel')
        
        download = await download_info.value
        await download.save_as(str(filepath))
        
        print(f"[GFData Bot] Downloaded: {filepath}")
        return filepath
    
    def parse_excel(self, filepath: Path) -> pd.DataFrame:
        """Parse downloaded Excel file into DataFrame."""
        print(f"[GFData Bot] Parsing Excel file: {filepath}")
        
        df = pd.read_excel(filepath)
        
        # Standardize column names
        df.columns = [col.strip().upper().replace(' ', '_').replace('/', '_') for col in df.columns]
        
        # Add metadata
        df['SOURCE_FILE'] = filepath.name
        df['EXTRACTED_AT'] = datetime.now()
        df['SOURCE_ID'] = self._get_gfdata_source_id()
        
        print(f"[GFData Bot] Parsed {len(df)} records")
        return df
    
    def _get_gfdata_source_id(self) -> int:
        """Get the source_id for GF Data from SOURCES table."""
        cursor = self.snowflake_conn.cursor()
        try:
            cursor.execute("""
                SELECT source_id FROM HURRICANE.MARKET_INTEL.SOURCES 
                WHERE source_name = 'GF Data'
            """)
            result = cursor.fetchone()
            return result[0] if result else None
        finally:
            cursor.close()
    
    def load_to_snowflake(self, df: pd.DataFrame, table_name: str = 'GFDATA_TRANSACTIONS'):
        """
        Load parsed data to Snowflake.
        
        Creates table if not exists, then appends data.
        """
        print(f"[GFData Bot] Loading {len(df)} records to HURRICANE.MARKET_INTEL.{table_name}")
        
        cursor = self.snowflake_conn.cursor()
        
        try:
            # Create table if not exists (dynamically based on DataFrame columns)
            columns_sql = ', '.join([
                f'"{col}" VARCHAR' if df[col].dtype == 'object' 
                else f'"{col}" FLOAT' if df[col].dtype in ['float64', 'float32']
                else f'"{col}" INTEGER' if df[col].dtype in ['int64', 'int32']
                else f'"{col}" TIMESTAMP_NTZ' if 'datetime' in str(df[col].dtype)
                else f'"{col}" VARCHAR'
                for col in df.columns
            ])
            
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS HURRICANE.MARKET_INTEL.{table_name} (
                    {columns_sql},
                    LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """)
            
            # Write DataFrame to Snowflake using write_pandas
            from snowflake.connector.pandas_tools import write_pandas
            
            success, nchunks, nrows, _ = write_pandas(
                self.snowflake_conn,
                df,
                table_name,
                database='HURRICANE',
                schema='MARKET_INTEL',
                auto_create_table=False,
                overwrite=False
            )
            
            print(f"[GFData Bot] Loaded {nrows} rows in {nchunks} chunks")
            
            # Log the scrape job
            self._log_scrape_job(len(df), table_name)
            
        finally:
            cursor.close()
    
    def _log_scrape_job(self, records_loaded: int, table_name: str):
        """Log the scrape job to SCRAPE_JOBS table."""
        cursor = self.snowflake_conn.cursor()
        try:
            source_id = self._get_gfdata_source_id()
            cursor.execute("""
                INSERT INTO HURRICANE.MARKET_INTEL.SCRAPE_JOBS 
                (source_id, job_type, job_status, started_at, completed_at, 
                 reports_found, reports_new, scraper_version, execution_environment)
                VALUES (%s, 'SCHEDULED', 'COMPLETED', CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP(),
                        %s, %s, '1.0.0', 'PLAYWRIGHT_BOT')
            """, (source_id, records_loaded, records_loaded))
            self.snowflake_conn.commit()
        finally:
            cursor.close()
    
    async def run_full_extraction(self, query_params: Dict[str, Any]) -> int:
        """
        Run complete extraction workflow:
        1. Login
        2. Navigate to database
        3. Run query
        4. Download Excel
        5. Parse and load to Snowflake
        
        Returns:
            Number of records loaded
        """
        try:
            await self.start_browser(headless=True)
            
            if not await self.login():
                raise Exception("Login failed")
            
            await self.navigate_to_database()
            
            excel_path = await self.run_query(**query_params)
            
            df = self.parse_excel(excel_path)
            
            self.load_to_snowflake(df)
            
            return len(df)
            
        finally:
            await self.close()
    
    async def close(self):
        """Clean up resources."""
        if self.browser:
            await self.browser.close()
        if self.snowflake_conn:
            self.snowflake_conn.close()
        if self.credential_store:
            self.credential_store.close()
        print("[GFData Bot] Shutdown complete")


# Pre-configured query profiles for MGC focus areas
QUERY_PROFILES = {
    'industrial_distribution': {
        'naics_codes': ['423', '424'],  # Wholesale Trade
        'tev_min': 75,
        'tev_max': 400,
    },
    'specialty_manufacturing': {
        'naics_codes': ['332', '333', '334', '335', '336'],  # Manufacturing
        'tev_min': 75,
        'tev_max': 400,
    },
    'metals_and_materials': {
        'naics_codes': ['331', '332'],  # Primary Metals, Fabricated Metal Products
        'tev_min': 50,
        'tev_max': 500,
    },
    'industrial_services': {
        'naics_codes': ['238', '561', '811'],  # Construction, Admin Services, Repair
        'tev_min': 75,
        'tev_max': 400,
    },
    'full_lower_middle_market': {
        'tev_min': 75,
        'tev_max': 400,
    }
}


async def main():
    """Main entry point for scheduled execution."""
    import argparse
    
    parser = argparse.ArgumentParser(description='GF Data Extraction Bot')
    parser.add_argument('--profile', choices=list(QUERY_PROFILES.keys()), 
                        default='full_lower_middle_market',
                        help='Query profile to use')
    parser.add_argument('--days-back', type=int, default=90,
                        help='Number of days back to query')
    parser.add_argument('--headless', action='store_true', default=True,
                        help='Run browser in headless mode')
    
    args = parser.parse_args()
    
    # Build query parameters
    query_params = QUERY_PROFILES[args.profile].copy()
    query_params['deal_date_start'] = (datetime.now() - timedelta(days=args.days_back)).strftime('%Y-%m-%d')
    query_params['deal_date_end'] = datetime.now().strftime('%Y-%m-%d')
    
    print(f"[GFData Bot] Starting extraction with profile: {args.profile}")
    print(f"[GFData Bot] Query params: {query_params}")
    
    bot = GFDataBot()
    records = await bot.run_full_extraction(query_params)
    
    print(f"[GFData Bot] Extraction complete. {records} records loaded.")


if __name__ == '__main__':
    asyncio.run(main())
