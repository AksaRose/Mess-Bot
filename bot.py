import logging
import datetime
import os
import psycopg2
import httpx
import pytz # Import pytz
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
) = range(4)

(
    MEAL_CHOICE_VEG_NONVEG,
    MEAL_CHOICE_CAFFEINE,
) = range(4, 6)

(
    WEEKLY_CHOICE_DAY,
    WEEKLY_CHOICE_VEG_NONVEG,
    WEEKLY_CHOICE_CAFFEINE,
) = range(6, 9)

(VIEW_MENU_DAY,) = range(9, 10)

(POST_REGISTRATION_CHOICE,) = range(10, 11)

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
        reply_keyboard = [["Today's Food Ticket", "Tomorrow's Meal Choice"]]
        await update.message.reply_text(
            f"Thank you, {name}! You are now registered. Welcome to Hostel Bot!\n"
            "Do you want today’s food ticket or give meal choice for tomorrow?",
            reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
        )
        return POST_REGISTRATION_CHOICE
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        await update.message.reply_text("You are already registered. Contact support if this is an error.")
        return ConversationHandler.END # End conversation if already registered
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving student data: {e}")
        await update.message.reply_text("An error occurred during registration. Please try again later.")
        return ConversationHandler.END # End conversation on error
    finally:
        cur.close()
        conn.close()

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Registration cancelled. Use /start to begin again.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END

# --- Post-registration choice handler --- #
async def handle_post_registration_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    if choice == "Today's Food Ticket":
        return await ticket(update, context)
    elif choice == "Tomorrow's Meal Choice":
        return await meal_choice(update, context)
    else:
        await update.message.reply_text("Invalid choice. Please select 'Today's Food Ticket' or 'Tomorrow's Meal Choice'.")
        return POST_REGISTRATION_CHOICE

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
    tomorrow_date = datetime.date.today() + datetime.timedelta(days=1)
    tomorrow_weekday = tomorrow_date.strftime("%A")
    
    conn.close() # Close connection used for student_id, open new for menu query

    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("SELECT breakfast, lunch, snacks, dinner FROM menus WHERE weekday = %s", (tomorrow_weekday,))
        menu_data = cur.fetchone()

        if menu_data:
            menu_text = f"Tomorrow's Menu ({tomorrow_weekday}):\n"
            menu_text += f"Breakfast: {menu_data[0] or 'N/A'}\n"
            menu_text += f"Lunch: {menu_data[1] or 'N/A'}\n"
            menu_text += f"Snacks: {menu_data[2] or 'N/A'}\n"
            menu_text += f"Dinner: {menu_data[3] or 'N/A'}"
            await update.message.reply_text(menu_text)
        else:
            await update.message.reply_text(f"No menu available for tomorrow ({tomorrow_weekday}).")
    except Exception as e:
        logger.error(f"Error fetching tomorrow's menu from DB: {e}")
        await update.message.reply_text("Could not fetch tomorrow's menu.")
    finally:
        cur.close()
        conn.close()

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
    # Define the timezone for Asia/Calcutta
    kolkata_timezone = pytz.timezone('Asia/Kolkata')
    
    # Get the current time in the specified timezone
    today_date_time = datetime.datetime.now(kolkata_timezone)
    
    # Calculate tomorrow's date based on the timezone-aware today
    tomorrow_date = today_date_time.date() + datetime.timedelta(days=1)

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
            (student_id, tomorrow_date, veg_or_nonveg, caffeine_choice)
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

# --- Weekly choice handlers --- #
async def weekly_choice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
    reply_keyboard = [
        ["Monday", "Tuesday", "Wednesday"],
        ["Thursday", "Friday", "Saturday"],
        ["Sunday"]
    ]
    await update.message.reply_text(
        "For which day do you want to set your weekly meal preference?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, input_field_placeholder="Select Day")
    )
    return WEEKLY_CHOICE_DAY

