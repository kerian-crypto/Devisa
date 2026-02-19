from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, session
from flask_login import login_required, current_user, logout_user, login_user
from datetime import datetime, date
import uuid
import os
import urllib.parse



from models import db, Utilisateur, Transaction, PortefeuilleAdmin, TauxJournalier, Notification
from forms import FormulaireInscription, FormulaireConnexion, FormulaireAchat, FormulaireVente, FormulaireCalculTaux, FormulaireTaux
from utils import calculer_taux_vente_usdt, calculer_taux_achat_usdt, generer_numero_marchand, formater_montant
from auth import auth_bp
from Config import Config

main_bp = Blueprint('main', __name__)


from itsdangerous import SignatureExpired, BadSignature
import hashlib

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

@main_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.est_admin:
            flash('Bienvenu Admin.', 'sucess')
            return redirect(url_for('admin.admin_dashboard'))
    
        return redirect(url_for('main.dashboard'))
    
    """Page d'accueil"""
    return render_template('index.html')

# Modifier la route register pour envoyer l'email de vérification
@main_bp.route('/register', methods=['GET', 'POST'])
def register():
    """Inscription"""
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = FormulaireInscription()
    
    if form.validate_on_submit():
        # Vérifier si l'email existe déjà
        if Utilisateur.query.filter_by(email=form.email.data).first():
            flash('Cet email est déjà utilisé.', 'error')
            return redirect(url_for('main.register'))
        
        # Vérifier si le téléphone existe déjà
        if Utilisateur.query.filter_by(telephone=form.telephone.data).first():
            flash('Ce numéro de téléphone est déjà utilisé.', 'error')
            return redirect(url_for('main.register'))
        
        # Créer l'utilisateur
        utilisateur = Utilisateur(
            nom=form.nom.data,
            telephone=form.telephone.data,
            email=form.email.data,
            pays=form.pays.data,
            mot_de_passe_hash=hashlib.sha256(form.mot_de_passe.data.encode()).hexdigest()
        )
        
        db.session.add(utilisateur)
        db.session.commit()
        return redirect(url_for('main.login'))
    
    return render_template('register.html', form=form)
    


