import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'sqlite:///bidz.db')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    AI_PROVIDER = os.getenv('AI_PROVIDER', 'openrouter')
    AI_API_KEY = os.getenv('AI_API_KEY', '')
    AI_MODEL = os.getenv('AI_MODEL', '')
    AI_BASE_URL = os.getenv('AI_BASE_URL', '')
    SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
    SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
    SMTP_USER = os.getenv('SMTP_USER', '')
    SMTP_PASS = os.getenv('SMTP_PASS', '')
    EMAIL_FROM = os.getenv('EMAIL_FROM', '')
    PORT = int(os.getenv('PORT', 8080))
    SECRET_KEY = os.getenv('SECRET_KEY', 'change-me-in-production')
