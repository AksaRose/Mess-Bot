import logging
import datetime
import os
import psycopg2
import httpx
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest
from fastapi import FastAPI, Request
import uvicorn
import asyncio
from functools import partial
from PIL import Image, ImageDraw, ImageFont, ImageOps
import io

load_dotenv()

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# Conversation states
(
    NAME,
    ADMISSION_NO,
    PASSOUT_YEAR,
    PROFILE_PHOTO,
    MEAL_CHOICE_VEG_NONVEG,
    MEAL_CHOICE_CAFFEINE,
) = range(6)

# Weekly choice states
(
    WEEKLY_CHOICE_DAY,
    WEEKLY_CHOICE_VEG_NONVEG,
    WEEKLY_CHOICE_CAFFEINE,
) = range(6, 9)

# View menu states
(VIEW_MENU_DAY,) = range(9, 10)

# Database connection
def get_db_connection():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# --- Bot command handlers --- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE tg_user_id = %s", (user_id,))
    student = cur.fetchone()
    cur.close()
    conn.close()

    if student:
        await update.message.reply_text(
            f"Hello {student[1]}! Welcome back to Hostel Bot. You are already registered."
        )
        return ConversationHandler.END
    else:
        await update.message.reply_text(
            "Hello! Welcome to Hostel Bot. Let's get you registered.\n"
            "Please tell me your full name."
        )
        return NAME

async def ask_admission_no(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Please tell me your Hostel Admission Number.")
    return ADMISSION_NO

async def ask_passout_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["admission_no"] = update.message.text
    await update.message.reply_text("Please tell me your Pass-out Year.")
    return PASSOUT_YEAR

async def ask_profile_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        passout_year = int(update.message.text)
        context.user_data["passout_year"] = passout_year
        await update.message.reply_text("Please send your profile photo.")
        return PROFILE_PHOTO
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid year. Please enter a 4-digit year (e.g., 2024).")
        return PASSOUT_YEAR

async def save_student_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    photo_file_id = update.message.photo[-1].file_id if update.message.photo else None

    if not photo_file_id:
        await update.message.reply_text("Please send a photo to complete registration.")
        return PROFILE_PHOTO

    context.user_data["profile_file_id"] = photo_file_id
    name = context.user_data["name"]
    admission_no = context.user_data["admission_no"]
    passout_year = context.user_data["passout_year"]

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO students (name, admission_no, passout_year, profile_file_id, tg_user_id) VALUES (%s, %s, %s, %s, %s)",
            (name, admission_no, passout_year, photo_file_id, user_id),
        )
        conn.commit()
        await update.message.reply_text(f"Thank you, {name}! You are now registered. Welcome to Hostel Bot!")
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        await update.message.reply_text("You are already registered. Contact support if this is an error.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving student data: {e}")
        await update.message.reply_text("An error occurred during registration. Please try again later.")
    finally:
        cur.close()
        conn.close()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Registration cancelled. Use /start to begin again.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Meal choice handlers --- #

async def meal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM students WHERE tg_user_id = %s", (user_id,))
    student_id = cur.fetchone()
    cur.close()
    conn.close()

    if not student_id:
        await update.message.reply_text("You need to register first using /start.")
        return ConversationHandler.END

    context.user_data["student_id"] = student_id[0]
    tomorrow_weekday = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%A")
    menu_api_url = os.getenv("MENU_API_URL", "http://127.0.0.1:8000")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{menu_api_url}/menu/{tomorrow_weekday}")
            response.raise_for_status()
            menu_data = response.json()
            menu_text = f"Tomorrow's Menu ({tomorrow_weekday}):\n"
            menu_text += f"Breakfast: {menu_data.get('breakfast', 'N/A')}\n"
            menu_text += f"Lunch: {menu_data.get('lunch', 'N/A')}\n"
            menu_text += f"Snacks: {menu_data.get('snacks', 'N/A')}\n"
            menu_text += f"Dinner: {menu_data.get('dinner', 'N/A')}"
            await update.message.reply_text(menu_text)
    except Exception as e:
        logger.error(f"Error fetching tomorrow's menu: {e}")
        await update.message.reply_text("Could not fetch tomorrow's menu.")

    reply_keyboard = [["Veg", "Non-Veg"]]
    await update.message.reply_text(
        "Veg or Non-Veg?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, input_field_placeholder="Veg or Non-Veg?")
    )
    return MEAL_CHOICE_VEG_NONVEG