# Ajouter une vérification dans la route login
@main_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Connexion"""
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    
    form = FormulaireConnexion()
    
    if form.validate_on_submit():
        utilisateur = Utilisateur.query.filter_by(email=form.email.data).first()
        
        # Vérifier le mot de passe (en production, utiliser bcrypt)
        mot_de_passe_hash = hashlib.sha256(form.mot_de_passe.data.encode()).hexdigest()

        if utilisateur and utilisateur.mot_de_passe_hash == mot_de_passe_hash:
            if utilisateur.est_admin==True:
                login_user(utilisateur)
                flash('Connexion réussie en tant qu\'administrateur!', 'success')
                return redirect(url_for('admin.admin_dashboard'))
            login_user(utilisateur)
            flash('Connexion réussie!', 'success')
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('main.dashboard'))
        else:
            flash('Email ou mot de passe incorrect.', 'error')
    
    return render_template('login.html', form=form)

@main_bp.route('/dashboard')
@login_required
def dashboard():
    """Tableau de bord utilisateur"""
    transactions = Transaction.query.filter_by(
        utilisateur_id=current_user.id
    ).order_by(Transaction.date_creation.desc()).limit(10).all()
    
    solde_usdt = sum(t.montant_usdt for t in transactions if t.statut == 'complete' and t.type_transaction == 'achat')
    solde_usdt -= sum(t.montant_usdt for t in transactions if t.statut == 'complete' and t.type_transaction == 'vente')
    
    return render_template('dashboard.html', 
                         transactions=transactions,
                         solde_usdt=round(solde_usdt, 2),
                         formater_montant=formater_montant)

# Achat de USDT
@main_bp.route('/buy', methods=['GET', 'POST'])
@login_required
def buy():
    taux_du_jour = TauxJournalier.query.filter_by(date=date.today()).first()
    if not taux_du_jour:
        flash("Les taux du jour ne sont pas définis.", "error")
        return redirect(url_for('main.dashboard'))

    form = FormulaireAchat()
    taux_vente = taux_du_jour.taux_vente

    if form.validate_on_submit():
        montant_xaf = form.montant_xaf.data
        montant_usdt = montant_xaf / taux_vente

        portefeuille = PortefeuilleAdmin.get_numero_marchand(form.operateur_mobile.data)
        if not portefeuille:
            flash("Aucun numéro marchand disponible.", "error")
            return redirect(url_for('main.dashboard'))

        numero = portefeuille.adresse
        adresse = None  # facultatif pour l'achat
        
        if form.operateur_mobile.data=='MTN':
            code_encode=f"*126*14*{numero}*{montant_xaf}#"
        else:
            code_encode=f"#150*14*505874*{numero}*{montant_xaf}"

        code = code_encode

        transaction = Transaction(
            utilisateur_id=current_user.id,
            type_transaction='achat',
            montant_xaf=montant_xaf,
            montant_usdt=round(montant_usdt, 2),
            taux_applique=taux_vente,
            reseau=form.reseau.data,
            adresse_wallet=form.adresse_wallet.data,
            operateur_mobile=form.operateur_mobile.data,
            numero_marchand=numero,
            statut='en_attente'
        )
        db.session.add(transaction)
        db.session.commit()

        notification = Notification(
            admin_id=1,
            type_notification='nouvelle_transaction',
            message=f"Nouvel achat : {montant_xaf} XAF par {current_user.nom}"
        )
        db.session.add(notification)
        db.session.commit()

        # ✅ Passage des valeurs facultatives en query string
        return redirect(url_for('main.transaction_status',
                                transaction_id=transaction.identifiant_transaction,
                                adresse=adresse))

    return render_template('buy.html', form=form, taux_vente=taux_vente)


# Vente de USDT
@main_bp.route('/sell', methods=['GET', 'POST'])
@login_required
def sell():
    taux_du_jour = TauxJournalier.query.filter_by(date=date.today()).first()
    if not taux_du_jour:
        flash("Les taux du jour ne sont pas définis.", "error")
        return redirect(url_for('main.dashboard'))

    form = FormulaireVente()
    taux_achat = taux_du_jour.taux_achat
    
    if form.validate_on_submit():
        montant_usdt = form.montant_usdt.data
        montant_xaf = montant_usdt * taux_achat

        portefeuille = PortefeuilleAdmin.get_adresse_crypto(form.reseau.data)
        if not portefeuille:
            flash("Aucune adresse crypto disponible.", "error")
            return redirect(url_for('main.dashboard'))

        adresse = portefeuille.adresse
        numero = None  # facultatif pour la vente

        transaction = Transaction(
            utilisateur_id=current_user.id,
            type_transaction='vente',
            montant_xaf=round(montant_xaf, 2),
            montant_usdt=montant_usdt,
            taux_applique=taux_achat,
            reseau=form.reseau.data,
            adresse_wallet=form.adresse_wallet.data,
            operateur_mobile=form.operateur_mobile.data,
            numero_marchand=numero,
            statut='en_attente'
        )
        db.session.add(transaction)
        db.session.commit()

        notification = Notification(
            admin_id=1,
            type_notification='nouvelle_transaction',
            message=f"Nouvelle vente : {montant_usdt} USDT par {current_user.nom}"
        )
        db.session.add(notification)
        db.session.commit()

        return redirect(url_for('main.transaction_status',
                                transaction_id=transaction.identifiant_transaction,
                                numero=numero,
                                adresse=adresse))
    return render_template('sell.html', form=form, taux_achat=taux_achat)
        
# Statut de la transaction
@main_bp.route('/transaction/<transaction_id>')
@login_required
def transaction_status(transaction_id):
    """Statut de la transaction"""
    transaction = Transaction.query.filter_by(
        identifiant_transaction=transaction_id,
        utilisateur_id=current_user.id
    ).first_or_404()

    if transaction.operateur_mobile == 'MTN':
        code = f"*126*14*{transaction.numero_marchand}*{transaction.montant_xaf}#"
    else:
        code = f"#150*14*505874*{transaction.numero_marchand}*{transaction.montant_xaf}"


    # Récupérer numero et adresse depuis la query string (facultatif)
    numero = request.args.get('numero')
    adresse = request.args.get('adresse')

    return render_template('transaction_status.html',
                           transaction=transaction,
                           numero=numero,
                           adresse=adresse,
                           formater_montant=formater_montant)

@main_bp.route('/calculate', methods=['GET', 'POST'])
def calculate():
    """Calculateur de taux"""
    form = FormulaireCalculTaux()
    resultat = None
    erreur = None
    
    if form.validate_on_submit():
        if form.type_calcul.data == 'vente':
            resultat, erreur = calculer_taux_vente_usdt(
                form.taux_mondial.data,
                form.benefice.data,
                form.montant.data
            )
        else:
            resultat, erreur = calculer_taux_achat_usdt(
                form.taux_mondial.data,
                form.benefice.data,
                form.montant.data
            )
    
    return render_template('calculate.html', 
                         form=form,
                         resultat=resultat,
                         erreur=erreur)

# Routes Admin
@admin_bp.route('/')
@login_required
def admin_dashboard():
    """Tableau de bord administrateur"""
    if not current_user.est_admin:
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard'))
    
    # Statistiques
    total_utilisateurs = Utilisateur.query.count()
    transactions_aujourdhui = Transaction.query.filter(
        db.func.date(Transaction.date_creation) == date.today()
    ).count()
    
    transactions_attente = Transaction.query.filter_by(statut='en_attente').count()
    transactions_complete = Transaction.query.filter_by(statut='complete').count()
    
    # Chiffre d'affaires
    ca_aujourdhui = db.session.query(
        db.func.sum(Transaction.montant_xaf)
    ).filter(
        db.func.date(Transaction.date_creation) == date.today(),
        Transaction.statut == 'complete'
    ).scalar() or 0
    
    ca_total = db.session.query(
        db.func.sum(Transaction.montant_xaf)
    ).filter(
        Transaction.statut == 'complete'
    ).scalar() or 0
    
    # Dernières transactions
    dernieres_transactions = Transaction.query.order_by(
        Transaction.date_creation.desc()
    ).limit(10).all()
    
    # Notifications non lues
    notifications = Notification.query.filter_by(
        admin_id=current_user.id,
        est_lue=False
    ).order_by(Notification.date_creation.desc()).all()
    print(dernieres_transactions)
    
    return render_template('admin_dashboard.html',
                         total_utilisateurs=total_utilisateurs,
                         transactions_aujourdhui=transactions_aujourdhui,
                         transactions_attente=transactions_attente,
                         transactions_complete=transactions_complete,
                         ca_aujourdhui=formater_montant(ca_aujourdhui),
                         ca_total=formater_montant(ca_total),
                         dernieres_transactions=dernieres_transactions,
                         notifications=notifications,
                         formater_montant=formater_montant)

@admin_bp.route('/transactions')
@login_required
def admin_transactions():
    """Gestion des transactions par l'admin"""
    if not current_user.est_admin:
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard'))
    
    statut = request.args.get('statut', 'tous')
    
    if statut == 'tous':
        transactions = Transaction.query.order_by(Transaction.date_creation.desc()).all()
    else:
        transactions = Transaction.query.filter_by(statut=statut).order_by(
            Transaction.date_creation.desc()
        ).all()
    
    return render_template('admin_transactions.html',
                         transactions=transactions,
                         formater_montant=formater_montant)

