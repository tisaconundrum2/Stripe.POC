import os
import secrets
import stripe
import tiktoken
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///ums.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"

stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
DOMAIN = os.getenv("DOMAIN", "http://localhost:5000")

# ---------------------------------------------------------------------------
# Database models
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    api_key = db.Column(db.String(64), unique=True, nullable=True)
    token_budget = db.Column(db.Integer, default=10000, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    usages = db.relationship("TokenUsage", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def tokens_used(self):
        return sum(u.total_tokens for u in self.usages)

    def tokens_remaining(self):
        return max(0, self.token_budget - self.tokens_used())


class TokenUsage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    prompt_tokens = db.Column(db.Integer, nullable=False, default=0)
    completion_tokens = db.Column(db.Integer, nullable=False, default=0)
    total_tokens = db.Column(db.Integer, nullable=False, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# ---------------------------------------------------------------------------
# Admin guard decorator
# ---------------------------------------------------------------------------

from functools import wraps
from flask import abort

def admin_required(f):
    """Decorator that requires the current user to be authenticated and is_admin=True."""
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ---------------------------------------------------------------------------
# CLI: flask promote-admin <username>
# ---------------------------------------------------------------------------

import click

@app.cli.command("promote-admin")
@click.argument("username")
def promote_admin(username):
    """Grant admin privileges to an existing user."""
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            click.echo(f"Error: user '{username}' not found.", err=True)
            raise SystemExit(1)
        user.is_admin = True
        db.session.commit()
        click.echo(f"✅  '{username}' is now an admin.")


# ---------------------------------------------------------------------------
# Helper: count tokens locally with tiktoken
# ---------------------------------------------------------------------------

def count_tokens(text: str, model: str = "gpt-3.5-turbo") -> int:
    """Return token count using tiktoken; fall back to a word-based estimate if offline."""
    try:
        try:
            encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text))
    except Exception:
        # Offline fallback: ~0.75 words per token is a reasonable approximation
        return max(1, len(text.split()))


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not username or not email or not password:
            flash("All fields are required.", "danger")
            return render_template("register.html")

        if User.query.filter_by(username=username).first():
            flash("Username already taken.", "danger")
            return render_template("register.html")

        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "danger")
            return render_template("register.html")

        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("Account created! Welcome.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard")
@login_required
def dashboard():
    # Build daily usage for the last 30 days
    today = datetime.utcnow().date()
    days = [(today - timedelta(days=i)) for i in range(29, -1, -1)]
    usage_by_day = {d: 0 for d in days}
    for u in current_user.usages:
        d = u.timestamp.date()
        if d in usage_by_day:
            usage_by_day[d] += u.total_tokens

    chart_labels = [d.strftime("%b %d") for d in days]
    chart_data = [usage_by_day[d] for d in days]

    return render_template(
        "dashboard.html",
        user=current_user,
        chart_labels=chart_labels,
        chart_data=chart_data,
    )


# ---------------------------------------------------------------------------
# API key management
# ---------------------------------------------------------------------------

@app.route("/generate-api-key", methods=["POST"])
@login_required
def generate_api_key():
    current_user.api_key = secrets.token_urlsafe(32)
    db.session.commit()
    flash("New API key generated.", "success")
    return redirect(url_for("dashboard"))


@app.route("/revoke-api-key", methods=["POST"])
@login_required
def revoke_api_key():
    current_user.api_key = None
    db.session.commit()
    flash("API key revoked.", "warning")
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# API endpoint (uses X-API-KEY header, tracks token usage)
# ---------------------------------------------------------------------------

