import logging
import datetime
import os
import psycopg2
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
# set higher logging level for httpx to avoid all GET and POST requests being logged
logging.getLogger("httpx").setLevel(logging.WARNING)

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

# Database connection function
def get_db_connection():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        database=os.getenv("DB_NAME", "mess_bot_db"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
    )

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Send a message when the command /start is issued."""
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
    """Stores the name and asks for admission number."""
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Please tell me your Hostel Admission Number.")
    return ADMISSION_NO

async def ask_passout_year(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the admission number and asks for pass-out year."""
    context.user_data["admission_no"] = update.message.text
    await update.message.reply_text("Please tell me your Pass-out Year.")
    return PASSOUT_YEAR

async def ask_profile_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the pass-out year and asks for profile photo."""
    try:
        passout_year = int(update.message.text)
        context.user_data["passout_year"] = passout_year
        await update.message.reply_text("Please send your profile photo.")
        return PROFILE_PHOTO
    except ValueError:
        await update.message.reply_text("That doesn't look like a valid year. Please enter a 4-digit year (e.g., 2024).")
        return PASSOUT_YEAR

async def save_student_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores the profile photo and saves all student data to the database."""
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
        await update.message.reply_text(
            f"Thank you, {name}! You are now registered. Welcome to Hostel Bot!"
        )
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        await update.message.reply_text(
            "It seems you or your admission number is already registered. Please contact support if you believe this is an error."
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving student data: {e}")
        await update.message.reply_text(
            "An error occurred during registration. Please try again later."
        )
    finally:
        cur.close()
        conn.close()

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text(
        "Registration cancelled. You can start again with /start.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END

def main() -> None:
    """Start the bot."""
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    # Add conversation handler with states
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_admission_no)],
            ADMISSION_NO: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_passout_year)],
            PASSOUT_YEAR: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_profile_photo)],
            PROFILE_PHOTO: [MessageHandler(filters.PHOTO, save_student_data)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

async def meal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the meal choice conversation."""
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id FROM students WHERE tg_user_id = %s", (user_id,))
    student_id = cur.fetchone()
    cur.close()
    conn.close()

    if not student_id:
        await update.message.reply_text(
            "You need to register first using the /start command."
        )
        return ConversationHandler.END

    context.user_data["student_id"] = student_id[0]
    reply_keyboard = [["Veg", "Non-Veg"]]
    await update.message.reply_text(
        "Veg or Non-Veg?",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Veg or Non-Veg?"
        ),
    )
    return MEAL_CHOICE_VEG_NONVEG


async def meal_choice_caffeine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores veg/non-veg choice and asks for caffeine option."""
    veg_or_nonveg = update.message.text
    if veg_or_nonveg not in ["Veg", "Non-Veg"]:
        await update.message.reply_text("Invalid choice. Please choose 'Veg' or 'Non-Veg'.")
        return MEAL_CHOICE_VEG_NONVEG
    context.user_data["veg_or_nonveg"] = veg_or_nonveg
    reply_keyboard = [["Tea", "Coffee"], ["Black Coffee", "Black Tea"], ["None"]]
    await update.message.reply_text(
        "Caffeine option (Tea / Coffee / Black Coffee / Black Tea / None)?",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Caffeine option?"
        ),
    )
    return MEAL_CHOICE_CAFFEINE


async def save_meal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores caffeine choice and saves all meal choice data to the database."""
    caffeine_choice = update.message.text
    valid_caffeine_choices = ["Tea", "Coffee", "Black Coffee", "Black Tea", "None"]
    if caffeine_choice not in valid_caffeine_choices:
        await update.message.reply_text("Invalid caffeine choice. Please choose from the provided options.")
        return MEAL_CHOICE_CAFFEINE

    context.user_data["caffeine_choice"] = caffeine_choice

    student_id = context.user_data["student_id"]
    veg_or_nonveg = context.user_data["veg_or_nonveg"]
    today = datetime.date.today()

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO meal_choices (student_id, date, veg_or_nonveg, caffeine_choice) VALUES (%s, %s, %s, %s)",
            (student_id, today, veg_or_nonveg, caffeine_choice),
        )
        conn.commit()
        await update.message.reply_text(
            "Your meal choice has been saved for tomorrow!",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving meal choice: {e}")
        await update.message.reply_text(
            "An error occurred while saving your meal choice. Please try again later.",
            reply_markup=ReplyKeyboardRemove(),
        )
    finally:
        cur.close()
        conn.close()

    return ConversationHandler.END


def main() -> None:
    """Start the bot."""
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()

    # Add conversation handler for student registration
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
    application.add_handler(registration_conv_handler)

    # Add conversation handler for meal choice
    meal_choice_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("mealchoice", meal_choice)],
        states={
            MEAL_CHOICE_VEG_NONVEG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, meal_choice_caffeine)
            ],
            MEAL_CHOICE_CAFFEINE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_meal_choice)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(meal_choice_conv_handler)

    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()