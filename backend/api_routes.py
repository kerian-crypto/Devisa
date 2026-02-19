# api_routes.py
from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from functools import wraps
from datetime import date
import uuid

from models import db, Utilisateur, Transaction, PortefeuilleAdmin, TauxJournalier, Notification, PushToken
from utils import calculer_taux_vente_usdt, calculer_taux_achat_usdt, formater_montant
from Config import Config
from push_service import send_push

# Vérification du token Google
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests

api_bp = Blueprint('api', __name__, url_prefix='/api')


def current_user_id():
    """Récupère l'identité JWT normalisée en entier."""
    return int(get_jwt_identity())


def _notification_to_dict(notification):
    return {
        "id": notification.id,
        "utilisateur_id": notification.utilisateur_id,
        "admin_id": notification.admin_id,
        "type_notification": notification.type_notification,
        "message": notification.message,
        "est_lue": notification.est_lue,
        "date_creation": notification.date_creation.isoformat() if notification.date_creation else None,
    }


def _push_to_users(user_ids, title, body, data=None):
    """Envoie un push FCM à une liste d'utilisateurs et invalide les tokens morts."""
    if not user_ids:
        return

    rows = PushToken.query.filter(
        PushToken.utilisateur_id.in_(list(set(user_ids))),
        PushToken.est_actif.is_(True),
    ).all()
    tokens = [row.token for row in rows]
    if not tokens:
        return

    result = send_push(tokens, title, body, data=data or {})
    invalid = result.get("invalid_tokens", [])
    if invalid:
        PushToken.query.filter(PushToken.token.in_(invalid)).update(
            {"est_actif": False},
            synchronize_session=False,
        )
        db.session.commit()


# -------------------------------------------------------------------
# Helper : vérification du rôle admin
# -------------------------------------------------------------------
def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user_id = current_user_id()
        user = Utilisateur.query.get(user_id)
        if not user or not user.est_admin:
            return jsonify({"msg": "Accès réservé aux administrateurs"}), 403
        return fn(*args, **kwargs)
    return wrapper

# -------------------------------------------------------------------
# Authentification
# -------------------------------------------------------------------
@api_bp.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    required = ['nom', 'telephone', 'email', 'pays', 'mot_de_passe']
    if not all(k in data for k in required):
        return jsonify({"msg": "Champs manquants"}), 400

    if Utilisateur.query.filter_by(email=data['email']).first():
        print("email deja utilise")
        return jsonify({"msg": "Email déjà utilisé"}), 400
    if Utilisateur.query.filter_by(telephone=data['telephone']).first():
        print("numero de telephone deja utilise")
        return jsonify({"msg": "Téléphone déjà utilisé"}), 400
    taux = TauxJournalier.query.filter_by(date=date.today()).first()

    user = Utilisateur(
        nom=data['nom'],
        telephone=data['telephone'],
        email=data['email'],
        pays=data['pays'],
        est_admin=False,
        est_actif=True
    )
    user.password = data['mot_de_passe']  # appelle le setter
    db.session.add(user)
    db.session.commit()

    access_token = create_access_token(identity=str(user.id))
    return jsonify(
        access_token=access_token,
        user=user.to_dict(),), 201

@api_bp.route('/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email')
    password = data.get('mot_de_passe')
    if not email or not password:
        return jsonify({"msg": "Email et mot de passe requis"}), 400

    user = Utilisateur.query.filter_by(email=email).first()
    taux = TauxJournalier.query.filter_by(date=date.today()).first()
    if user and user.mot_de_passe_hash==password:
        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token, user=user.to_dict())
    return jsonify({"msg": "Email ou mot de passe incorrect"}), 401

@api_bp.route('/auth/google', methods=['POST'])
def google_login():
    token = request.json.get('id_token')
    if not token:
        return jsonify({"msg": "Token manquant"}), 400

    try:
        idinfo = id_token.verify_oauth2_token(
            token,
            google_requests.Request(),
            Config.GOOGLE_CLIENT_ID
        )
        userid = idinfo['sub']
        email = idinfo['email']
        name = idinfo.get('name', 'Utilisateur Google')

        user = Utilisateur.query.filter_by(email=email).first()
        if not user:
            # Création automatique
            user = Utilisateur(
                nom=name,
                email=email,
                google_id=userid,
                email_verifie=True,
                pays='CM',  # Valeur par défaut, à modifier ultérieurement
                telephone=f"google_{userid[:10]}"
            )
            db.session.add(user)
            db.session.commit()

        access_token = create_access_token(identity=str(user.id))
        return jsonify(access_token=access_token, user=user.to_dict())
    except ValueError as e:
        return jsonify({"msg": str(e)}), 401

