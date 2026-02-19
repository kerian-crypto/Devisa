import json
import requests

from flask import Blueprint, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required
from oauthlib.oauth2 import WebApplicationClient

from models import db, Utilisateur
from Config import Config

auth_bp = Blueprint("auth", __name__)
client = WebApplicationClient(Config.GOOGLE_CLIENT_ID)


@auth_bp.route("/login/google")
def login_google():
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=url_for(
            "auth.google_callback",
            _external=True,
            _scheme="https"
        ),
        scope=["openid", "email", "profile"],
    )
    return redirect(request_uri)


@auth_bp.route("/login/google/callback")
def google_callback():
    code = request.args.get("code")

    if not code:
        flash("Erreur Google OAuth.", "error")
        return redirect(url_for("main.index"))

    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]

    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=url_for(
            "auth.google_callback",
            _external=True,
            _scheme="https"
        ),
        code=code,
    )

    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(
            Config.GOOGLE_CLIENT_ID,
            Config.GOOGLE_CLIENT_SECRET,
        ),
    )

    client.parse_request_body_response(
        json.dumps(token_response.json())
    )

    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers)
    userinfo = userinfo_response.json()

    if not userinfo.get("email_verified"):
        flash("Email non vérifié.", "error")
        return redirect(url_for("main.index"))

    google_id = userinfo["sub"]
    email = userinfo["email"]
    nom = userinfo.get("name", "Utilisateur Google")

    utilisateur = Utilisateur.query.filter_by(email=email).first()

    if not utilisateur:
        utilisateur = Utilisateur(
            nom=nom,
            email=email,
            google_id=google_id,
            email_verifie=True,
            pays="CM",
            telephone=f"google_{google_id[:10]}"
        )
        db.session.add(utilisateur)
        db.session.commit()

    login_user(utilisateur)
    flash("Connexion Google réussie.", "success")
    return redirect(url_for("main.dashboard"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Déconnexion réussie.", "info")
    return redirect(url_for("main.index"))


def get_google_provider_cfg():
    return requests.get(
        Config.GOOGLE_DISCOVERY_URL
    ).json()