@admin_bp.route('/transaction/<transaction_id>/validate', methods=['POST'])
@login_required
def validate_transaction(transaction_id):
    """Valider une transaction"""
    if not current_user.est_admin:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    transaction = Transaction.query.filter_by(
        identifiant_transaction=transaction_id
    ).first_or_404()
    
    transaction.statut = 'complete'
    transaction.date_validation = datetime.utcnow()
    
    # Notifier l'utilisateur
    notification = Notification(
        utilisateur_id=transaction.utilisateur_id,
        type_notification='transaction_validee',
        message=f'Votre transaction de {transaction.montant_usdt} USDT a été validée.'
    )
    db.session.add(notification)
    db.session.commit()
    
    flash('Transaction validée avec succès.', 'success')
    return jsonify({'success': True})

@admin_bp.route('/transaction/<transaction_id>/reject', methods=['POST'])
@login_required
def reject_transaction(transaction_id):
    """Rejeter une transaction"""
    if not current_user.est_admin:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    motif = request.form.get('motif', '')
    
    transaction = Transaction.query.filter_by(
        identifiant_transaction=transaction_id
    ).first_or_404()
    
    transaction.statut = 'rejete'
    transaction.motif_rejet = motif
    transaction.date_validation = datetime.utcnow()
    
    # Notifier l'utilisateur
    notification = Notification(
        utilisateur_id=transaction.utilisateur_id,
        type_notification='transaction_rejetee',
        message=f'Votre transaction a été rejetée. Motif: {motif}'
    )
    db.session.add(notification)
    db.session.commit()
    
    flash('Transaction rejetée.', 'success')
    return jsonify({'success': True})

