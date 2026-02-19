# app.py (extrait)
from datetime import datetime

import uuid
from flask import Flask, request
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from sqlalchemy import inspect, text
from models import db, Utilisateur
from api_routes import api_bp
from auth import auth_bp  # si vous conservez les routes web
from Config import Config

app = Flask(__name__)
app.config.from_object(Config)
from werkzeug.security import generate_password_hash
import uuid
from datetime import datetime



@app.before_request
def log_request():
    print("Requête reçue :", request.method, request.path)

# Initialisation des extensions
db.init_app(app)


def _ensure_sqlite_schema_updates():
    """Ajoute les colonnes manquantes pour les bases SQLite existantes."""
    engine = db.engine
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "utilisateurs" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("utilisateurs")}
    statements = []

    if "est_admin" not in existing_columns:
        statements.append(
            "ALTER TABLE utilisateurs ADD COLUMN est_admin BOOLEAN NOT NULL DEFAULT 0"
        )
    if "est_actif" not in existing_columns:
        statements.append(
            "ALTER TABLE utilisateurs ADD COLUMN est_actif BOOLEAN NOT NULL DEFAULT 1"
        )

    if not statements:
        return

    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))


def _ensure_default_admin():
    """Crée (ou met à jour) l'admin par défaut au démarrage."""
    admin_email = Config.ADMIN_EMAIL
    admin_password = Config.ADMIN_PASSWORD
    admin_name = Config.ADMIN_USERNAME or "Admin"
    admin_phone = Config.ADMIN_NUMBER or f"admin_{uuid.uuid4().hex[:10]}"

    admin_user = Utilisateur.query.filter_by(email=admin_email).first()
    if admin_user:
        updated = False
        if not admin_user.est_admin:
            admin_user.est_admin = True
            updated = True
        if not admin_user.est_actif:
            admin_user.est_actif = True
            updated = True
        if not admin_user.mot_de_passe_hash:
            admin_user.mot_de_passe_hash = admin_password
            updated = True
        if updated:
            db.session.commit()
            print(f"[INIT] Admin existant mis à jour: {admin_email}")
        return

    if Utilisateur.query.filter_by(telephone=admin_phone).first():
        admin_phone = f"admin_{uuid.uuid4().hex[:10]}"

    admin_user = Utilisateur(
        nom=admin_name,
        telephone=admin_phone,
        email=admin_email,
        pays="CM",
        mot_de_passe_hash=admin_password,
        email_verifie=True,
        est_admin=True,
        est_actif=True,
    )
    db.session.add(admin_user)
    db.session.commit()
    print(f"[INIT] Admin créé: {admin_email}")


with app.app_context():
    db.create_all()
    _ensure_sqlite_schema_updates()
    _ensure_default_admin()

app.config.from_object(Config)
JWTManager(app)
CORS(app)  # Autorise les requêtes depuis votre application Flutter

# Enregistrement des blueprints
app.register_blueprint(api_bp)
app.register_blueprint(auth_bp)

if __name__=='__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
