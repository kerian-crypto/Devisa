"""
Modèles de base de données pour Devisa-FX
Flask-SQLAlchemy ORM Models
"""

from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import uuid

db = SQLAlchemy()


class Utilisateur(UserMixin, db.Model):
    """
    Modèle utilisateur pour l'authentification et la gestion des comptes
    """
    __tablename__ = 'utilisateurs'
    
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(100), nullable=False)
    telephone = db.Column(db.String(20), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    pays = db.Column(db.String(50), nullable=False)
    mot_de_passe_hash = db.Column(db.String(200))
    email_verifie = db.Column(db.Boolean, default=False)
    google_id = db.Column(db.String(100), unique=True)
    date_inscription = db.Column(db.DateTime, default=datetime.utcnow)
    est_admin = db.Column(db.Boolean, default=False)
    est_actif = db.Column(db.Boolean, default=True)
    
    # Relations
    transactions = db.relationship('Transaction', backref='utilisateur', lazy=True, foreign_keys='Transaction.utilisateur_id')
    notifications = db.relationship('Notification', backref='utilisateur', lazy=True, foreign_keys='Notification.utilisateur_id')
    push_tokens = db.relationship('PushToken', backref='proprietaire', lazy=True)
    
    def __repr__(self):
        return f'<Utilisateur {self.nom} ({self.email})>'

    def to_dict(self):
        return {
            "id": self.id,
            "nom": self.nom,
            "email": self.email,
            "telephone": self.telephone,
            "pays": self.pays,
            "email_verifie": self.email_verifie,
            "est_admin": self.est_admin,
            "est_actif": self.est_actif,
            "date_inscription": self.date_inscription.isoformat()
        }


class Transaction(db.Model):
    """
    Modèle pour les transactions d'achat et de vente de USDT
    """
    __tablename__ = 'transactions'
    
    id = db.Column(db.Integer, primary_key=True)
    identifiant_transaction = db.Column(db.String(36), unique=True, default=lambda: str(uuid.uuid4()))
    utilisateur_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False)
    
    # Type et montants
    type_transaction = db.Column(db.Enum('achat', 'vente', name='type_transaction_enum'), nullable=False)
    montant_xaf = db.Column(db.Float, nullable=False)
    montant_usdt = db.Column(db.Float, nullable=False)
    taux_applique = db.Column(db.Float, nullable=False)
    
    # Informations réseau et wallet
    reseau = db.Column(db.String(50), nullable=False)  # TRC20, ETHEREUM, SOL, USDT_TON, USDT_APTOS
    adresse_wallet = db.Column(db.String(100))  # Adresse wallet du client
    
    # Informations mobile money
    operateur_mobile = db.Column(db.String(50))  # MTN, ORANGE, etc.
    numero_marchand = db.Column(db.String(20))  # Numéro marchand pour le paiement
    
    # Statut et validation
    statut = db.Column(
        db.Enum('en_attente', 'valide', 'rejete', 'complete', name='statut_transaction_enum'),
        default='en_attente'
    )
    motif_rejet = db.Column(db.Text)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_validation = db.Column(db.DateTime)
    
    # Preuves de paiement
    preuve_paiement = db.Column(db.String(200))  # Chemin vers l'image uploadée
    reference_paiement = db.Column(db.String(100))  # Référence de transaction
    
    def __repr__(self):
        return f'<Transaction {self.identifiant_transaction} - {self.type_transaction} - {self.statut}>'
    
    def to_dict(self):
        """Convertir la transaction en dictionnaire"""
        return {
            'id': self.id,
            'identifiant_transaction': self.identifiant_transaction,
            'utilisateur': {
                'nom': self.utilisateur.nom,
                'email': self.utilisateur.email,
                'telephone': self.utilisateur.telephone
            },
            'type_transaction': self.type_transaction,
            'montant_xaf': self.montant_xaf,
            'montant_usdt': self.montant_usdt,
            'taux_applique': self.taux_applique,
            'reseau': self.reseau,
            'statut': self.statut,
            'date_creation': self.date_creation.isoformat() if self.date_creation else None,
            'date_validation': self.date_validation.isoformat() if self.date_validation else None
        }