@admin_bp.route('/wallets')
@login_required
def admin_wallets():
    """Gestion des adresses wallet par l'admin"""
    if not current_user.est_admin:
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('dashboard'))
    
    portefeuilles = PortefeuilleAdmin.query.all()
    
    return render_template('admin_wallets.html', portefeuilles=portefeuilles)

@admin_bp.route('/utilisateurs')
@login_required
def liste_utilisateurs():
    """Affiche tous les utilisateurs avec filtres"""
    
    # Récupération des paramètres de filtrage
    page = request.args.get('page', 1, type=int)
    statut = request.args.get('statut', 'tous')
    admin = request.args.get('admin', 'tous')
    pays = request.args.get('pays', '')
    email_verifie = request.args.get('email_verifie', '')
    
    # Construction de la requête de base
    query = Utilisateur.query
    
    # Application des filtres
    if statut == 'actifs':
        query = query.filter_by(est_actif=True)
    elif statut == 'inactifs':
        query = query.filter_by(est_actif=False)
    
    if admin == 'admins':
        query = query.filter_by(est_admin=True)
    elif admin == 'non-admins':
        query = query.filter_by(est_admin=False)
    
    if pays:
        query = query.filter(Utilisateur.pays.ilike(f'%{pays}%'))
    
    if email_verifie == 'verifies':
        query = query.filter_by(email_verifie=True)
    elif email_verifie == 'non-verifies':
        query = query.filter_by(email_verifie=False)
    
    # Pagination (20 utilisateurs par page)
    utilisateurs = query.order_by(Utilisateur.date_inscription.desc())\
                       .paginate(page=page, per_page=20, error_out=False)
    
    # Statistiques pour les filtres
    total_utilisateurs = Utilisateur.query.count()
    admins = Utilisateur.query.filter_by(est_admin=True).count()
    actifs = Utilisateur.query.filter_by(est_actif=True).count()
    verifies = Utilisateur.query.filter_by(email_verifie=True).count()
    
    # Liste des pays uniques pour le filtre
    pays_uniques = db.session.query(Utilisateur.pays)\
                   .distinct()\
                   .order_by(Utilisateur.pays)\
                   .all()
    pays_uniques = [p[0] for p in pays_uniques]
    
    return render_template('utilisateurs.html',
                         utilisateurs=utilisateurs,
                         total=total_utilisateurs,
                         admins=admins,
                         actifs=actifs,
                         verifies=verifies,
                         pays_uniques=pays_uniques,
                         filtres=request.args)