# -------------------------------------------------------------------
# Profil utilisateur
# -------------------------------------------------------------------
@api_bp.route('/user/profile', methods=['GET'])
@jwt_required()
def profile():
    user_id = current_user_id()
    user = Utilisateur.query.get(user_id)
    return jsonify(user.to_dict())

@api_bp.route('/user/transactions', methods=['GET'])
@jwt_required()
def user_transactions():
    user_id = current_user_id()
    transactions = Transaction.query.filter_by(utilisateur_id=user_id)\
        .order_by(Transaction.date_creation.desc()).all()
    return jsonify([t.to_dict() for t in transactions])

@api_bp.route('/user/balance', methods=['GET'])
@jwt_required()
def balance():
    user_id = current_user_id()
    transactions = Transaction.query.filter_by(utilisateur_id=user_id, statut='complete').all()
    solde_usdt = sum(t.montant_usdt for t in transactions if t.type_transaction == 'achat') \
                 - sum(t.montant_usdt for t in transactions if t.type_transaction == 'vente')
    return jsonify(balance_usdt=round(solde_usdt, 2))

# -------------------------------------------------------------------
# Achat / Vente
# -------------------------------------------------------------------
@api_bp.route('/buy', methods=['POST'])
@jwt_required()
def buy():
    user_id = current_user_id()
    data = request.get_json()
    required = ['montant_xaf', 'reseau', 'operateur_mobile', 'adresse_wallet']
    if not all(k in data for k in required):
        print("champs manquant")
        return jsonify({"msg": "Champs manquants"}), 400

    taux = TauxJournalier.query.filter_by(date=date.today()).first()
    if not taux:
        print("Taux manquants")
        return jsonify({"msg": "Taux non définis pour aujourd'hui"}), 400

    montant_xaf = float(data['montant_xaf'])
    montant_usdt = montant_xaf / taux.taux_vente

    portefeuille = PortefeuilleAdmin.get_numero_marchand(data['operateur_mobile'])
    if not portefeuille:
        print("portefeuille absent")
        return jsonify({"msg": "Numéro marchand non disponible"}), 400

    numero = portefeuille.adresse
    if data['operateur_mobile'] == 'MTN':
        code_ussd = f"*126*14*{numero}*{montant_xaf}#"
    else:
        code_ussd = f"#150*14*505874*{numero}*{montant_xaf}"  # adaptez selon vos opérateurs

    transaction = Transaction(
        utilisateur_id=user_id,
        type_transaction='achat',
        montant_xaf=montant_xaf,
        montant_usdt=round(montant_usdt, 2),
        taux_applique=taux.taux_vente,
        reseau=data['reseau'],
        adresse_wallet=data['adresse_wallet'],
        operateur_mobile=data['operateur_mobile'],
        numero_marchand=numero,
        statut='en_attente'
    )
    db.session.add(transaction)

    user_notif = Notification(
        utilisateur_id=user_id,
        type_notification='transaction_created',
        message=f"Votre achat est enregistré et en attente ({transaction.identifiant_transaction})."
    )
    db.session.add(user_notif)

    # Notification à tous les administrateurs actifs
    admins = Utilisateur.query.filter_by(est_admin=True, est_actif=True).all()
    for admin in admins:
        notif = Notification(
            admin_id=admin.id,
            type_notification='transaction_created',
            message=f"Nouvel achat en attente: {montant_xaf} XAF ({transaction.identifiant_transaction})"
        )
        db.session.add(notif)
    db.session.commit()

    _push_to_users(
        [user_id],
        "Achat en attente",
        f"Votre achat {transaction.identifiant_transaction} est en attente de validation.",
        data={"type": "transaction_created", "transaction_id": transaction.identifiant_transaction},
    )
    _push_to_users(
        [admin.id for admin in admins],
        "Nouvelle transaction",
        f"Nouvel achat en attente: {montant_xaf} XAF",
        data={"type": "admin_notification", "transaction_id": transaction.identifiant_transaction},
    )

    return jsonify({
        'transaction_id': transaction.identifiant_transaction,
        'montant_xaf': montant_xaf,
        'montant_usdt': round(montant_usdt, 2),
        'numero_marchand': numero,
        'code_ussd': code_ussd,
        'statut': transaction.statut
    }), 201