class PortefeuilleAdmin(db.Model):
    """
    Modèle pour stocker les portefeuilles administrateurs
    - Type 'mobile_money': stocke les numéros marchands pour les paiements mobile money
    - Type 'crypto': stocke les adresses crypto par réseau pour recevoir les USDT
    """
    __tablename__ = 'portefeuilles_admin'
    
    id = db.Column(db.Integer, primary_key=True)
    reseau = db.Column(db.String(50), nullable=False)  # TRC20, ETHEREUM, SOL, MTN, ORANGE, etc.
    adresse = db.Column(db.String(200), nullable=False)  # Adresse crypto ou numéro marchand
    pays = db.Column(db.String(50))  # Pays du portefeuille (optionnel)
    type_portefeuille = db.Column(
        db.Enum('crypto', 'mobile_money', name='type_portefeuille_enum'),
        nullable=False
    )
    est_actif = db.Column(db.Boolean, default=True)
    date_ajout = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<PortefeuilleAdmin {self.type_portefeuille} - {self.reseau} - {self.adresse[:10]}...>'
    
    @classmethod
    def get_numero_marchand(cls, operateur=None):
        """
        Récupérer le numéro marchand mobile money actif
        Args:
            operateur: Nom de l'opérateur (optionnel)
        Returns:
            PortefeuilleAdmin object ou None
        """
        query = cls.query.filter_by(
            type_portefeuille='mobile_money',
            est_actif=True
        )
        if operateur:
            query = query.filter_by(reseau=operateur)
        return query.first()
    
    @classmethod
    def get_adresse_crypto(cls, reseau):
        """
        Récupérer l'adresse crypto pour un réseau donné
        Args:
            reseau: Nom du réseau (TRC20, ETHEREUM, etc.)
        Returns:
            PortefeuilleAdmin object ou None
        """
        return cls.query.filter_by(
            reseau=reseau,
            type_portefeuille='crypto',
            est_actif=True
        ).first()


class TauxJournalier(db.Model):
    """
    Modèle pour stocker les taux de change journaliers USDT/XAF
    """
    __tablename__ = 'taux_journaliers'
    
    id = db.Column(db.Integer, primary_key=True)
    taux_achat = db.Column(db.Float, nullable=False)  # Taux pour acheter USDT (client achète)
    taux_vente = db.Column(db.Float, nullable=False)  # Taux pour vendre USDT (client vend)
    date = db.Column(db.Date, unique=True, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<TauxJournalier {self.date} - Achat: {self.taux_achat}, Vente: {self.taux_vente}>'
    
    @classmethod
    def get_taux_actuel(cls):
        """Récupérer le taux du jour ou le plus récent"""
        return cls.query.order_by(cls.date.desc()).first()


class Notification(db.Model):
    """
    Modèle pour les notifications utilisateurs et admin
    """
    __tablename__ = 'notifications'
    
    id = db.Column(db.Integer, primary_key=True)
    utilisateur_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    admin_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'))
    type_notification = db.Column(db.String(50), nullable=False)
    message = db.Column(db.Text, nullable=False)
    est_lue = db.Column(db.Boolean, default=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    
    def __repr__(self):
        return f'<Notification {self.type_notification} - {"Lue" if self.est_lue else "Non lue"}>'
    
    def marquer_comme_lue(self):
        """Marquer la notification comme lue"""
        self.est_lue = True
        db.session.commit()


class PushToken(db.Model):
    """
    Token FCM d'un appareil utilisateur/admin pour push hors application.
    """
    __tablename__ = 'push_tokens'

    id = db.Column(db.Integer, primary_key=True)
    utilisateur_id = db.Column(db.Integer, db.ForeignKey('utilisateurs.id'), nullable=False, index=True)
    token = db.Column(db.String(255), unique=True, nullable=False, index=True)
    platform = db.Column(db.String(20), default='unknown')  # android, ios, web
    est_actif = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_mise_a_jour = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<PushToken user={self.utilisateur_id} platform={self.platform}>'


class ParametreSysteme(db.Model):
    """
    Modèle pour stocker les paramètres système de l'application
    """
    __tablename__ = 'parametres_systeme'
    
    id = db.Column(db.Integer, primary_key=True)
    cle = db.Column(db.String(50), unique=True, nullable=False)
    valeur = db.Column(db.Text, nullable=False)
    type_valeur = db.Column(db.String(20), default='string')  # string, int, float, bool, json
    description = db.Column(db.Text)
    date_modification = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def __repr__(self):
        return f'<ParametreSysteme {self.cle}: {self.valeur}>'
    
    @classmethod
    def get_valeur(cls, cle, defaut=None):
        """Récupérer la valeur d'un paramètre"""
        param = cls.query.filter_by(cle=cle).first()
        if not param:
            return defaut
        
        # Convertir selon le type
        if param.type_valeur == 'int':
            return int(param.valeur)
        elif param.type_valeur == 'float':
            return float(param.valeur)
        elif param.type_valeur == 'bool':
            return param.valeur.lower() in ('true', '1', 'yes', 'oui')
        elif param.type_valeur == 'json':
            import json
            return json.loads(param.valeur)
        return param.valeur
    
    @classmethod
    def set_valeur(cls, cle, valeur, type_valeur='string', description=None):
        """Définir la valeur d'un paramètre"""
        param = cls.query.filter_by(cle=cle).first()
        if param:
            param.valeur = str(valeur)
            param.type_valeur = type_valeur
            if description:
                param.description = description
            param.date_modification = datetime.utcnow()
        else:
            param = cls(
                cle=cle,
                valeur=str(valeur),
                type_valeur=type_valeur,
                description=description
            )
            db.session.add(param)
        db.session.commit()