@admin_bp.route('/utilisateur/<string:identifiant_unique>')
@login_required
def detail_utilisateur(identifiant_unique):
    """Page de détail d'un utilisateur"""
    utilisateur = Utilisateur.query\
        .filter_by(identifiant_unique=identifiant_unique)\
        .first_or_404()
    
    # Calcul de l'ancienneté
    anciennete = (datetime.utcnow() - utilisateur.date_inscription).days
    
    return render_template('detail_utilisateurs.html',
                         utilisateur=utilisateur,
                         anciennete=anciennete)
@admin_bp.route('/admin/utilisateur/<string:identifiant_unique>/delete', methods=['POST'])
@login_required
# @admin_required 
def delete_user(identifiant_unique):
    user = Utilisateur.query.filter_by(identifiant_unique=identifiant_unique).first_or_404()
    
    
    if user.id == current_user.id:
        return jsonify({'success': False, 'message': 'Vous ne pouvez pas supprimer votre propre compte.'}), 400
    
    try:
        db.session.delete(user)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Utilisateur supprimé avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@admin_bp.route('/wallet/add', methods=['POST'])
@login_required
def add_wallet():
    """Ajouter une adresse wallet"""
    if not current_user.est_admin:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    reseau = request.form.get('reseau')
    adresse = request.form.get('adresse')
    pays = request.form.get('pays')
    type_portefeuille = request.form.get('type')
    
    if not all([reseau, adresse, type_portefeuille]):
        return jsonify({'success': False, 'message': 'Données manquantes'}), 400
    
    portefeuille = PortefeuilleAdmin(
        reseau=reseau,
        adresse=adresse,
        pays=pays,
        type_portefeuille=type_portefeuille
    )
    
    db.session.add(portefeuille)
    db.session.commit()
    
    return jsonify({'success': True})

@admin_bp.route('/wallet/<int:wallet_id>/delete', methods=['POST'])
@login_required
def delete_wallet(wallet_id):
    """Supprimer une adresse wallet"""
    if not current_user.est_admin:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    portefeuille = PortefeuilleAdmin.query.get_or_404(wallet_id)
    db.session.delete(portefeuille)
    db.session.commit()
    
    return jsonify({'success': True})

# routes.py - Ajouter ces routes dans la section admin_bp
from datetime import datetime, date, timedelta
import json

@admin_bp.route('/rates', methods=['GET', 'POST'])
@login_required
def admin_rates():
    """Gestion des taux de change par l'admin"""
    if not current_user.est_admin:
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('main.dashboard'))
    
    form = FormulaireTaux()
    
    # Récupérer les taux d'aujourd'hui
    taux_aujourdhui = TauxJournalier.query.filter_by(date=date.today()).first()
    
    # Récupérer l'historique des taux (30 derniers jours)
    historique_taux = TauxJournalier.query.order_by(
        TauxJournalier.date.desc()
    ).limit(30).all()
    
    # Statistiques des taux
    taux_moyen_achat = db.session.query(db.func.avg(TauxJournalier.taux_achat)).scalar() or 0
    taux_moyen_vente = db.session.query(db.func.avg(TauxJournalier.taux_vente)).scalar() or 0
    
    if form.validate_on_submit():
        taux_achat = form.taux_achat.data
        taux_vente = form.taux_vente.data
        date_application = form.date_application.data or date.today()
        
        # Validation : taux de vente doit être supérieur au taux d'achat
        if taux_vente <= taux_achat:
            flash('Le taux de vente doit être supérieur au taux d\'achat.', 'error')
            return render_template('admin_rates.html',
                                 form=form,
                                 taux_aujourdhui=taux_aujourdhui,
                                 historique_taux=historique_taux,
                                 taux_moyen_achat=round(taux_moyen_achat, 2),
                                 taux_moyen_vente=round(taux_moyen_vente, 2),
                                 today=date.today())
        
        # Vérifier si un taux existe déjà pour cette date
        taux_existant = TauxJournalier.query.filter_by(date=date_application).first()
        
        if taux_existant:
            # Mettre à jour le taux existant
            taux_existant.taux_achat = taux_achat
            taux_existant.taux_vente = taux_vente
            taux_existant.timestamp = datetime.utcnow()
            message = 'Taux mis à jour avec succès pour le '
        else:
            # Créer un nouveau taux
            nouveau_taux = TauxJournalier(
                taux_achat=taux_achat,
                taux_vente=taux_vente,
                date=date_application
            )
            db.session.add(nouveau_taux)
            message = 'Nouveau taux ajouté avec succès pour le '
        
        db.session.commit()
        
        # Notifier tous les utilisateurs via notification
        if date_application == date.today():
            utilisateurs = Utilisateur.query.filter_by(est_actif=True).all()
            for utilisateur in utilisateurs:
                notification = Notification(
                    utilisateur_id=utilisateur.id,
                    type_notification='taux_mis_a_jour',
                    message=f'Nouveaux taux disponibles : Achat {taux_achat} XAF | Vente {taux_vente} XAF'
                )
                db.session.add(notification)
            db.session.commit()
        
        flash(f'{message} {date_application.strftime("%d/%m/%Y")}.', 'success')
        return redirect(url_for('admin.admin_rates'))
    
    # Pré-remplir le formulaire avec les taux d'aujourd'hui
    if taux_aujourdhui and not form.is_submitted():
        form.taux_achat.data = taux_aujourdhui.taux_achat
        form.taux_vente.data = taux_aujourdhui.taux_vente
    
    return render_template('admin_rates.html',
                         form=form,
                         taux_aujourdhui=taux_aujourdhui,
                         historique_taux=historique_taux,
                         taux_moyen_achat=round(taux_moyen_achat, 2),
                         taux_moyen_vente=round(taux_moyen_vente, 2),
                         today=date.today())