@api_bp.route('/sell', methods=['POST'])
@jwt_required()
def sell():
    user_id = current_user_id()
    data = request.get_json()
    required = ['montant_usdt', 'reseau', 'operateur_mobile', 'numero_mobile']
    if not all(k in data for k in required):
        return jsonify({"msg": "Champs manquants"}), 400

    # Vérification du solde USDT
    transactions = Transaction.query.filter_by(utilisateur_id=user_id, statut='complete').all()
    solde_usdt = sum(t.montant_usdt for t in transactions if t.type_transaction == 'achat') \
                 - sum(t.montant_usdt for t in transactions if t.type_transaction == 'vente')
    montant_usdt = float(data['montant_usdt'])
    if solde_usdt < montant_usdt:
        return jsonify({"msg": "Solde USDT insuffisant"}), 400

    taux = TauxJournalier.query.filter_by(date=date.today()).first()
    if not taux:
        return jsonify({"msg": "Taux non définis pour aujourd'hui"}), 400

    montant_xaf = montant_usdt * taux.taux_achat

    portefeuille = PortefeuilleAdmin.get_adresse_crypto(data['reseau'])
    if not portefeuille:
        return jsonify({"msg": "Adresse crypto non disponible"}), 400

    adresse_admin = portefeuille.adresse

    transaction = Transaction(
        utilisateur_id=user_id,
        type_transaction='vente',
        montant_xaf=round(montant_xaf, 2),
        montant_usdt=montant_usdt,
        taux_applique=taux.taux_achat,
        reseau=data['reseau'],
        adresse_wallet=data.get('adresse_wallet', ''),
        operateur_mobile=data['operateur_mobile'],
        numero_marchand=adresse_admin,  # stocke l'adresse admin
        statut='en_attente'
    )
    db.session.add(transaction)

    user_notif = Notification(
        utilisateur_id=user_id,
        type_notification='transaction_created',
        message=f"Votre vente est enregistrée et en attente ({transaction.identifiant_transaction})."
    )
    db.session.add(user_notif)

    admins = Utilisateur.query.filter_by(est_admin=True, est_actif=True).all()
    for admin in admins:
        notif = Notification(
            admin_id=admin.id,
            type_notification='transaction_created',
            message=f"Nouvelle vente en attente: {montant_usdt} USDT ({transaction.identifiant_transaction})"
        )
        db.session.add(notif)
    db.session.commit()

    _push_to_users(
        [user_id],
        "Vente en attente",
        f"Votre vente {transaction.identifiant_transaction} est en attente de validation.",
        data={"type": "transaction_created", "transaction_id": transaction.identifiant_transaction},
    )
    _push_to_users(
        [admin.id for admin in admins],
        "Nouvelle transaction",
        f"Nouvelle vente en attente: {montant_usdt} USDT",
        data={"type": "admin_notification", "transaction_id": transaction.identifiant_transaction},
    )

    return jsonify({
        'transaction_id': transaction.identifiant_transaction,
        'montant_usdt': montant_usdt,
        'montant_xaf': round(montant_xaf, 2),
        'adresse_admin': adresse_admin,
        'statut': transaction.statut
    }), 201

@api_bp.route('/transaction/<transaction_id>', methods=['GET'])
@jwt_required()
def get_transaction(transaction_id):
    user_id = current_user_id()
    transaction = Transaction.query.filter_by(identifiant_transaction=transaction_id,
                                              utilisateur_id=user_id).first_or_404()
    return jsonify(transaction.to_dict())

# -------------------------------------------------------------------
# Taux et calculateur
# -------------------------------------------------------------------
@api_bp.route('/rates/current', methods=['GET'])
def current_rates():
    taux = TauxJournalier.query.filter_by(date=date.today()).first()
    if not taux:
        return jsonify({"msg": "Aucun taux pour aujourd'hui"}), 404
    return jsonify({
        'date': taux.date.isoformat(),
        'taux_achat': taux.taux_achat,
        'taux_vente': taux.taux_vente
    })

