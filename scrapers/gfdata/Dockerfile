FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browsers
RUN playwright install chromium

# Copy bot code
COPY gfdata_bot.py .

# Set environment variables (override at runtime)
ENV SNOWFLAKE_ACCOUNT=""
ENV SNOWFLAKE_USER=""
ENV SNOWFLAKE_PASSWORD=""
ENV SNOWFLAKE_WAREHOUSE="COMPUTE_WH"

# Run the bot
CMD ["python", "gfdata_bot.py", "--profile", "full_lower_middle_market", "--days-back", "90"]