@admin_bp.route('/api/rates/history')
@login_required
def rates_history_api():
    """API pour obtenir l'historique des taux (pour graphique)"""
    if not current_user.est_admin:
        return jsonify({'error': 'Non autorisé'}), 403
    
    # Récupérer les 60 derniers jours
    jours = request.args.get('days', 30, type=int)
    date_debut = date.today() - timedelta(days=jours)
    
    historique = TauxJournalier.query.filter(
        TauxJournalier.date >= date_debut
    ).order_by(TauxJournalier.date).all()
    
    data = {
        'dates': [t.date.strftime('%Y-%m-%d') for t in historique],
        'achat': [float(t.taux_achat) for t in historique],
        'vente': [float(t.taux_vente) for t in historique],
        'ecart': [float(t.taux_vente - t.taux_achat) for t in historique]
    }
    
    return jsonify(data)

@admin_bp.route('/api/rates/update', methods=['POST'])
@login_required
def update_rates_api():
    """API pour mettre à jour les taux (AJAX)"""
    if not current_user.est_admin:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    data = request.get_json()
    
    taux_achat = data.get('taux_achat')
    taux_vente = data.get('taux_vente')
    date_application = data.get('date_application')
    
    if not taux_achat or not taux_vente:
        return jsonify({'success': False, 'message': 'Données manquantes'})
    
    try:
        taux_achat = float(taux_achat)
        taux_vente = float(taux_vente)
        
        if taux_vente <= taux_achat:
            return jsonify({'success': False, 'message': 'Le taux de vente doit être supérieur au taux d\'achat'})
        
        if date_application:
            date_application = datetime.strptime(date_application, '%Y-%m-%d').date()
        else:
            date_application = date.today()
        
        # Vérifier si un taux existe déjà pour cette date
        taux_existant = TauxJournalier.query.filter_by(date=date_application).first()
        
        if taux_existant:
            taux_existant.taux_achat = taux_achat
            taux_existant.taux_vente = taux_vente
            taux_existant.timestamp = datetime.utcnow()
            message = 'Taux mis à jour'
        else:
            nouveau_taux = TauxJournalier(
                taux_achat=taux_achat,
                taux_vente=taux_vente,
                date=date_application
            )
            db.session.add(nouveau_taux)
            message = 'Nouveau taux ajouté'
        
        db.session.commit()
        
        # Si c'est pour aujourd'hui, notifier les utilisateurs
        if date_application == date.today():
            # Envoyer des notifications push ou emails aux utilisateurs actifs
            pass
        
        return jsonify({
            'success': True,
            'message': f'{message} avec succès',
            'taux': {
                'achat': taux_achat,
                'vente': taux_vente,
                'date': date_application.strftime('%Y-%m-%d')
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/rates/delete/<int:rate_id>', methods=['POST'])
@login_required
def delete_rate(rate_id):
    """Supprimer un taux de l'historique"""
    if not current_user.est_admin:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    taux = TauxJournalier.query.get_or_404(rate_id)
    
    # Ne pas permettre la suppression du taux d'aujourd'hui
    if taux.date == date.today():
        return jsonify({'success': False, 'message': 'Impossible de supprimer le taux du jour actuel'})
    
    try:
        db.session.delete(taux)
        db.session.commit()
        return jsonify({'success': True, 'message': 'Taux supprimé avec succès'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/rates/duplicate/<int:rate_id>', methods=['POST'])
@login_required
def duplicate_rate(rate_id):
    """Dupliquer un taux pour une nouvelle date"""
    if not current_user.est_admin:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    taux_source = TauxJournalier.query.get_or_404(rate_id)
    nouvelle_date = request.form.get('nouvelle_date')
    
    if not nouvelle_date:
        return jsonify({'success': False, 'message': 'Date manquante'})
    
    try:
        nouvelle_date = datetime.strptime(nouvelle_date, '%Y-%m-%d').date()
        
        # Vérifier si un taux existe déjà pour cette date
        taux_existant = TauxJournalier.query.filter_by(date=nouvelle_date).first()
        
        if taux_existant:
            return jsonify({'success': False, 'message': 'Un taux existe déjà pour cette date'})
        
        nouveau_taux = TauxJournalier(
            taux_achat=taux_source.taux_achat,
            taux_vente=taux_source.taux_vente,
            date=nouvelle_date
        )
        
        db.session.add(nouveau_taux)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': f'Taux dupliqué pour le {nouvelle_date.strftime("%d/%m/%Y")}',
            'taux': {
                'achat': taux_source.taux_achat,
                'vente': taux_source.taux_vente,
                'date': nouvelle_date.strftime('%Y-%m-%d')
            }
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@admin_bp.route('/rates/export')
@login_required
def export_rates():
    """Exporter l'historique des taux en CSV/Excel"""
    if not current_user.est_admin:
        flash('Accès non autorisé.', 'error')
        return redirect(url_for('main.dashboard'))
    
    # Récupérer tous les taux
    taux = TauxJournalier.query.order_by(TauxJournalier.date.desc()).all()
    
    # Créer un CSV
    import csv
    from io import StringIO
    
    output = StringIO()
    writer = csv.writer(output)
    
    # En-têtes
    writer.writerow(['Date', 'Taux Achat (XAF)', 'Taux Vente (XAF)', 'Écart (XAF)', 'Marge (%)'])
    
    # Données
    for t in taux:
        ecart = t.taux_vente - t.taux_achat
        marge = (ecart / t.taux_achat) * 100 if t.taux_achat > 0 else 0
        writer.writerow([
            t.date.strftime('%Y-%m-%d'),
            t.taux_achat,
            t.taux_vente,
            round(ecart, 2),
            round(marge, 2)
        ])
    
    output.seek(0)
    
    from flask import make_response
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=taux_devisa_fx.csv"
    response.headers["Content-type"] = "text/csv"
    return response

@admin_bp.route('/notification/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    """Marquer une notification comme lue"""
    notification = Notification.query.get_or_404(notification_id)
    
    if notification.admin_id != current_user.id and notification.utilisateur_id != current_user.id:
        return jsonify({'success': False, 'message': 'Non autorisé'}), 403
    
    notification.est_lue = True
    db.session.commit()
    

    return jsonify({'success': True})