async def weekly_choice_veg_nonveg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    day = update.message.text
    valid_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    if day not in valid_days:
        await update.message.reply_text("Invalid day. Please choose a day from the keyboard.")
        return WEEKLY_CHOICE_DAY
    context.user_data["weekly_choice_day"] = day

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT breakfast, lunch, snacks, dinner FROM menus WHERE weekday = %s", (day,))
        menu_data = cur.fetchone()

        if menu_data:
            menu_text = f"Menu for {day}:\n"
            menu_text += f"Breakfast: {menu_data[0] or 'N/A'}\n"
            menu_text += f"Lunch: {menu_data[1] or 'N/A'}\n"
            menu_text += f"Snacks: {menu_data[2] or 'N/A'}\n"
            menu_text += f"Dinner: {menu_data[3] or 'N/A'}"
            await update.message.reply_text(menu_text)
        else:
            await update.message.reply_text(f"No menu available for {day}.")
    except Exception as e:
        logger.error(f"Error fetching menu for {day} from DB: {e}")
        await update.message.reply_text("Could not fetch menu for the selected day.")
    finally:
        cur.close()
        conn.close()

    reply_keyboard = [["Veg", "Non-Veg"]]
    await update.message.reply_text(
        f"For {day}, Veg or Non-Veg?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, input_field_placeholder="Veg or Non-Veg?")
    )
    return WEEKLY_CHOICE_VEG_NONVEG

async def weekly_choice_caffeine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    veg_or_nonveg = update.message.text
    if veg_or_nonveg not in ["Veg", "Non-Veg"]:
        await update.message.reply_text("Invalid choice. Choose 'Veg' or 'Non-Veg'.")
        return WEEKLY_CHOICE_VEG_NONVEG
    context.user_data["weekly_choice_veg_nonveg"] = veg_or_nonveg
    reply_keyboard = [["Tea", "Coffee"], ["Black Coffee", "Black Tea"], ["None"]]
    await update.message.reply_text(
        "Caffeine option?",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True)
    )
    return WEEKLY_CHOICE_CAFFEINE