async def meal_choice_caffeine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    veg_or_nonveg = update.message.text
    if veg_or_nonveg not in ["Veg", "Non-Veg"]:
        await update.message.reply_text("Invalid choice. Choose 'Veg' or 'Non-Veg'.")
        return MEAL_CHOICE_VEG_NONVEG
    context.user_data["veg_or_nonveg"] = veg_or_nonveg
    reply_keyboard = [["Tea", "Coffee"], ["Black Coffee", "Black Tea"], ["None"]]
    await update.message.reply_text(
        "Caffeine option?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return MEAL_CHOICE_CAFFEINE

async def save_meal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    caffeine_choice = update.message.text
    valid_choices = ["Tea", "Coffee", "Black Coffee", "Black Tea", "None"]
    if caffeine_choice not in valid_choices:
        await update.message.reply_text("Invalid choice. Choose from the options.")
        return MEAL_CHOICE_CAFFEINE

    student_id = context.user_data["student_id"]
    veg_or_nonveg = context.user_data["veg_or_nonveg"]
    today = datetime.date.today()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO meal_choices (student_id, date, veg_or_nonveg, caffeine_choice)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (student_id, date) DO UPDATE SET
                veg_or_nonveg = EXCLUDED.veg_or_nonveg,
                caffeine_choice = EXCLUDED.caffeine_choice
            """,
            (student_id, today, veg_or_nonveg, caffeine_choice)
        )
        conn.commit()
        await update.message.reply_text("Your meal choice has been saved!", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving meal choice: {e}")
        await update.message.reply_text("An error occurred. Try again later.", reply_markup=ReplyKeyboardRemove())
    finally:
        cur.close()
        conn.close()
    return ConversationHandler.END

# --- Ticket handler --- #
async def ticket(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🎫 Ticket for {user.first_name} ({user.id})\nDate: {datetime.date.today()}"
    )

# --- Weekly choice handlers and view menu handlers omitted for brevity, include as previously written --- #

# Initialize FastAPI app and Telegram bot
fastapi_app = FastAPI()
request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).request(request).build()
asyncio.get_event_loop().run_until_complete(application.initialize())

def add_handlers(app: Application) -> None:
    # Registration handler
    registration_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_admission_no)],
            ADMISSION_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_passout_year)],
            PASSOUT_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_profile_photo)],
            PROFILE_PHOTO: [MessageHandler(filters.PHOTO, save_student_data)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(registration_conv_handler)

    # Meal choice
    meal_choice_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("mealchoice", meal_choice)],
        states={
            MEAL_CHOICE_VEG_NONVEG: [MessageHandler(filters.TEXT & ~filters.COMMAND, meal_choice_caffeine)],
            MEAL_CHOICE_CAFFEINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_meal_choice)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(meal_choice_conv_handler)

    # Ticket
    app.add_handler(CommandHandler("ticket", ticket))

    # Include weekly choice and view menu handlers here exactly as previously written

# Add handlers
add_handlers(application)

@fastapi_app.post(os.environ.get("WEBHOOK_PATH", "/webhook"))
async def telegram_webhook(request: Request):
    update_json = await request.json()
    update = Update.de_json(update_json, application.bot)
    await application.process_update(update)
    return {"ok": True}

if __name__ == "__main__":
    uvicorn.run(fastapi_app, host="0.0.0.0", port=int(os.environ.get("PORT", 8443)))