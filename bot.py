import logging
import datetime
import os
import psycopg2
import httpx # Import httpx
from dotenv import load_dotenv # Import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest # Import HTTPXRequest

load_dotenv() # Load environment variables from .env file

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

# States for weekly choice conversation
(
    WEEKLY_CHOICE_DAY,
    WEEKLY_CHOICE_VEG_NONVEG,
    WEEKLY_CHOICE_CAFFEINE,
) = range(6, 9) # Continue range from previous states

# States for view menu conversation
(
    VIEW_MENU_DAY,
) = range(9, 10) # Continue range

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

async def meal_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the meal choice conversation by displaying tomorrow's menu."""
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

    # Fetch and display tomorrow's menu
    tomorrow_weekday = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%A")
    menu_api_url = os.getenv("MENU_API_URL", "http://127.0.0.1:8000")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{menu_api_url}/menu/{tomorrow_weekday}")
            response.raise_for_status()  # Raise an exception for HTTP errors
            menu_data = response.json()

            menu_text = f"Tomorrow's Menu ({tomorrow_weekday}):\n"
            menu_text += f"Breakfast: {menu_data.get('breakfast', 'N/A')}\n"
            menu_text += f"Lunch: {menu_data.get('lunch', 'N/A')}\n"
            menu_text += f"Snacks: {menu_data.get('snacks', 'N/A')}\n"
            menu_text += f"Dinner: {menu_data.get('dinner', 'N/A')}"
            await update.message.reply_text(menu_text)

    except httpx.HTTPStatusError as e:
        logger.warning(f"Could not fetch tomorrow's menu: {e.response.status_code} - {e.response.text}")
        await update.message.reply_text("Could not fetch tomorrow's menu at this time.")
    except httpx.RequestError as e:
        logger.error(f"Error making request to menu API: {e}")
        await update.message.reply_text("An error occurred while trying to fetch tomorrow's menu.")

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
            """
            INSERT INTO meal_choices (student_id, date, veg_or_nonveg, caffeine_choice)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (student_id, date) DO UPDATE SET
                veg_or_nonveg = EXCLUDED.veg_or_nonveg,
                caffeine_choice = EXCLUDED.caffeine_choice
            """,
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
    # Configure httpx client with a longer timeout for all HTTP requests made by the bot
    # Configure httpx client with a longer timeout for all HTTP requests made by the bot
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0)
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).request(request).build()

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

    application.add_handler(CommandHandler("ticket", ticket))


    # Add conversation handler for weekly choice
    weekly_choice_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("weeklychoice", weekly_choice_start)],
        states={
            WEEKLY_CHOICE_DAY: [
                MessageHandler(
                    filters.Regex("^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)$"),
                    weekly_choice_veg_nonveg,
                )
            ],
            WEEKLY_CHOICE_VEG_NONVEG: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, # Accept any text for initial processing
                    weekly_choice_caffeine
                )
            ],
            WEEKLY_CHOICE_CAFFEINE: [
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, # Accept any text for initial processing
                    weekly_choice_save,
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(weekly_choice_conv_handler)

    # Add conversation handler for view menu
    view_menu_conv_handler = ConversationHandler(
        entry_points=[CommandHandler("menu", view_menu_start)],
        states={
            VIEW_MENU_DAY: [
                MessageHandler(
                    filters.Regex("^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)$"),
                    display_menu_for_day,
                )
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )
    application.add_handler(view_menu_conv_handler)
 
    # For Railway deployment, switch to webhook mode
    # The URL and port will be provided by Railway
    if os.environ.get("USE_WEBHOOK", "false").lower() == "true":
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", 8443)),
            url_path=os.environ.get("WEBHOOK_PATH", ""),
            webhook_url=os.environ.get("WEBHOOK_URL", "") + os.environ.get("WEBHOOK_PATH", ""),
        )
    else:
        application.run_polling(allowed_updates=Update.ALL_TYPES)


import io
import asyncio
from functools import partial
from PIL import Image, ImageDraw, ImageFont, ImageOps

def _generate_ticket_image(student_name, ticket_date, veg_or_nonveg, caffeine_choice, profile_photo_bytes=None):
    """Helper function to generate the ticket image (CPU-bound)."""
    img_width = 600
    img_height = 400
    background_color = (215, 240, 57) # #D7F039
    text_color = (0, 0, 0) # Black

    img = Image.new('RGB', (img_width, img_height), color = background_color)
    d = ImageDraw.Draw(img)

    # Use default font for simplicity and cross-platform compatibility
    font_name_date = ImageFont.load_default(size=40)
    font_meal = ImageFont.load_default(size=60)
    font_caffeine = ImageFont.load_default(size=30)
    
    # Text positions for left half (0-300px width)
    x_text_offset = 20

    d.text((x_text_offset, 20), f"{student_name}", fill=text_color, font=font_name_date)
    d.text((x_text_offset, 80), f"{ticket_date}", fill=text_color, font=font_name_date)
    d.text((x_text_offset, 180), f"{veg_or_nonveg}", fill=text_color, font=font_meal)
    d.text((x_text_offset, 280), f"Caffeine: {caffeine_choice}", fill=text_color, font=font_caffeine)

    # Profile photo for the right half (300-600px width)
    if profile_photo_bytes:
        try:
            profile_img = Image.open(io.BytesIO(profile_photo_bytes))
            
            # Resize photo to fill the right half (300x400) while maintaining aspect ratio
            # and then center it in that half
            photo_target_width = 300
            photo_target_height = 400
            profile_img.thumbnail((photo_target_width, photo_target_height), Image.LANCZOS)
            
            # Calculate position to center in the right half
            x_photo = img_width - photo_target_width + (photo_target_width - profile_img.width) // 2
            y_photo = (img_height - profile_img.height) // 2
            
            img.paste(profile_img, (x_photo, y_photo))
        except Exception as e:
            logger.error(f"Error processing profile photo in helper: {e}")
            d.text((img_width - 280, 20), "Photo Error", fill=(255,0,0), font=font_caffeine)
    else:
        d.text((img_width - 280, 20), "No profile photo", fill=text_color, font=font_caffeine)

    byte_io = io.BytesIO()
    img.save(byte_io, format='PNG')
    byte_io.seek(0)
    return byte_io

async def ticket(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Generates and sends a food ticket for today based on yesterday's choice as an image."""
    user_id = update.effective_user.id
    conn = get_db_connection()
    cur = conn.cursor()

    profile_photo_bytes = None

    try:
        cur.execute("SELECT id, name, profile_file_id FROM students WHERE tg_user_id = %s", (user_id,))
        student = cur.fetchone()

        if not student:
            await update.message.reply_text(
                "You need to register first using the /start command."
            )
            return

        student_id, student_name, profile_file_id = student
        yesterday = datetime.date.today() - datetime.timedelta(days=1)

        # 1. Check for today's meal choice (made yesterday)
        cur.execute(
            "SELECT veg_or_nonveg, caffeine_choice FROM meal_choices WHERE student_id = %s AND date = %s",
            (student_id, yesterday),
        )
        meal_choice_data = cur.fetchone()

        if meal_choice_data:
            veg_or_nonveg, caffeine_choice = meal_choice_data
        else:
            # 2. Else check weekly choice
            today_weekday = datetime.date.today().strftime("%A")
            cur.execute(
                "SELECT veg_or_nonveg, caffeine_choice FROM weekly_choices WHERE student_id = %s AND weekday = %s",
                (student_id, today_weekday),
            )
            weekly_choice_data = cur.fetchone()

            if weekly_choice_data:
                veg_or_nonveg, caffeine_choice = weekly_choice_data
            else:
                # 3. Else default to Non-Veg
                veg_or_nonveg = "Non-Veg"
                caffeine_choice = "None"
                await update.message.reply_text(
                    "No meal choice found for yesterday or in your weekly plan. Defaulting to Non-Veg with no caffeine."
                )

        ticket_date = datetime.date.today().strftime("%d %b %Y")

        # Download profile photo if available
        if profile_file_id:
            try:
                file = await context.bot.get_file(profile_file_id)
                profile_photo_bytes = await file.download_as_bytearray()
            except Exception as e:
                logger.error(f"Error downloading profile photo: {e}")
                # Don't fail the entire ticket generation if photo download fails

        # Run image generation in a thread pool executor to avoid blocking the event loop
        # This speeds up perceived performance for concurrent users
        byte_io = _generate_ticket_image(student_name, ticket_date, veg_or_nonveg, caffeine_choice, profile_photo_bytes)

        await update.message.reply_photo(photo=byte_io, caption="Here is your food ticket!")

    except Exception as e:
        logger.error(f"Error generating ticket: {e}")
        await update.message.reply_text(
            "An error occurred while generating your ticket. Please try again later."
        )
    finally:
        cur.close()
        conn.close()

async def weekly_choice_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the weekly meal choice conversation."""
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
    context.user_data["weekly_choices"] = {}  # Initialize dictionary to store choices
    context.user_data["first_day_set"] = False # Flag to track if the first day has been set

    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    reply_keyboard = [weekdays[i:i+3] for i in range(0, len(weekdays), 3)] # Group by 3 for keyboard layout

    await update.message.reply_text(
        "Let's set up your weekly meal plan. Which day would you like to set first?",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Select a day"
        ),
    )
    return WEEKLY_CHOICE_DAY

async def weekly_choice_veg_nonveg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Displays the menu for the selected day and asks for veg/non-veg choice."""
    message_text = update.message.text
    
    context.user_data["current_weekday"] = message_text
    current_weekday = context.user_data["current_weekday"]

    # Fetch and display menu for the selected day
    menu_api_url = os.getenv("MENU_API_URL", "http://127.0.0.1:8000")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{menu_api_url}/menu/{current_weekday}")
            response.raise_for_status()  # Raise an exception for HTTP errors
            menu_data = response.json()

            menu_text = f"Menu for {current_weekday}:\n"
            menu_text += f"Breakfast: {menu_data.get('breakfast', 'N/A')}\n"
            menu_text += f"Lunch: {menu_data.get('lunch', 'N/A')}\n"
            menu_text += f"Snacks: {menu_data.get('snacks', 'N/A')}\n"
            menu_text += f"Dinner: {menu_data.get('dinner', 'N/A')}"
            await update.message.reply_text(menu_text)

    except httpx.HTTPStatusError as e:
        logger.warning(f"Could not fetch menu for {current_weekday}: {e.response.status_code} - {e.response.text}")
        await update.message.reply_text(f"Could not fetch menu for {current_weekday} at this time.")
    except httpx.RequestError as e:
        logger.error(f"Error making request to menu API: {e}")
        await update.message.reply_text("An error occurred while trying to fetch the menu.")

    reply_keyboard = [["Veg", "Non-Veg"]]
    if context.user_data["first_day_set"]: # Only add "Skip" and "Done" after the first day
        reply_keyboard.append(["Skip this day", "Done"])
    
    await update.message.reply_text(
        f"For {context.user_data['current_weekday']}, Veg or Non-Veg?",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Veg or Non-Veg?"
        ),
    )
    context.user_data["first_day_set"] = True # Set flag after the first day's question
    return WEEKLY_CHOICE_VEG_NONVEG

async def weekly_choice_caffeine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores veg/non-veg choice and asks for caffeine option."""
    message_text = update.message.text
    if message_text == "Done":
        return await done_weekly_choice(update, context)
    if message_text == "Skip this day":
        return await skip_day(update, context)

    context.user_data["current_veg_nonveg"] = message_text
    reply_keyboard = [["Tea", "Coffee"], ["Black Coffee", "Black Tea"], ["None"]]
    await update.message.reply_text(
        "Caffeine option (Tea / Coffee / Black Coffee / Black Tea / None)?",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Caffeine option?"
        ),
    )
    return WEEKLY_CHOICE_CAFFEINE

async def weekly_choice_save(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Stores caffeine choice and saves the weekly choice for the day to the database."""
    caffeine_choice = update.message.text
    if caffeine_choice == "Done":
        return await done_weekly_choice(update, context)
    if caffeine_choice == "Skip this day":
        return await skip_day(update, context)
    
    current_weekday = context.user_data["current_weekday"]
    veg_or_nonveg = context.user_data["current_veg_nonveg"]
    student_id = context.user_data["student_id"]

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
            (student_id, current_weekday, veg_or_nonveg, caffeine_choice),
        )
        conn.commit()
        await update.message.reply_text(
            f"Your choice for {current_weekday} has been saved: {veg_or_nonveg}, {caffeine_choice}.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as e:
        conn.rollback()
        logger.error(f"Error saving weekly choice: {e}")
        await update.message.reply_text(
            "An error occurred while saving your weekly choice. Please try again.",
            reply_markup=ReplyKeyboardRemove(),
        )
    finally:
        cur.close()
        conn.close()

    # Ask for next day or end conversation
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    current_day_index = weekdays.index(current_weekday)
    
    if current_day_index + 1 < len(weekdays):
        next_weekday = weekdays[current_day_index + 1]
        context.user_data["current_weekday"] = next_weekday
        reply_keyboard = [weekdays[i:i+3] for i in range(0, len(weekdays), 3)] # Group by 3 for keyboard layout
        await update.message.reply_text(
            f"What about {next_weekday}? Which day would you like to set?", # New prompt
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="Select a day"
            ),
        )
        return WEEKLY_CHOICE_DAY # Go back to asking for a day
    else:
        return await done_weekly_choice(update, context)

async def skip_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Skips setting choice for the current day and moves to the next."""
    message_text = update.message.text
    if message_text == "Done":
        return await done_weekly_choice(update, context)

    current_weekday = context.user_data["current_weekday"]
    await update.message.reply_text(f"Skipped {current_weekday}.")
    
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    current_day_index = weekdays.index(current_weekday)
    
    if current_day_index + 1 < len(weekdays):
        next_weekday = weekdays[current_day_index + 1]
        context.user_data["current_weekday"] = next_weekday
        reply_keyboard = [weekdays[i:i+3] for i in range(0, len(weekdays), 3)] # Group by 3 for keyboard layout
        await update.message.reply_text(
            f"What about {next_weekday}? Which day would you like to set?", # New prompt
            reply_markup=ReplyKeyboardMarkup(
                reply_keyboard, one_time_keyboard=True, input_field_placeholder="Select a day"
            ),
        )
        return WEEKLY_CHOICE_DAY # Go back to asking for a day
    else:
        return await done_weekly_choice(update, context)

async def done_weekly_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Ends the weekly choice conversation."""
    await update.message.reply_text(
        "Weekly meal plan setup complete! You can start again with /weeklychoice.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END

async def view_menu_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Starts the conversation to view menu for a specific day."""
    weekdays = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    reply_keyboard = [weekdays[i:i+3] for i in range(0, len(weekdays), 3)] # Group by 3 for keyboard layout
    
    await update.message.reply_text(
        "Which day's menu would you like to see?",
        reply_markup=ReplyKeyboardMarkup(
            reply_keyboard, one_time_keyboard=True, input_field_placeholder="Select a day"
        ),
    )
    return VIEW_MENU_DAY

async def display_menu_for_day(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Fetches and displays the menu for the selected day."""
    selected_weekday = update.message.text
    
    menu_api_url = os.getenv("MENU_API_URL", "http://127.0.0.1:8000")
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{menu_api_url}/menu/{selected_weekday}")
            response.raise_for_status()  # Raise an exception for HTTP errors
            menu_data = response.json()

            menu_text = f"Menu for {selected_weekday}:\n"
            menu_text += f"Breakfast: {menu_data.get('breakfast', 'N/A')}\n"
            menu_text += f"Lunch: {menu_data.get('lunch', 'N/A')}\n"
            menu_text += f"Snacks: {menu_data.get('snacks', 'N/A')}\n"
            menu_text += f"Dinner: {menu_data.get('dinner', 'N/A')}"
            await update.message.reply_text(menu_text, reply_markup=ReplyKeyboardRemove())

    except httpx.HTTPStatusError as e:
        logger.warning(f"Could not fetch menu for {selected_weekday}: {e.response.status_code} - {e.response.text}")
        await update.message.reply_text(f"Could not fetch menu for {selected_weekday} at this time.", reply_markup=ReplyKeyboardRemove())
    except httpx.RequestError as e:
        logger.error(f"Error making request to menu API: {e}")
        await update.message.reply_text("An error occurred while trying to fetch the menu.", reply_markup=ReplyKeyboardRemove())
    
    return ConversationHandler.END

if __name__ == "__main__":
    main()