@api_bp.route('/rates/calculate', methods=['POST'])
def calculate_rates():
    data = request.get_json()
    type_calc = data.get('type')  # 'achat' ou 'vente' (sens client)
    taux_mondial = data.get('taux_mondial')
    benefice = data.get('benefice')
    montant = data.get('montant')

    if not type_calc or taux_mondial is None or benefice is None or montant is None:
        return jsonify({"msg": "Champs manquants"}), 400

    try:
        taux_mondial = float(taux_mondial)
        benefice = float(benefice)
        montant = float(montant)
    except ValueError:
        return jsonify({"msg": "Valeurs numériques invalides"}), 400

    if type_calc == 'vente':   # le client vend des USDT => calcul des XAF reçus
        result, error = calculer_taux_achat_usdt(taux_mondial, benefice, montant)
    elif type_calc == 'achat': # le client achète des USDT => calcul des USDT reçus
        result, error = calculer_taux_vente_usdt(taux_mondial, benefice, montant)
    else:
        return jsonify({"msg": "Type invalide (utiliser 'achat' ou 'vente')"}), 400

    if error:
        return jsonify({"msg": error}), 400
    return jsonify(result)

# -------------------------------------------------------------------
# ADMIN : utilisateurs
# -------------------------------------------------------------------
@api_bp.route('/admin/users', methods=['GET'])
@admin_required
def admin_users():
    users = Utilisateur.query.order_by(Utilisateur.date_inscription.desc()).all()
    return jsonify([u.to_dict() for u in users])

@api_bp.route('/admin/users/<string:user_uuid>', methods=['DELETE'])
@admin_required
def admin_delete_user(user_uuid):
    user = Utilisateur.query.filter_by(identifiant_unique=user_uuid).first_or_404()
    if user.id == current_user_id():
        return jsonify({"msg": "Impossible de supprimer votre propre compte"}), 400
    db.session.delete(user)
    db.session.commit()
    return jsonify({"msg": "Utilisateur supprimé"}), 200

@api_bp.route('/admin/users/<string:user_uuid>/toggle-admin', methods=['POST'])
@admin_required
def admin_toggle_admin(user_uuid):
    user = Utilisateur.query.filter_by(identifiant_unique=user_uuid).first_or_404()
    user.est_admin = not user.est_admin
    db.session.commit()
    return jsonify({"msg": "Rôle modifié", "est_admin": user.est_admin})

# -------------------------------------------------------------------
# ADMIN : transactions
# -------------------------------------------------------------------
@api_bp.route('/admin/transactions', methods=['GET'])
@admin_required
def admin_transactions():
    statut = request.args.get('statut')
    query = Transaction.query
    if statut and statut != 'tous':
        query = query.filter_by(statut=statut)
    transactions = query.order_by(Transaction.date_creation.desc()).all()
    return jsonify([t.to_dict() for t in transactions])

@api_bp.route('/admin/transactions/<string:trans_id>/validate', methods=['POST'])
@admin_required
def admin_validate_transaction(trans_id):
    transaction = Transaction.query.filter_by(identifiant_transaction=trans_id).first_or_404()
    transaction.statut = 'complete'
    transaction.date_validation = db.func.current_timestamp()
    # Notification utilisateur
    notif = Notification(utilisateur_id=transaction.utilisateur_id,
                         type_notification='transaction_validee',
                         message=f"Votre transaction {transaction.montant_usdt} USDT a été validée.")
    db.session.add(notif)
    db.session.commit()
    _push_to_users(
        [transaction.utilisateur_id],
        "Transaction validée",
        f"Votre transaction {transaction.identifiant_transaction} a été validée.",
        data={"type": "transaction_validated", "transaction_id": transaction.identifiant_transaction},
    )
    return jsonify({"msg": "Transaction validée"})

@api_bp.route('/admin/transactions/<string:trans_id>/reject', methods=['POST'])
@admin_required
def admin_reject_transaction(trans_id):
    data = request.get_json()
    motif = data.get('motif', '')
    transaction = Transaction.query.filter_by(identifiant_transaction=trans_id).first_or_404()
    transaction.statut = 'rejete'
    transaction.motif_rejet = motif
    transaction.date_validation = db.func.current_timestamp()
    notif = Notification(utilisateur_id=transaction.utilisateur_id,
                         type_notification='transaction_rejetee',
                         message=f"Transaction rejetée. Motif: {motif}")
    db.session.add(notif)
    db.session.commit()
    _push_to_users(
        [transaction.utilisateur_id],
        "Transaction rejetée",
        f"Votre transaction {transaction.identifiant_transaction} a été rejetée.",
        data={"type": "transaction_rejected", "transaction_id": transaction.identifiant_transaction},
    )
    return jsonify({"msg": "Transaction rejetée"})

