"""
GF Data Automation Bot v3.4
===========================
Automated extraction of PE transaction data from GF Data portal.
Uses Playwright for browser automation and Snowflake for data storage.

Author: Sovereign Mind Intelligence System
Created: December 2024
Updated: December 2024 - v3.4 Load to GFDATA_RAW staging table with DROP/CREATE
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

# GF Data UI Configuration - Exact selector values
BUSINESS_CATEGORIES = ['All', 'Distribution', 'Manufacturing']

NAICS_CODES = {
    'agriculture': 'Agriculture (100-115)',
    'construction': 'Construction/Contractors (230-238)',
    'manufacturing': 'Manufacturing (300-340)',
    'repair_maintenance': 'Repair and Maintenance (810-811)',
    'civic_government': 'Civic and Government (813-930)'
}

SORT_OPTIONS = [
    'By TEV Range All Years',
    'By EBITDA Range All Years',
    'By TEV Range - Custom',
    'By EBITDA Range - Custom',
    'By Year All Years',
    'By Quarter All Years'
]


class GFDataBot:
    """
    Automated bot for extracting data from GF Data portal.
    
    Features:
    - Browser automation via Playwright
    - Excel download and parsing
    - Direct load to Snowflake MARKET_INTEL schema
    """
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.download_dir = DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)
        
        # Snowflake connection for data loading
        self.snowflake_conn = snowflake.connector.connect(
            user=os.environ.get('SNOWFLAKE_USER', 'JOHN_CLAUDE'),
            password=os.environ.get('SNOWFLAKE_PASSWORD'),
            account=os.environ.get('SNOWFLAKE_ACCOUNT'),
            warehouse=os.environ.get('SNOWFLAKE_WAREHOUSE', 'SOVEREIGN_MIND_WH'),
            database='HURRICANE',
            schema='MARKET_INTEL'
        )
        
        # Explicitly use warehouse
        cursor = self.snowflake_conn.cursor()
        cursor.execute(f"USE WAREHOUSE {os.environ.get('SNOWFLAKE_WAREHOUSE', 'SOVEREIGN_MIND_WH')}")
        cursor.close()
        
        print(f"[GFData Bot] Initialized - Snowflake connected")
        
        # GF Data credentials - check environment first, then Snowflake
        self.gfdata_username = os.environ.get('GFDATA_USERNAME')
        self.gfdata_password = os.environ.get('GFDATA_PASSWORD')
        
        if not self.gfdata_username or not self.gfdata_password:
            print("[GFData Bot] Credentials not in environment, checking Snowflake...")
            self._load_credentials_from_snowflake()
    
    def _load_credentials_from_snowflake(self):
        """Load GF Data credentials from SOVEREIGN_MIND.CREDENTIALS.SERVICE_CREDENTIALS."""
        cursor = self.snowflake_conn.cursor()
        try:
            cursor.execute("""
                SELECT CREDENTIAL_KEY, CREDENTIAL_VALUE 
                FROM SOVEREIGN_MIND.CREDENTIALS.SERVICE_CREDENTIALS 
                WHERE SERVICE_NAME = 'GF_DATA' 
                AND IS_ACTIVE = TRUE
            """)
            
            for row in cursor.fetchall():
                key, value = row
                if key == 'login_email':
                    self.gfdata_username = value
                    print(f"[GFData Bot] Loaded username from Snowflake: {value}")
                elif key == 'login_password':
                    self.gfdata_password = value
                    print("[GFData Bot] Loaded password from Snowflake")
                    
        except Exception as e:
            print(f"[GFData Bot] Error loading credentials from Snowflake: {e}")
        finally:
            cursor.close()
    
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
        self.page.set_default_timeout(60000)
        
        print("[GFData Bot] Browser initialized")
    
    async def login(self) -> bool:
        """Log into GF Data portal."""
        if not self.gfdata_username or not self.gfdata_password:
            raise ValueError("GF Data credentials not found")
        
        print(f"[GFData Bot] Logging in as {self.gfdata_username}...")
        
        await self.page.goto(GFDATA_LOGIN_URL)
        await self.page.wait_for_load_state('networkidle')
        
        # Take screenshot for debugging
        await self.page.screenshot(path=str(self.download_dir / "01_login_page.png"))
        
        # Try multiple selector strategies for email field
        email_selectors = [
            'input[type="email"]',
            'input[name="email"]',
            'input[placeholder*="email" i]',
            'input[placeholder*="Email" i]',
            '#email',
            'input.email',
            'input[id*="email" i]',
            'input[name*="email" i]'
        ]
        
        email_filled = False
        for selector in email_selectors:
            try:
                if await self.page.locator(selector).count() > 0:
                    await self.page.fill(selector, self.gfdata_username, timeout=5000)
                    email_filled = True
                    print(f"[GFData Bot] Email filled using selector: {selector}")
                    break
            except Exception:
                continue
        
        if not email_filled:
            # Try finding any visible input field
            inputs = await self.page.locator('input:visible').all()
            print(f"[GFData Bot] Found {len(inputs)} visible input fields")
            if len(inputs) >= 1:
                await inputs[0].fill(self.gfdata_username)
                email_filled = True
                print("[GFData Bot] Email filled in first visible input")
        
        # Try multiple selector strategies for password field
        password_selectors = [
            'input[type="password"]',
            'input[name="password"]',
            '#password',
            'input.password',
            'input[id*="password" i]',
            'input[name*="password" i]'
        ]
        
        password_filled = False
        for selector in password_selectors:
            try:
                if await self.page.locator(selector).count() > 0:
                    await self.page.fill(selector, self.gfdata_password, timeout=5000)
                    password_filled = True
                    print(f"[GFData Bot] Password filled using selector: {selector}")
                    break
            except Exception:
                continue
        
        if not password_filled:
            inputs = await self.page.locator('input:visible').all()
            if len(inputs) >= 2:
                await inputs[1].fill(self.gfdata_password)
                password_filled = True
                print("[GFData Bot] Password filled in second visible input")
        
        await self.page.screenshot(path=str(self.download_dir / "02_credentials_entered.png"))
        
        # Click login/submit button
        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            'button:has-text("Sign In")',
            'button:has-text("Login")',
            'button:has-text("Log In")',
            'button:has-text("Submit")',
            '.login-btn',
            '#login-btn',
            'button.btn-primary',
            'button:visible'
        ]
        
        for selector in submit_selectors:
            try:
                if await self.page.locator(selector).count() > 0:
                    await self.page.click(selector, timeout=5000)
                    print(f"[GFData Bot] Clicked submit using selector: {selector}")
                    break
            except Exception:
                continue
        
        # Wait for navigation
        try:
            await self.page.wait_for_load_state('networkidle', timeout=30000)
            await asyncio.sleep(3)  # Extra wait for JS
            
            await self.page.screenshot(path=str(self.download_dir / "03_after_login.png"))
            
            current_url = self.page.url
            print(f"[GFData Bot] Current URL after login: {current_url}")
            
            if 'signin' not in current_url.lower() and 'login' not in current_url.lower():
                print("[GFData Bot] Login successful")
                return True
            else:
                print("[GFData Bot] Still on login page - login may have failed")
                return False
                
        except Exception as e:
            print(f"[GFData Bot] Login navigation error: {e}")
            await self.page.screenshot(path=str(self.download_dir / "login_error.png"))
            return False
    
    async def navigate_to_database(self):
        """Navigate to the valuation database search interface."""
        print("[GFData Bot] Navigating to database...")
        
        # Try various navigation approaches
        nav_selectors = [
            'a:has-text("Database")',
            'a[href*="database"]',
            'text=Database',
            '.nav >> text=Database',
            'a:has-text("Search")',
            'a:has-text("Valuation")'
        ]
        
        for selector in nav_selectors:
            try:
                if await self.page.locator(selector).count() > 0:
                    await self.page.click(selector, timeout=10000)
                    print(f"[GFData Bot] Navigated using: {selector}")
                    break
            except Exception:
                continue
        
        await self.page.wait_for_load_state('networkidle')
        await self.page.screenshot(path=str(self.download_dir / "04_database_page.png"))
        print("[GFData Bot] Database page loaded")
    
    async def configure_search(self, 
                               business_category: str = 'All',
                               naics_codes: List[str] = None,
                               sort_by: str = 'By TEV Range - Custom',
                               tev_min: float = None,
                               tev_max: float = None):
        """
        Configure search filters on GF Data.
        
        Args:
            business_category: 'All', 'Distribution', or 'Manufacturing'
            naics_codes: List of NAICS code keys from NAICS_CODES dict
            sort_by: Sort option from SORT_OPTIONS
            tev_min: Minimum TEV in $M (for custom range)
            tev_max: Maximum TEV in $M (for custom range)
        """
        print(f"[GFData Bot] Configuring search...")
        print(f"  Business Category: {business_category}")
        print(f"  NAICS Codes: {naics_codes}")
        print(f"  Sort By: {sort_by}")
        if tev_min or tev_max:
            print(f"  TEV Range: ${tev_min}M - ${tev_max}M")
        
        # 1. Select Business Category dropdown
        try:
            category_selectors = [
                'select:near(:text("Business Category"))',
                'select:near(:text("Select Business Category"))',
                'select:first-of-type',
                '#businessCategory',
                'select[name*="business" i]',
                'select[name*="category" i]',
                '.business-category select'
            ]
            
            for selector in category_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0:
                        await locator.select_option(label=business_category, timeout=5000)
                        print(f"[GFData Bot] Selected business category '{business_category}' via: {selector}")
                        break
                except Exception as e:
                    continue
            
            # Fallback: click on dropdown and select option
            if business_category != 'All':
                try:
                    await self.page.click(f'text="{business_category}"', timeout=3000)
                    print(f"[GFData Bot] Clicked business category text: {business_category}")
                except:
                    pass
                    
        except Exception as e:
            print(f"[GFData Bot] Could not set business category: {e}")
        
        await asyncio.sleep(0.5)
        
        # 2. Select NAICS codes
        if naics_codes:
            try:
                naics_selectors = [
                    'select:near(:text("NAICS"))',
                    'select:near(:text("Select NAICS"))',
                    'select:nth-of-type(2)',
                    '#naicsCode',
                    'select[name*="naics" i]',
                    '.naics-select select'
                ]
                
                for naics_key in naics_codes:
                    # Get the full display value like "Manufacturing (300-340)"
                    naics_value = NAICS_CODES.get(naics_key, naics_key)
                    print(f"[GFData Bot] Selecting NAICS: {naics_value}")
                    
                    selected = False
                    for selector in naics_selectors:
                        try:
                            locator = self.page.locator(selector)
                            if await locator.count() > 0:
                                await locator.select_option(label=naics_value, timeout=3000)
                                print(f"[GFData Bot] Selected NAICS via: {selector}")
                                selected = True
                                break
                        except:
                            continue
                    
                    # Fallback: try clicking the text directly
                    if not selected:
                        try:
                            await self.page.click(f'text="{naics_value}"', timeout=3000)
                            print(f"[GFData Bot] Clicked NAICS text: {naics_value}")
                        except:
                            pass
                            
            except Exception as e:
                print(f"[GFData Bot] Could not set NAICS codes: {e}")
        
        await asyncio.sleep(0.5)
        
        # 3. Select Sort By option
        try:
            sort_selectors = [
                'select:near(:text("Sort By"))',
                'select:near(:text("Sort"))',
                'select:nth-of-type(3)',
                '#sortBy',
                'select[name*="sort" i]',
                '.sort-select select'
            ]
            
            for selector in sort_selectors:
                try:
                    locator = self.page.locator(selector)
                    if await locator.count() > 0:
                        await locator.select_option(label=sort_by, timeout=5000)
                        print(f"[GFData Bot] Selected sort '{sort_by}' via: {selector}")
                        break
                except:
                    continue
                    
        except Exception as e:
            print(f"[GFData Bot] Could not set sort option: {e}")
        
        await asyncio.sleep(0.5)
        
        # 4. If custom TEV range, set min/max values
        if 'Custom' in sort_by and (tev_min is not None or tev_max is not None):
            await asyncio.sleep(1)  # Wait for custom fields to appear
            
            if tev_min is not None:
                tev_min_selectors = [
                    'input[name*="min" i]',
                    'input[placeholder*="min" i]',
                    'input:near(:text("Min"))',
                    'input:near(:text("From"))',
                    '#tevMin',
                    '#minTev',
                    'input.min-value',
                    'input[type="number"]:first-of-type'
                ]
                for selector in tev_min_selectors:
                    try:
                        locator = self.page.locator(selector)
                        if await locator.count() > 0:
                            await locator.fill(str(int(tev_min)), timeout=3000)
                            print(f"[GFData Bot] Set TEV min: ${tev_min}M via {selector}")
                            break
                    except:
                        continue
            
            if tev_max is not None:
                tev_max_selectors = [
                    'input[name*="max" i]',
                    'input[placeholder*="max" i]',
                    'input:near(:text("Max"))',
                    'input:near(:text("To"))',
                    '#tevMax',
                    '#maxTev',
                    'input.max-value',
                    'input[type="number"]:last-of-type'
                ]
                for selector in tev_max_selectors:
                    try:
                        locator = self.page.locator(selector)
                        if await locator.count() > 0:
                            await locator.fill(str(int(tev_max)), timeout=3000)
                            print(f"[GFData Bot] Set TEV max: ${tev_max}M via {selector}")
                            break
                    except:
                        continue
        
        await self.page.screenshot(path=str(self.download_dir / "05_filters_configured.png"))
        print("[GFData Bot] Search filters configured")
    
    async def execute_search_and_download(self) -> Path:
        """Execute the search and download results to Excel."""
        print("[GFData Bot] Executing search...")
        
        # Click search/apply/submit button
        search_selectors = [
            'button:has-text("Search")',
            'button:has-text("Apply")',
            'button:has-text("Submit")',
            'button:has-text("Go")',
            'button:has-text("Filter")',
            'input[type="submit"]',
            'button.search-btn',
            'button.btn-primary',
            '#searchBtn'
        ]
        
        for selector in search_selectors:
            try:
                locator = self.page.locator(selector)
                if await locator.count() > 0:
                    await locator.click(timeout=10000)
                    print(f"[GFData Bot] Clicked search: {selector}")
                    break
            except Exception:
                continue
        
        await self.page.wait_for_load_state('networkidle')
        await asyncio.sleep(3)  # Wait for results to load
        
        await self.page.screenshot(path=str(self.download_dir / "06_search_results.png"))
        
        # Download to Excel - Handle javascript:void(0) button
        print("[GFData Bot] Downloading results...")
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"gfdata_export_{timestamp}.xlsx"
        filepath = self.download_dir / filename
        
        # Selectors for Export to Excel button (javascript:void(0) triggered)
        download_selectors = [
            # EXACT match for GF Data UI - the button uses javascript:void(0)
            'a:has-text("Export to Excel")',
            'button:has-text("Export to Excel")',
            'a[href="javascript:void(0);"]:has-text("Export")',
            'a[href="javascript:void(0);"]:has-text("Excel")',
            ':text("Export to Excel")',
            # Fallbacks
            'button:has-text("Excel")',
            'button:has-text("Download")',
            'button:has-text("Export")',
            'a:has-text("Excel")',
            'a:has-text("Download")',
            'a:has-text("Export")',
            '.export-btn',
            '.download-excel',
            'button[title*="Excel" i]',
            '#exportExcel',
            '#downloadBtn'
        ]
        
        # Find and click the export button
        export_button = None
        for selector in download_selectors:
            try:
                locator = self.page.locator(selector)
                if await locator.count() > 0:
                    export_button = locator.first
                    print(f"[GFData Bot] Found export button: {selector}")
                    break
            except Exception:
                continue
        
        if not export_button:
            await self.page.screenshot(path=str(self.download_dir / "no_export_button.png"))
            raise Exception("Could not find Export to Excel button")
        
        # Set up download handler BEFORE clicking
        # For javascript:void(0) buttons, the download is triggered by JS onclick
        try:
            # Method 1: Use expect_download with the click inside
            async with self.page.expect_download(timeout=90000) as download_info:
                await export_button.click(timeout=10000)
                print("[GFData Bot] Clicked export button, waiting for download...")
            
            download = await download_info.value
            await download.save_as(str(filepath))
            print(f"[GFData Bot] Downloaded: {filepath}")
            
        except Exception as e:
            print(f"[GFData Bot] Method 1 failed: {e}")
            
            # Method 2: Click first, then wait for download event
            try:
                print("[GFData Bot] Trying alternative download method...")
                
                # Set up a download listener
                download_promise = asyncio.create_task(
                    self.page.wait_for_event('download', timeout=90000)
                )
                
                # Click the button
                await export_button.click(timeout=10000)
                print("[GFData Bot] Clicked export, waiting for download event...")
                
                # Wait for download
                download = await download_promise
                await download.save_as(str(filepath))
                print(f"[GFData Bot] Downloaded via method 2: {filepath}")
                
            except Exception as e2:
                print(f"[GFData Bot] Method 2 failed: {e2}")
                
                # Method 3: Check if file was downloaded to default location
                try:
                    print("[GFData Bot] Trying method 3: Check for recent downloads...")
                    await asyncio.sleep(10)  # Wait for potential download
                    
                    # Look for recently created xlsx files
                    import glob
                    recent_files = glob.glob("/tmp/*.xlsx") + glob.glob("/tmp/gfdata_downloads/*.xlsx")
                    if recent_files:
                        most_recent = max(recent_files, key=os.path.getctime)
                        if os.path.getctime(most_recent) > (datetime.now().timestamp() - 60):
                            import shutil
                            shutil.copy(most_recent, str(filepath))
                            print(f"[GFData Bot] Found download at: {most_recent}")
                        else:
                            raise Exception("No recent download found")
                    else:
                        raise Exception("No xlsx files found")
                        
                except Exception as e3:
                    print(f"[GFData Bot] Method 3 failed: {e3}")
                    await self.page.screenshot(path=str(self.download_dir / "download_error.png"))
                    raise Exception(f"All download methods failed. Last error: {e3}")
        
        return filepath
    
    def parse_excel(self, filepath: Path) -> pd.DataFrame:
        """Parse downloaded Excel file into DataFrame."""
        print(f"[GFData Bot] Parsing Excel file: {filepath}")
        
        df = pd.read_excel(filepath)
        
        # Standardize column names - make SQL-safe
        df.columns = [str(col).strip().upper().replace(' ', '_').replace('/', '_').replace('-', '_') for col in df.columns]
        
        # CRITICAL FIX: Convert all columns to strings to avoid mixed type errors
        # This handles the "ALL" column and any other columns with mixed types
        for col in df.columns:
            df[col] = df[col].astype(str)
            # Replace 'nan' strings with None for proper NULL handling
            df[col] = df[col].replace('nan', None)
            df[col] = df[col].replace('None', None)
        
        # Add metadata
        df['SOURCE_FILE'] = filepath.name
        df['EXTRACTED_AT'] = datetime.now().isoformat()
        df['SOURCE_ID'] = str(self._get_gfdata_source_id())
        
        print(f"[GFData Bot] Parsed {len(df)} records with columns: {list(df.columns)}")
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
        except:
            return None
        finally:
            cursor.close()
    
    def load_to_snowflake(self, df: pd.DataFrame, table_name: str = 'GFDATA_RAW'):
        """
        Load parsed data to Snowflake staging table.
        
        Uses DROP/CREATE to handle schema changes from Excel exports.
        Raw data goes to GFDATA_RAW for later transformation to GFDATA_TRANSACTIONS.
        """
        print(f"[GFData Bot] Loading {len(df)} records to HURRICANE.MARKET_INTEL.{table_name}")
        
        cursor = self.snowflake_conn.cursor()
        
        try:
            # Drop existing table to handle schema changes
            print(f"[GFData Bot] Dropping existing {table_name} table if exists...")
            cursor.execute(f"DROP TABLE IF EXISTS HURRICANE.MARKET_INTEL.{table_name}")
            
            # Build column definitions - all VARCHAR for raw data
            columns_sql = ', '.join([f'"{col}" VARCHAR' for col in df.columns])
            
            print(f"[GFData Bot] Creating {table_name} with {len(df.columns)} columns...")
            cursor.execute(f"""
                CREATE TABLE HURRICANE.MARKET_INTEL.{table_name} (
                    {columns_sql},
                    LOADED_AT TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
                )
            """)
            
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
            self._log_scrape_job(len(df), table_name)
            
        except Exception as e:
            print(f"[GFData Bot] Error loading to Snowflake: {e}")
            raise
            
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
                        %s, %s, '3.4.0', 'PLAYWRIGHT_BOT')
            """, (source_id, records_loaded, records_loaded))
            self.snowflake_conn.commit()
        except:
            pass
        finally:
            cursor.close()
    
    async def run_full_extraction(self, query_params: Dict[str, Any]) -> int:
        """Run complete extraction workflow."""
        try:
            await self.start_browser(headless=True)
            
            if not await self.login():
                raise Exception("Login failed")
            
            await self.navigate_to_database()
            
            await self.configure_search(
                business_category=query_params.get('business_category', 'All'),
                naics_codes=query_params.get('naics_codes'),
                sort_by=query_params.get('sort_by', 'By TEV Range - Custom'),
                tev_min=query_params.get('tev_min'),
                tev_max=query_params.get('tev_max')
            )
            
            excel_path = await self.execute_search_and_download()
            
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
        print("[GFData Bot] Shutdown complete")