@app.route("/api/process", methods=["POST"])
def api_process():
    key = request.headers.get("X-API-KEY")
    if not key:
        return jsonify({"error": "Missing X-API-KEY header"}), 401

    user = User.query.filter_by(api_key=key).first()
    if not user:
        return jsonify({"error": "Invalid API key"}), 401

    data = request.get_json(silent=True) or {}
    prompt = data.get("prompt", "")
    if not prompt:
        return jsonify({"error": "No prompt provided"}), 400

    p_tokens = count_tokens(prompt)
    mock_response = f"This is a simulated response to: {prompt[:20]}..."
    c_tokens = count_tokens(mock_response)
    t_tokens = p_tokens + c_tokens

    if user.tokens_remaining() < t_tokens:
        return jsonify({"error": "Insufficient token budget"}), 402

    log = TokenUsage(
        user_id=user.id,
        prompt_tokens=p_tokens,
        completion_tokens=c_tokens,
        total_tokens=t_tokens,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify(
        {
            "output": mock_response,
            "tokens": {"prompt": p_tokens, "completion": c_tokens, "total": t_tokens},
            "budget_remaining": user.tokens_remaining(),
        }
    )


@app.route("/api/usage", methods=["GET"])
@login_required
def api_usage():
    usages = [
        {
            "id": u.id,
            "prompt_tokens": u.prompt_tokens,
            "completion_tokens": u.completion_tokens,
            "total_tokens": u.total_tokens,
            "timestamp": u.timestamp.isoformat(),
        }
        for u in current_user.usages
    ]
    return jsonify(
        {
            "total_budget": current_user.token_budget,
            "tokens_used": current_user.tokens_used(),
            "tokens_remaining": current_user.tokens_remaining(),
            "usages": usages,
        }
    )


# ---------------------------------------------------------------------------
# Stripe: create checkout session
# ---------------------------------------------------------------------------

@app.route("/create-checkout-session", methods=["POST"])
@login_required
def create_checkout_session():
    price_id = STRIPE_PRICE_ID or request.form.get("price_id", "")
    if not price_id:
        flash("Stripe price ID not configured.", "danger")
        return redirect(url_for("dashboard"))

    try:
        session = stripe.checkout.Session.create(
            line_items=[{"price": price_id, "quantity": 1}],
            mode="payment",
            success_url=DOMAIN + "/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url=DOMAIN + "/cancel",
            metadata={"user_id": str(current_user.id)},
            automatic_tax={"enabled": True},
        )
        return redirect(session.url, code=303)
    except Exception as exc:
        flash(f"Payment error: {exc}", "danger")
        return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Stripe webhook
# ---------------------------------------------------------------------------

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=False)
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
    except ValueError:
        return jsonify({"error": "Invalid payload"}), 400
    except stripe.error.SignatureVerificationError:
        return jsonify({"error": "Invalid signature"}), 400

    if event["type"] == "checkout.session.completed":
        session_obj = event["data"]["object"]
        user_id = session_obj.get("metadata", {}).get("user_id")
        if user_id:
            user = db.session.get(User, int(user_id))
            if user:
                # Add 50 000 tokens per successful payment
                user.token_budget += 50000
                db.session.commit()

    return jsonify({"status": "success"})


# ---------------------------------------------------------------------------
# Admin portal
# ---------------------------------------------------------------------------

@app.route("/admin")
@admin_required
def admin_dashboard():
    total_users = User.query.count()
    total_tokens_sold = db.session.query(db.func.sum(User.token_budget)).scalar() or 0
    total_tokens_used = db.session.query(db.func.sum(TokenUsage.total_tokens)).scalar() or 0
    recent_users = User.query.order_by(User.created_at.desc()).limit(5).all()
    return render_template(
        "admin/dashboard.html",
        total_users=total_users,
        total_tokens_sold=total_tokens_sold,
        total_tokens_used=total_tokens_used,
        recent_users=recent_users,
    )


@app.route("/admin/users")
@admin_required
def admin_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template("admin/users.html", users=users)


@app.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if request.method == "POST":
        new_budget = request.form.get("token_budget", "").strip()
        make_admin = request.form.get("is_admin") == "on"
        if new_budget.isdigit():
            user.token_budget = int(new_budget)
        user.is_admin = make_admin
        db.session.commit()
        flash(f"User '{user.username}' updated.", "success")
        return redirect(url_for("admin_users"))
    return render_template("admin/edit_user.html", user=user)


@app.route("/admin/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for("admin_users"))
    TokenUsage.query.filter_by(user_id=user.id).delete()
    db.session.delete(user)
    db.session.commit()
    flash(f"User '{user.username}' deleted.", "warning")
    return redirect(url_for("admin_users"))


# ---------------------------------------------------------------------------
# Payment result pages
# ---------------------------------------------------------------------------

@app.route("/success")
@login_required
def success():
    return render_template("success.html")


@app.route("/cancel")
@login_required
def cancel():
    return render_template("cancel.html")


if __name__ == "__main__":
    app.run(debug=True)