# -------------------------------------------------------------------
# ADMIN : portefeuilles
# -------------------------------------------------------------------
@api_bp.route('/admin/wallets', methods=['GET'])
@admin_required
def admin_wallets():
    wallets = PortefeuilleAdmin.query.all()
    return jsonify([{
        'id': w.id,
        'reseau': w.reseau,
        'adresse': w.adresse,
        'pays': w.pays,
        'type': w.type_portefeuille,
        'est_actif': w.est_actif,
        'date_ajout': w.date_ajout.isoformat()
    } for w in wallets])

@api_bp.route('/admin/wallets', methods=['POST'])
@admin_required
def admin_add_wallet():
    data = request.get_json()
    required = ['reseau', 'adresse', 'type_portefeuille']
    if not all(k in data for k in required):
        return jsonify({"msg": "Champs manquants"}), 400

    wallet = PortefeuilleAdmin(
        reseau=data['reseau'],
        adresse=data['adresse'],
        pays=data.get('pays'),
        type_portefeuille=data['type_portefeuille'],
        est_actif=data.get('est_actif', True)
    )
    db.session.add(wallet)
    db.session.commit()
    return jsonify({"msg": "Portefeuille ajouté", "id": wallet.id}), 201

@api_bp.route('/admin/wallets/<int:wallet_id>', methods=['DELETE'])
@admin_required
def admin_delete_wallet(wallet_id):
    wallet = PortefeuilleAdmin.query.get_or_404(wallet_id)
    db.session.delete(wallet)
    db.session.commit()
    return jsonify({"msg": "Portefeuille supprimé"})

# -------------------------------------------------------------------
# ADMIN : taux
# -------------------------------------------------------------------
@api_bp.route('/admin/rates', methods=['GET'])
@admin_required
def admin_rates():
    # Historique des 30 derniers jours
    taux = TauxJournalier.query.order_by(TauxJournalier.date.desc()).limit(30).all()
    return jsonify([{
        'id': t.id,
        'date': t.date.isoformat(),
        'taux_achat': t.taux_achat,
        'taux_vente': t.taux_vente
    } for t in taux])

@api_bp.route('/admin/rates', methods=['POST'])
@admin_required
def admin_add_rate():
    data = request.get_json()
    required = ['taux_achat', 'taux_vente']
    if not all(k in data for k in required):
        return jsonify({"msg": "Champs manquants"}), 400

    taux_achat = float(data['taux_achat'])
    taux_vente = float(data['taux_vente'])
    if taux_vente <= taux_achat:
        return jsonify({"msg": "Le taux de vente doit être supérieur au taux d'achat"}), 400

    date_app = data.get('date')
    if date_app:
        from datetime import datetime
        date_app = datetime.strptime(date_app, '%Y-%m-%d').date()
    else:
        date_app = date.today()

    existing = TauxJournalier.query.filter_by(date=date_app).first()
    if existing:
        existing.taux_achat = taux_achat
        existing.taux_vente = taux_vente
        action = "mis à jour"
    else:
        new_rate = TauxJournalier(
            taux_achat=taux_achat,
            taux_vente=taux_vente,
            date=date_app
        )
        db.session.add(new_rate)
        action = "ajouté"

    # Notification broadcast à tous les utilisateurs actifs
    utilisateurs = Utilisateur.query.filter_by(est_actif=True).all()
    for utilisateur in utilisateurs:
        notif = Notification(
            utilisateur_id=utilisateur.id,
            type_notification='rate_updated',
            message=(
                f"Nouveaux taux {action} ({date_app.isoformat()}): "
                f"Achat {taux_achat} XAF | Vente {taux_vente} XAF"
            ),
        )
        db.session.add(notif)
    db.session.commit()

    _push_to_users(
        [u.id for u in utilisateurs],
        "Mise à jour des taux",
        f"Nouveaux taux: Achat {taux_achat} XAF | Vente {taux_vente} XAF",
        data={"type": "rate_updated", "date": date_app.isoformat()},
    )
    return jsonify({"msg": "Taux enregistré"}), 201

@api_bp.route('/admin/rates/<int:rate_id>', methods=['DELETE'])
@admin_required
def admin_delete_rate(rate_id):
    rate = TauxJournalier.query.get_or_404(rate_id)
    if rate.date == date.today():
        return jsonify({"msg": "Impossible de supprimer le taux du jour"}), 400
    db.session.delete(rate)
    db.session.commit()
    return jsonify({"msg": "Taux supprimé"})


