import logging
import os
import random
import string
import time
import sqlite3
from datetime import datetime, timedelta
from telegram import (
    Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ConversationHandler, ContextTypes, CallbackQueryHandler
)
from github_sync import ensure_file_and_push, push_to_github
from config import TELEGRAM_TOKEN

BOT_NAME = "TS"

CHOOSING, PAYMENT_METHOD, PAYMENT_NUMBER, PAYMENT_REF, INSCRIPTION_NAME, INSCRIPTION_SURNAME, INSCRIPTION_PHONE, INSCRIPTION_ID = range(8)
ADMIN_IDS = [123456789, 987654321]  # ⚠️ Remplacer par tes deux vrais Telegram ID admin !

KEY_VALIDITY_SECONDS = 30 * 24 * 3600

DB_FILE = "users.db"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def ensure_db():
    conn = get_db()
    c = conn.cursor()
    # Table des utilisateurs
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            name TEXT,
            surname TEXT,
            phone TEXT,
            user_id TEXT PRIMARY KEY,
            telegram_id TEXT,
            status TEXT
        )
    """)
    # Table des codes
    c.execute("""
        CREATE TABLE IF NOT EXISTS codes (
            user_id TEXT,
            code TEXT,
            payment_method TEXT,
            payment_number TEXT,
            active TEXT,
            timestamp TEXT,
            PRIMARY KEY (user_id, code)
        )
    """)
    conn.commit()
    conn.close()

def generate_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def now_ts():
    return int(time.time())

def format_date(ts):
    return datetime.fromtimestamp(int(ts)).strftime("%d/%m/%Y")

def key_is_valid(code_row):
    if code_row["active"] != "validated":
        return False
    ts = int(code_row["timestamp"])
    return now_ts() - ts < KEY_VALIDITY_SECONDS

def user_has_valid_code(user_id):
    ensure_db()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM codes WHERE user_id = ? AND active = 'validated'", (user_id,))
    row = c.fetchone()
    conn.close()
    if row and key_is_valid(row):
        return True
    return False

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, msg=None):
    keyboard = [
        ["💳 Payer mon abonnement", "📝 M'inscrire"],
        ["ℹ️ Aide", "🔑 Mon abonnement"],
    ]
    if not msg:
        msg = (
            f"✨ <b>Bienvenue sur {BOT_NAME} !</b>\n\n"
            "Que souhaitez-vous faire ?\n\n"
            "💠 <b>Payer mon abonnement</b> — Recevez votre code.\n"
            "💠 <b>M'inscrire</b> — Devenez membre.\n"
            "💠 <b>Aide</b> — Questions fréquentes.\n"
            "💠 <b>Mon abonnement</b> — Statut de clé."
        )
    await update.message.reply_text(
        msg,
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
        parse_mode="HTML"
    )
    return CHOOSING

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await send_main_menu(update, context)

async def choix_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choix = update.message.text
    if "Payer" in choix:
        keyboard = [
            ["📱 Via Mvola", "💵 Via Airtel Money"],
            ["⬅️ Retour"],
        ]
        await update.message.reply_text(
            "🔐 <b>Paiement de l'abonnement</b>\n\n"
            "Sélectionnez le mode de paiement :",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
            parse_mode="HTML"
        )
        return PAYMENT_METHOD
    elif "M'inscrire" in choix:
        await update.message.reply_text(
            "📝 <b>Inscription</b>\n\nEntrez votre <b>nom</b> :",
            reply_markup=ReplyKeyboardRemove(),
            parse_mode="HTML"
        )
        return INSCRIPTION_NAME
    elif "Aide" in choix:
        await update.message.reply_text(
            "ℹ️ <b>Aide / Questions fréquentes</b>\n\n"
            "• <b>Inscription</b> : Renseignez vos infos pour créer un compte.\n"
            "• <b>Paiement</b> : Payez 5000 Ar via Mvola ou Airtel Money, puis fournissez les infos demandées pour obtenir votre code d'accès.\n"
            "• <b>Clé d'accès</b> : Valable 30 jours, usage unique, vérifiée automatiquement.\n"
            "Utilisez /start à tout moment pour revenir au menu principal.",
            reply_markup=ReplyKeyboardMarkup([["⬅️ Retour"]], resize_keyboard=True),
            parse_mode="HTML"
        )
        return ConversationHandler.END
    elif "Mon abonnement" in choix:
        uid = get_userid_from_telegram(update.effective_user.id)
        if uid:
            code, valid_until = get_user_code_info(uid)
            if code:
                await update.message.reply_text(
                    f"🔑 <b>Votre code d'accès</b> : <code>{code}</code>\n"
                    f"⏳ <b>Valide jusqu'au</b> : {valid_until}\n"
                    "Pour renouveler, refaites un paiement.",
                    parse_mode="HTML"
                )
            else:
                await update.message.reply_text("❗️Aucun code d'accès actif pour votre compte.")
        else:
            await update.message.reply_text("❗️Vous devez d'abord vous inscrire.")
        await send_main_menu(update, context)
        return CHOOSING
    elif "Retour" in choix or "⬅️" in choix:
        await send_main_menu(update, context)
        return CHOOSING
    else:
        await update.message.reply_text("❗️Option inconnue. Envoyez /start pour recommencer.")
        return ConversationHandler.END

# ========== Paiement

async def payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choix = update.message.text
    if "Retour" in choix:
        await send_main_menu(update, context)
        return CHOOSING
    elif "Mvola" in choix or "Airtel" in choix:
        context.user_data["payment_method"] = choix
        await update.message.reply_text(
            "📱 Entrez <b>le numéro de transfert</b> :",
            parse_mode="HTML"
        )
        return PAYMENT_NUMBER
    else:
        await update.message.reply_text("❗️Option inconnue.")
        await send_main_menu(update, context)
        return CHOOSING

async def payment_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["payment_number"] = update.message.text
    await update.message.reply_text(
        "🆔 Entrez <b>la référence de transfert</b> (votre identifiant choisi) :",
        parse_mode="HTML"
    )
    return PAYMENT_REF

async def payment_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.text
    context.user_data["user_id"] = user_id
    ensure_db()
    code = generate_code()
    timestamp = now_ts()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM codes WHERE user_id = ? AND active != 'deleted'", (user_id,))
    row = c.fetchone()
    already_exist = False
    if row:
        already_exist = True
        code = row["code"]
        c.execute("UPDATE codes SET active = 'pending', timestamp = ? WHERE user_id = ?", (str(timestamp), user_id))
    if not already_exist:
        c.execute("INSERT OR REPLACE INTO codes (user_id, code, payment_method, payment_number, active, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                  (user_id, code, context.user_data.get("payment_method", ""), context.user_data.get("payment_number", ""), "pending", str(timestamp)))
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "⏳ <b>Demande enregistrée !</b>\n\n"
        "Votre paiement sera vérifié par un administrateur.\n"
        "Vous recevrez votre code d'accès après validation.\n"
        "Pour revenir au menu, tapez /start.",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# ========== Inscription

async def inscription_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text(
        "✏️ Entrez votre <b>prénom</b> :",
        parse_mode="HTML"
    )
    return INSCRIPTION_SURNAME

async def inscription_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["surname"] = update.message.text
    await update.message.reply_text(
        "📞 Entrez votre <b>numéro de téléphone</b> :",
        parse_mode="HTML"
    )
    return INSCRIPTION_PHONE

async def inscription_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text(
        "🆔 Choisissez votre <b>identifiant unique (ID)</b> :",
        parse_mode="HTML"
    )
    return INSCRIPTION_ID

async def inscription_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.text
    context.user_data["user_id"] = user_id

    ensure_db()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    already_exist = c.fetchone()
    if not already_exist:
        c.execute("INSERT INTO users (name, surname, phone, user_id, telegram_id, status) VALUES (?, ?, ?, ?, ?, ?)",
                  (context.user_data["name"], context.user_data["surname"], context.user_data["phone"], user_id, str(update.effective_user.id), "active"))
        conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎉 <b>Inscription réussie !</b>\n"
        f"👤 <b>Nom</b> : {context.user_data['name']}\n"
        f"👤 <b>Prénom</b> : {context.user_data['surname']}\n"
        f"📞 <b>Téléphone</b> : {context.user_data['phone']}\n"
        f"🆔 <b>ID</b> : {user_id}\n"
        "Pour revenir au menu, tapez /start.",
        parse_mode="HTML"
    )
    return ConversationHandler.END

# ========== ADMINISTRATION ==========

async def admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⛔️ Accès refusé.")
        return
    keyboard = [
        [InlineKeyboardButton("👥 Liste inscrits", callback_data='admin_users')],
        [InlineKeyboardButton("💳 Paiements à valider", callback_data='admin_payments')],
        [InlineKeyboardButton("⬅️ Retour menu principal", callback_data='admin_quit')],
    ]
    await update.message.reply_text(
        "🛡️ <b>Menu d'administration TS</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def admin_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if user_id not in ADMIN_IDS:
        await query.edit_message_text("⛔️ Accès refusé.")
        return

    if query.data == 'admin_users':
        await show_admin_users(query, context)
    elif query.data.startswith('toggle_user_'):
        await toggle_user_status(query, context, query.data.replace('toggle_user_', ''))
    elif query.data == 'admin_payments':
        await show_admin_payments(query, context)
    elif query.data.startswith('validate_payment_'):
        await validate_payment(query, context, query.data.replace('validate_payment_', ''))
    elif query.data.startswith('delete_payment_'):
        await delete_payment(query, context, query.data.replace('delete_payment_', ''))
    elif query.data == 'admin_quit':
        await query.edit_message_text("⬅️ Retour au menu principal.")

async def show_admin_users(query, context):
    ensure_db()
    text = "👥 <b>Liste des inscrits</b> :\n"
    buttons = []
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users")
    users = c.fetchall()
    if not users:
        text += "\nAucun inscrit."
    else:
        for row in users:
            user_id = row["user_id"]
            nom = row["name"]
            prenom = row["surname"]
            phone = row["phone"]
            status = row["status"] if row["status"] else "active"
            icon = "✅" if status == "active" else "🚫"
            text += f"{icon} <b>{nom} {prenom}</b> (ID: <code>{user_id}</code>, Tel: {phone})\n"
            label = "🚫 Désactiver" if status == "active" else "✅ Réactiver"
            buttons.append([InlineKeyboardButton(f"{label} {user_id}", callback_data=f"toggle_user_{user_id}")])
    buttons.append([InlineKeyboardButton("⬅️ Retour", callback_data="admin_menu")])
    conn.close()
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML", disable_web_page_preview=True)

async def toggle_user_status(query, context, target_user_id):
    ensure_db()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT status FROM users WHERE user_id = ?", (target_user_id,))
    row = c.fetchone()
    if row:
        current_status = row["status"]
        new_status = "inactive" if current_status == "active" else "active"
        c.execute("UPDATE users SET status = ? WHERE user_id = ?", (new_status, target_user_id))
        conn.commit()
        status_msg = f"Utilisateur {target_user_id} est maintenant {new_status.upper()}."
    else:
        status_msg = "Utilisateur introuvable."
    conn.close()
    await show_admin_users(query, context)
    await context.bot.send_message(chat_id=query.from_user.id, text=status_msg)

async def show_admin_payments(query, context):
    ensure_db()
    text = "💳 <b>Paiements en attente de validation</b> :\n"
    buttons = []
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM codes WHERE active = 'pending'")
    rows = c.fetchall()
    found = False
    for row in rows:
        user_id = row["user_id"]
        code = row["code"]
        method = row["payment_method"]
        num = row["payment_number"]
        state = row["active"]
        found = True
        text += f"\n• <b>ID</b>: <code>{user_id}</code> | <b>Méthode</b>: {method} | <b>N°</b>: {num}"
        buttons.append([
            InlineKeyboardButton(f"✅ Confirmer {user_id}", callback_data=f"validate_payment_{user_id}"),
            InlineKeyboardButton(f"❌ Supprimer {user_id}", callback_data=f"delete_payment_{user_id}")
        ])
    if not found:
        text += "\nAucune demande en attente."
    buttons.append([InlineKeyboardButton("⬅️ Retour", callback_data="admin_menu")])
    conn.close()
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="HTML", disable_web_page_preview=True)

async def validate_payment(query, context, target_user_id):
    ensure_db()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM codes WHERE user_id = ? AND active = 'pending'", (target_user_id,))
    row = c.fetchone()
    code = None
    if row:
        code = row["code"]
        c.execute("UPDATE codes SET active = 'validated', timestamp = ? WHERE user_id = ? AND active = 'pending'", (str(now_ts()), target_user_id))
        conn.commit()
    # Trouver le telegram_id associé à ce user_id
    c.execute("SELECT telegram_id FROM users WHERE user_id = ?", (target_user_id,))
    row2 = c.fetchone()
    tgid = row2["telegram_id"] if row2 else None
    conn.close()
    # Envoi du code par DM
    if tgid and code:
        try:
            await context.bot.send_message(
                chat_id=int(tgid),
                text=f"✅ <b>Paiement validé !</b>\n"
                     f"🔑 <b>Votre code d'accès</b> :\n\n<code>{code}</code>\n\n"
                     "Ce code est unique, valable 30 jours, et ne peut être utilisé qu'une seule fois.\n"
                     "Utilisez-le dans Termux pour activer votre abonnement.",
                parse_mode="HTML"
            )
        except Exception as e:
            await context.bot.send_message(chat_id=query.from_user.id, text=f"❗️Impossible d'envoyer le code à {tgid} : {e}")
    await show_admin_payments(query, context)
    await context.bot.send_message(chat_id=query.from_user.id, text=f"🎉 Paiement {target_user_id} validé, code envoyé !")

async def delete_payment(query, context, target_user_id):
    ensure_db()
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE codes SET active = 'deleted' WHERE user_id = ? AND active = 'pending'", (target_user_id,))
    conn.commit()
    conn.close()
    await show_admin_payments(query, context)
    await context.bot.send_message(chat_id=query.from_user.id, text=f"🚫 Paiement {target_user_id} supprimé.")

# ========== UTILS

def get_userid_from_telegram(telegram_id):
    ensure_db()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE telegram_id = ?", (str(telegram_id),))
    row = c.fetchone()
    conn.close()
    if row:
        return row["user_id"]
    return None

def get_user_code_info(user_id):
    ensure_db()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM codes WHERE user_id = ? AND active = 'validated'", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        ts = int(row["timestamp"])
        valid_until = datetime.fromtimestamp(ts + KEY_VALIDITY_SECONDS).strftime("%d/%m/%Y")
        return row["code"], valid_until
    return None, None

# ========== MAIN

def main():
    ensure_db()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            CHOOSING: [MessageHandler(filters.TEXT & ~filters.COMMAND, choix_menu)],
            PAYMENT_METHOD: [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_method)],
            PAYMENT_NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_number)],
            PAYMENT_REF: [MessageHandler(filters.TEXT & ~filters.COMMAND, payment_ref)],
            INSCRIPTION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, inscription_name)],
            INSCRIPTION_SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, inscription_surname)],
            INSCRIPTION_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, inscription_phone)],
            INSCRIPTION_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, inscription_id)],
        },
        fallbacks=[CommandHandler('start', start)],
    )
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler('admin', admin_menu))
    app.add_handler(CallbackQueryHandler(admin_callback))
    print("🤖 Bot TS lancé…")
    app.run_polling()

if __name__ == "__main__":
    main()