async def save_weekly_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    caffeine_choice = update.message.text
    valid_choices = ["Tea", "Coffee", "Black Coffee", "Black Tea", "None"]
    if caffeine_choice not in valid_choices:
        await update.message.reply_text("Invalid choice. Choose from the options.")
        return WEEKLY_CHOICE_CAFFEINE

    student_id = context.user_data["student_id"]
    day = context.user_data["weekly_choice_day"]
    veg_or_nonveg = context.user_data["weekly_choice_veg_nonveg"]

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO weekly_choices (student_id, weekday, veg_or_nonveg, caffeine_choice)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (student_id, weekday) DO UPDATE SET
                veg_or_nonveg = EXCLUDED.veg_or_nonveg,
                caffeine_choice = EXCLUDED.caffeine_choice
            """,
            (student_id, day, veg_or_nonveg, caffeine_choice)
        )
        conn.commit()
        await update.message.reply_text(f"Your weekly preference for {day} has been saved!", reply_markup=ReplyKeyboardRemove())
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving weekly choice: {e}")
        await update.message.reply_text("An error occurred. Try again later.", reply_markup=ReplyKeyboardRemove())
    finally:
        cur.close()
        conn.close()
    return ConversationHandler.END

# --- Ticket handler --- #
async def ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()
    
    try:
        # Fetch student details
        cur.execute(
            "SELECT id, name, profile_file_id FROM students WHERE tg_user_id = %s",
            (user_id,)
        )
        student_data = cur.fetchone()

        if not student_data:
            await update.message.reply_text("You need to register first using /start.")
            return ConversationHandler.END

        student_id, student_name, profile_file_id = student_data

        # Determine today's meal choice based on hierarchy: meal_choices > weekly_choices > default non-veg
        # Define the timezone for Asia/Calcutta
        kolkata_timezone = pytz.timezone('Asia/Kolkata')
        
        # Get the current time in the specified timezone
        today_date_time = datetime.datetime.now(kolkata_timezone)
        
        # Extract today's date and weekday
        today_date = today_date_time.date()
        today_weekday = today_date.strftime("%A")

        today_meal_choice = None
        
        # 1. Check meal_choices table for today's explicit choice
        cur.execute(
            "SELECT veg_or_nonveg, caffeine_choice FROM meal_choices WHERE student_id = %s AND date = %s",
            (student_id, today_date)
        )
        today_meal_choice = cur.fetchone()

        if not today_meal_choice:
            # 2. Else, check weekly_choices for today's preference
            cur.execute(
                "SELECT veg_or_nonveg, caffeine_choice FROM weekly_choices WHERE student_id = %s AND weekday = %s",
                (student_id, today_weekday)
            )
            today_meal_choice = cur.fetchone()

        veg_nonveg = "Non-Veg (Default)"
        caffeine = "None"
        if today_meal_choice:
            veg_nonveg = today_meal_choice[0] if today_meal_choice[0] is not None else "Non-Veg (Default)"
            caffeine = today_meal_choice[1] if today_meal_choice[1] is not None else "None"

        # Generate ticket image
        ticket_image = await generate_ticket_image(
            student_name,
            today_date.strftime("%b %d"), # Use timezone-aware today_date for formatting
            veg_nonveg,
            caffeine,
            profile_file_id,
            context
        )
        
        # Send the generated image
        await update.message.reply_photo(photo=ticket_image)

    except Exception as e:
        logger.error(f"Error generating or sending ticket: {e}")
        await update.message.reply_text("An error occurred while generating your food ticket. Please try again later.")
    finally:
        cur.close()
        conn.close()
    return ConversationHandler.END

async def generate_ticket_image(
    name: str,
    date_str: str,
    veg_nonveg: str,
    caffeine: str,
    profile_file_id: str,
    context: ContextTypes.DEFAULT_TYPE
) -> bytes:
    # Get profile photo
    profile_photo_file = await context.bot.get_file(profile_file_id)
    profile_photo_bytes = await profile_photo_file.download_as_bytearray()
    profile_img = Image.open(io.BytesIO(profile_photo_bytes)).convert("RGB") # Convert to RGB for simpler handling

    # Create ticket image
    # Increase image size to make default font appear larger
    img_width, img_height = 2560, 2000 # Ensure square for better vertical centering
    img = Image.new("RGB", (img_width, img_height), color="white")
    d = ImageDraw.Draw(img)

    font_path = "fonts/Roboto_Condensed-Bold.ttf" # Path to the bundled font

    try:
        name_font = ImageFont.truetype(font_path, 200) # Increased font size
        date_font = ImageFont.truetype(font_path, 160) # Increased font size
        veg_nonveg_font = ImageFont.truetype(font_path, 300) # Increased font size
        caffeine_font = ImageFont.truetype(font_path, 200) # Increased font size
        ticket_title_font = ImageFont.truetype(font_path, 180) # Increased font size
    except IOError:
        logger.error(f"Font file not found at {font_path}. Falling back to default PIL font.")
        name_font = ImageFont.load_default()
        date_font = ImageFont.load_default()
        choice_font = ImageFont.load_default()
        ticket_title_font = ImageFont.load_default()

    # Resize profile photo to fit one side, maintaining aspect ratio
    photo_width = img_width // 2
    photo_height = img_height
    profile_img.thumbnail((photo_width, photo_height), Image.Resampling.LANCZOS)

    # Calculate y-coordinate to center the profile photo vertically
    y_position = (img_height - profile_img.height) // 2

    # Paste profile photo on the left side, centered vertically with left padding
    img.paste(profile_img, (150, y_position)) # Added 50 pixels of left padding

    # Calculate text positions for the right side
    text_x_start = img_width // 2 + 100 # Adjusted x position for larger fonts
    
    # Add text details
    d.text((text_x_start, 400), name, fill=(0, 0, 0), font=name_font) # Adjusted Y position
    d.text((text_x_start, 600), f" {date_str}", fill=(0, 0, 0), font=date_font) # Adjusted Y position
    # Adjust position for multi-line meal choice text
    # Calculate text height using textbbox for accurate positioning
    bbox_veg_nonveg = veg_nonveg_font.getbbox(veg_nonveg)
    text_height_veg_nonveg = bbox_veg_nonveg[3] - bbox_veg_nonveg[1]

    # Adjusted positions for larger image and clearer separation
    d.text((text_x_start, 1200), veg_nonveg, fill=(0, 0, 0), font=veg_nonveg_font) # Adjusted Y position
    d.text((text_x_start, 1200 + text_height_veg_nonveg + 100), caffeine, fill=(0, 0, 0), font=caffeine_font) # Adjusted Y position and increased padding
    # Removed the "🎫 Food Ticket" text

    # Convert to bytes
    byte_arr = io.BytesIO()
    img.save(byte_arr, format="PNG")
    return byte_arr.getvalue()

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
            POST_REGISTRATION_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_post_registration_choice)],
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

    # Weekly choice
    weekly_choice_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("weeklychoice", weekly_choice_start)],
        states={
            WEEKLY_CHOICE_DAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_choice_veg_nonveg)],
            WEEKLY_CHOICE_VEG_NONVEG: [MessageHandler(filters.TEXT & ~filters.COMMAND, weekly_choice_caffeine)],
            WEEKLY_CHOICE_CAFFEINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_weekly_choice)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    app.add_handler(weekly_choice_conv_handler)

    # View menu (assuming existing view menu handlers would be here)

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