import math
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

def calculer_taux_vente_usdt(taux_mondial, benefice, montant_xaf):
    """Calcul du taux de vente USDT selon la logique du fichier taux.py"""
    taux_marchant = float(taux_mondial)
    frais_operateur = 0
    
    if montant_xaf < 5000:
        return None, "Le montant doit être supérieur ou égal à 5000 XAF"
    elif 5000 <= montant_xaf < 300000:
        frais_operateur = montant_xaf * 0.0151
    elif 300000 <= montant_xaf < 500000:
        frais_operateur = montant_xaf * 0.01
    else:
        return None, "Le montant doit être inférieur à 500000 XAF"
    
    # Calcul du nombre de USDT sans frais opérateur
    nbre_usdt_sans_frais = montant_xaf / (taux_marchant + benefice)
    
    # Calcul avec frais
    frais_par_usdt = frais_operateur / (taux_marchant + benefice)
    taux_marchant_avec_frais = taux_marchant + benefice + frais_par_usdt
    amount_out = montant_xaf / taux_marchant_avec_frais
    
    return {
        'usdt_sans_frais': round(nbre_usdt_sans_frais, 2),
        'frais_operateur': round(frais_operateur, 2),
        'taux_final': round(taux_marchant_avec_frais, 2),
        'usdt_final': round(amount_out, 2),
        'frais_par_usdt': round(frais_par_usdt, 2)
    }, None

def calculer_taux_achat_usdt(taux_mondial, benefice, montant_usdt):
    """Calcul du taux d'achat USDT selon la logique du fichier taux.py"""
    taux_marchant = float(taux_mondial)
    frais_operateur = 0
    
    if montant_usdt < 1:
        return None, "Le montant doit être supérieur ou égal à 1 USDT"
    elif 1 <= montant_usdt < 500:
        frais_operateur = montant_usdt * 0.0151
    elif 500 <= montant_usdt < 1000:
        frais_operateur = montant_usdt * 0.1
    else:
        return None, "Le montant doit être inférieur à 1000 USDT"
    
    # Calcul du nombre de XAF sans frais opérateur
    nbre_xaf_sans_frais = montant_usdt * (taux_marchant - benefice)
    
    # Calcul avec frais
    frais_par_usdt = frais_operateur / (taux_marchant - benefice)
    taux_marchant_avec_frais = taux_marchant - benefice - frais_par_usdt
    amount_out = montant_usdt * taux_marchant_avec_frais
    
    return {
        'xaf_sans_frais': round(nbre_xaf_sans_frais, 2),
        'frais_operateur': round(frais_operateur, 2),
        'taux_final': round(taux_marchant_avec_frais, 2),
        'xaf_final': round(amount_out, 2),
        'frais_par_usdt': round(frais_par_usdt, 2)
    }, None

def generer_numero_marchand(pays, operateur):
    """Génère un numéro marchand basé sur le pays et l'opérateur"""
    numeros = {
        'CM': {
            'MTN': '237670000000',
            'ORANGE': '237690000000'
        },
        'TG': {
            'TOGOCEL': '22890000000',
            'MOOV': '22870000000'
        }
    }
    return numeros.get(pays, {}).get(operateur, '')

def formater_montant(montant):
    """Formate un montant avec séparateurs de milliers"""
    return f"{montant:,.2f}".replace(',', ' ').replace('.', ',')

def determiner_reseau_par_adresse(adresse):
    """Détermine le réseau cryptographique basé sur l'adresse wallet"""
    if adresse.startswith('T'):
        return 'TRC20'
    elif adresse.startswith('0x'):
        return 'ETHEREUM'
    elif len(adresse) == 44 and adresse.isalnum():
        return 'SOL'
    elif 'TON' in adresse.upper():
        return 'USDT_TON'
    elif 'APT' in adresse.upper():
        return 'USDT_APTOS'
    return 'TRC20'  # Par défaut