# -------------------------------------------------------------------
# Notifications
# -------------------------------------------------------------------
@api_bp.route('/notifications/device-token', methods=['POST'])
@jwt_required()
def register_device_token():
    user_id = current_user_id()
    data = request.get_json() or {}
    token = (data.get('token') or '').strip()
    platform = (data.get('platform') or 'unknown').strip().lower()

    if not token:
        return jsonify({"msg": "Token FCM manquant"}), 400

    existing = PushToken.query.filter_by(token=token).first()
    if existing:
        existing.utilisateur_id = user_id
        existing.platform = platform
        existing.est_actif = True
    else:
        db.session.add(
            PushToken(
                utilisateur_id=user_id,
                token=token,
                platform=platform,
                est_actif=True,
            )
        )

    db.session.commit()
    return jsonify({"msg": "Token appareil enregistré"})


@api_bp.route('/notifications/device-token', methods=['DELETE'])
@jwt_required()
def unregister_device_token():
    user_id = current_user_id()
    data = request.get_json() or {}
    token = (data.get('token') or '').strip()
    if token:
        row = PushToken.query.filter_by(utilisateur_id=user_id, token=token).first()
        if row:
            row.est_actif = False
    else:
        PushToken.query.filter_by(utilisateur_id=user_id, est_actif=True).update(
            {"est_actif": False},
            synchronize_session=False,
        )
    db.session.commit()
    return jsonify({"msg": "Token appareil désactivé"})


@api_bp.route('/notifications', methods=['GET'])
@jwt_required()
def get_notifications():
    user_id = current_user_id()
    user = Utilisateur.query.get_or_404(user_id)
    limit = request.args.get('limit', default=50, type=int)
    limit = max(1, min(limit, 200))

    query = Notification.query
    if user.est_admin:
        query = query.filter(
            (Notification.admin_id == user_id) | (Notification.utilisateur_id == user_id)
        )
    else:
        query = query.filter(Notification.utilisateur_id == user_id)

    notifications = query.order_by(Notification.date_creation.desc()).limit(limit).all()
    unread_count = query.filter_by(est_lue=False).count()

    return jsonify({
        "notifications": [_notification_to_dict(n) for n in notifications],
        "unread_count": unread_count,
    })


@api_bp.route('/notifications/<int:notification_id>/read', methods=['POST'])
@jwt_required()
def mark_notification_read(notification_id):
    user_id = current_user_id()
    user = Utilisateur.query.get_or_404(user_id)
    notification = Notification.query.get_or_404(notification_id)

    allowed = (
        notification.utilisateur_id == user_id
        or notification.admin_id == user_id
        or (user.est_admin and notification.utilisateur_id == user_id)
    )
    if not allowed:
        return jsonify({"msg": "Accès refusé"}), 403

    notification.est_lue = True
    db.session.commit()
    return jsonify({"msg": "Notification marquée comme lue"})


@api_bp.route('/notifications/read-all', methods=['POST'])
@jwt_required()
def mark_all_notifications_read():
    user_id = current_user_id()
    user = Utilisateur.query.get_or_404(user_id)
    query = Notification.query

    if user.est_admin:
        query = query.filter(
            ((Notification.admin_id == user_id) | (Notification.utilisateur_id == user_id))
            & (Notification.est_lue.is_(False))
        )
    else:
        query = query.filter(
            (Notification.utilisateur_id == user_id) & (Notification.est_lue.is_(False))
        )

    for notification in query.all():
        notification.est_lue = True

    db.session.commit()
    return jsonify({"msg": "Toutes les notifications ont été marquées comme lues"})


@api_bp.route('/notifications/<int:notification_id>', methods=['DELETE'])
@jwt_required()
def delete_notification(notification_id):
    user_id = current_user_id()
    user = Utilisateur.query.get_or_404(user_id)
    notification = Notification.query.get_or_404(notification_id)

    allowed = (
        notification.utilisateur_id == user_id
        or notification.admin_id == user_id
        or (user.est_admin and notification.utilisateur_id == user_id)
    )
    if not allowed:
        return jsonify({"msg": "Accès refusé"}), 403

    db.session.delete(notification)
    db.session.commit()
    return jsonify({"msg": "Notification supprimée"})