# Pre-configured query profiles for MGC focus areas
QUERY_PROFILES = {
    'mgc_core': {
        'business_category': 'All',
        'naics_codes': ['construction', 'manufacturing', 'repair_maintenance'],
        'sort_by': 'By TEV Range - Custom',
        'tev_min': 75,
        'tev_max': 400,
    },
    'distribution_only': {
        'business_category': 'Distribution',
        'naics_codes': None,
        'sort_by': 'By TEV Range - Custom',
        'tev_min': 75,
        'tev_max': 400,
    },
    'manufacturing_only': {
        'business_category': 'Manufacturing',
        'naics_codes': ['manufacturing'],
        'sort_by': 'By TEV Range - Custom',
        'tev_min': 75,
        'tev_max': 400,
    },
    'full_lower_middle_market': {
        'business_category': 'All',
        'naics_codes': None,
        'sort_by': 'By TEV Range - Custom',
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
    
    args = parser.parse_args()
    
    query_params = QUERY_PROFILES[args.profile].copy()
    
    print(f"[GFData Bot] Starting extraction with profile: {args.profile}")
    print(f"[GFData Bot] Query params: {query_params}")
    
    bot = GFDataBot()
    records = await bot.run_full_extraction(query_params)
    
    print(f"[GFData Bot] Extraction complete. {records} records loaded.")


if __name__ == '__main__':
    asyncio.run(main())
