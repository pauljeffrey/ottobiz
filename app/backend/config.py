"""
Configuration file for Ottobiz backend.
Contains all environment variables and settings.
"""
import os
from dotenv import load_dotenv
from typing import Optional

load_dotenv()

# Debug mode - when True, tier restrictions are disabled
DEBUG = os.getenv("DEBUG", "False").lower() == "true"

# Model Configuration
MODEL_NAME = os.getenv("MODEL_NAME", "gemini-2.0-flash")
MODEL_API_KEY = os.getenv("MODEL_API_KEY", "")
# Coordinator uses this model when set; otherwise MODEL_NAME (stronger model recommended).
CENTRAL_AGENT_MODEL_NAME = os.getenv("CENTRAL_AGENT_MODEL_NAME", "").strip() or MODEL_NAME

# Database Configuration (Supabase/PostgreSQL)
DATABASE_URL = os.getenv("DATABASE_URL", "")
DATABASE_USERNAME = os.getenv("DATABASE_USERNAME", "")
DATABASE_PASSWORD = os.getenv("DATABASE_PASSWORD", "")
DATABASE_HOST = os.getenv("DATABASE_HOST", "")
DATABASE_PORT = os.getenv("DATABASE_PORT", "5432")
DATABASE_NAME = os.getenv("DATABASE_NAME", "")

# Redis Configuration
REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_SERVER_HOST = os.getenv("REDIS_SERVER_HOST", "localhost")
REDIS_SERVER_PORT = int(os.getenv("REDIS_SERVER_PORT", "6379"))
REDIS_SERVER_PASSWORD = os.getenv("REDIS_SERVER_PASSWORD", "")

# Supabase Configuration
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

# Paystack Configuration (Optional)
PAYSTACK_PUBLIC_KEY = os.getenv("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_SECRET_KEY = os.getenv("PAYSTACK_SECRET_KEY", "")
PAYSTACK_DEFAULT_CURRENCY = os.getenv("PAYSTACK_DEFAULT_CURRENCY", "NGN")

# WhatsApp Configuration
WHATSAPP_API_KEY = os.getenv("WHATSAPP_API_KEY", "")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# Business Tier Plans
TIER_FREE = "free"
TIER_GOLD = "gold"
TIER_PLATINUM = "platinum"

# Logging
LOG_FILE = os.getenv("LOG_FILE", "app.log")

# File uploads: when true, also upload bytes to S3 (requires boto3 + AWS env).
SAVE_UPLOADS_TO_S3 = os.getenv("SAVE_UPLOADS_TO_S3", "false").lower() == "true"
AWS_S3_BUCKET = os.getenv("AWS_S3_BUCKET", "")
AWS_S3_REGION = os.getenv("AWS_S3_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
BASE_URL = os.getenv("BASE_URL", "")  # Required for webhook callbacks and file download links

# Chat & context management
CHAT_HISTORY_SUMMARY_WORD_LIMIT = int(os.getenv("CHAT_HISTORY_SUMMARY_WORD_LIMIT", "2048"))
CHAT_HISTORY_KEEP_LAST_N = int(os.getenv("CHAT_HISTORY_KEEP_LAST_N", "20"))
COMM_HISTORY_SUMMARY_WORD_LIMIT = int(os.getenv("COMM_HISTORY_SUMMARY_WORD_LIMIT", "1024"))
COMM_HISTORY_KEEP_LAST_N = int(os.getenv("COMM_HISTORY_KEEP_LAST_N", "10"))
FILE_TEXT_CACHE_MAX = int(os.getenv("FILE_TEXT_CACHE_MAX", "5"))
PRODUCTS_CACHE_TTL_HOURS = int(os.getenv("PRODUCTS_CACHE_TTL_HOURS", "6"))
# Cap Redis list paystack_webhook_confirmed (webhook also persists to Postgres).
PAYSTACK_WEBHOOK_CONFIRMED_MAX = int(os.getenv("PAYSTACK_WEBHOOK_CONFIRMED_MAX", "50"))
# Bank transfer / receipt: auto-verification in payment agent (not Paystack)
BANK_RECEIPT_MAX_AGE_HOURS = int(os.getenv("BANK_RECEIPT_MAX_AGE_HOURS", "72"))
BANK_RECEIPT_AMOUNT_TOLERANCE = float(os.getenv("BANK_RECEIPT_AMOUNT_TOLERANCE", "0.001"))

# Rate limiting (requests per window). Off by default; set RATE_LIMIT_ENABLED=true to enable.
RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "false").lower() == "true"
RATE_LIMIT_REQUESTS = int(os.getenv("RATE_LIMIT_REQUESTS", "60"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))


class Config:
    """Configuration class for easy access"""
    DEBUG = DEBUG
    MODEL_NAME = MODEL_NAME
    MODEL_API_KEY = MODEL_API_KEY
    CENTRAL_AGENT_MODEL_NAME = CENTRAL_AGENT_MODEL_NAME
    DATABASE_URL = DATABASE_URL
    REDIS_URL = REDIS_URL
    SUPABASE_URL = SUPABASE_URL
    SUPABASE_KEY = SUPABASE_KEY
    PAYSTACK_PUBLIC_KEY = PAYSTACK_PUBLIC_KEY
    PAYSTACK_SECRET_KEY = PAYSTACK_SECRET_KEY
    PAYSTACK_DEFAULT_CURRENCY = PAYSTACK_DEFAULT_CURRENCY
    WHATSAPP_API_KEY = WHATSAPP_API_KEY
    WHATSAPP_PHONE_NUMBER_ID = WHATSAPP_PHONE_NUMBER_ID
    SAVE_UPLOADS_TO_S3 = SAVE_UPLOADS_TO_S3
    AWS_S3_BUCKET = AWS_S3_BUCKET
    AWS_S3_REGION = AWS_S3_REGION
    BASE_URL = BASE_URL
    RATE_LIMIT_ENABLED = RATE_LIMIT_ENABLED

config = Config()

