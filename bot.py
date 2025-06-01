import logging
import csv
import os
import random
import string
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters,
    ConversationHandler, ContextTypes
)
from github_sync import ensure_file_and_push, push_to_github
from config import TELEGRAM_TOKEN

USERS_FILE = "users.csv"
CODES_FILE = "codes.csv"

CHOOSING, PAYMENT_METHOD, PAYMENT_NUMBER, PAYMENT_REF, INSCRIPTION_NAME, INSCRIPTION_SURNAME, INSCRIPTION_PHONE, INSCRIPTION_ID = range(8)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def generate_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["Paiement", "Inscription", "Aide"]]
    await update.message.reply_text(
        "Bienvenue ! Que souhaitez-vous faire ?",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
    )
    return CHOOSING

async def choix_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choix = update.message.text
    if choix == "Paiement":
        keyboard = [["Via Mvola", "Via Airtel Money", "Retour"]]
        await update.message.reply_text(
            "Choisissez le mode de paiement :",
            reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True)
        )
        return PAYMENT_METHOD
    elif choix == "Inscription":
        await update.message.reply_text("Entrez votre nom :", reply_markup=ReplyKeyboardRemove())
        return INSCRIPTION_NAME
    elif choix == "Aide":
        await update.message.reply_text(
            "Aide :\n"
            "- Inscription : renseignez vos infos pour créer un compte.\n"
            "- Paiement : payez 5000 Ar via Mvola ou Airtel Money, puis fournissez les infos demandées pour obtenir votre code d'accès.\n"
            "Utilisez /start pour revenir au menu à tout moment.",
            reply_markup=ReplyKeyboardRemove()
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text("Option inconnue. Envoyez /start pour recommencer.")
        return ConversationHandler.END

# Paiement
async def payment_method(update: Update, context: ContextTypes.DEFAULT_TYPE):
    choix = update.message.text
    if choix == "Retour":
        return await start(update, context)
    elif choix in ["Via Mvola", "Via Airtel Money"]:
        context.user_data["payment_method"] = choix
        await update.message.reply_text("Entrez le numéro de transfert :")
        return PAYMENT_NUMBER
    else:
        await update.message.reply_text("Option inconnue. Envoyez /start pour recommencer.")
        return ConversationHandler.END

async def payment_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["payment_number"] = update.message.text
    await update.message.reply_text("Entrez la référence de transfert (votre ID choisi) :")
    return PAYMENT_REF

async def payment_ref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.text
    context.user_data["user_id"] = user_id

    ensure_file_and_push(CODES_FILE, "user_id,code,payment_method,payment_number")

    code = generate_code()
    # Vérifie si l'id a déjà un code attribué (anti-duplication)
    already_exist = False
    with open(CODES_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["user_id"] == user_id:
                already_exist = True
                code = row["code"]
                break
    if not already_exist:
        with open(CODES_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                user_id,
                code,
                context.user_data.get("payment_method", ""),
                context.user_data.get("payment_number", "")
            ])
        push_to_github(CODES_FILE)

    await update.message.reply_text(
        f"Merci !\n"
        f"Votre code d'abonnement est : {code}\n"
        f"Gardez ce code pour l'utiliser dans Termux.\n"
        f"Pour revenir au menu, tapez /start."
    )
    return ConversationHandler.END

# Inscription
async def inscription_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Entrez votre prénom :")
    return INSCRIPTION_SURNAME

async def inscription_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["surname"] = update.message.text
    await update.message.reply_text("Entrez votre numéro de téléphone :")
    return INSCRIPTION_PHONE

async def inscription_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text
    await update.message.reply_text("Choisissez votre identifiant unique (ID) :")
    return INSCRIPTION_ID

async def inscription_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.text
    context.user_data["user_id"] = user_id

    ensure_file_and_push(USERS_FILE, "name,surname,phone,user_id,telegram_id")

    # Vérifie si l'id existe déjà
    already_exist = False
    with open(USERS_FILE, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["user_id"] == user_id:
                already_exist = True
                break
    if not already_exist:
        with open(USERS_FILE, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                context.user_data["name"],
                context.user_data["surname"],
                context.user_data["phone"],
                user_id,
                update.effective_user.id
            ])
        push_to_github(USERS_FILE)

    await update.message.reply_text(
        "Inscription réussie !\n"
        f"Nom : {context.user_data['name']}\n"
        f"Prénom : {context.user_data['surname']}\n"
        f"Téléphone : {context.user_data['phone']}\n"
        f"Votre ID : {user_id}\n"
        "Pour revenir au menu, tapez /start."
    )
    return ConversationHandler.END

def main():
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
    print("Bot lancé…")
    app.run_polling()

if __name__ == "__main__":
    main()
