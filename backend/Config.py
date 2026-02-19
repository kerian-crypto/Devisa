# config.py - Configuration pour Render
import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-fx-secret-key-2024'
    
    # Configuration de la base de données
    DATABASE_URL = os.environ.get('DATABASE_URL')
    if DATABASE_URL:
        if DATABASE_URL.startswith("postgres://"):
            DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        # Configuration locale (MySQL)
        SQLALCHEMY_DATABASE_URI = f'sqlite:///app.db'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Configuration Google OAuth (à mettre dans les variables d'environnement sur Render)
    GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID', "votre-client-id-par-defaut")
    GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET', "votre-secret-par-defaut")
    GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
    
    # URL de l'application
    APP_URL = os.environ.get('APP_URL', 'http://127.0.0.1:5000')
    
    # Taux par défaut
    DEFAULT_USDT_RATE = 600
    PROFIT_MARGIN = 0.02  # 2%
    
    
    # Opérateurs mobiles
    MOBILE_OPERATORS = {
        'CM': {
            'MTN': '237671737948',
            'ORANGE': '237696574076'
        },
        'TG': {
            'TOGOCEL': '2289xxxxxxx',
            'MOOV': '2287xxxxxxx'
        },
    }

    # Configuration Admin (à sécuriser dans les variables d'environnement)
    ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL', 'ddevisafx@gmail.com')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'ddevisafxcrypto2025')
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'Devis-Fx')

    ADMIN_NUMBER = os.environ.get('ADMIN_NUMBER', '237696574076')

    # Firebase Cloud Messaging (push hors application)
    FIREBASE_CREDENTIALS_PATH = os.environ.get('FIREBASE_CREDENTIALS_PATH')
    FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get('FIREBASE_SERVICE_ACCOUNT_JSON')
