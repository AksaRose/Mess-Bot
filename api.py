from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import datetime # Import datetime
import asyncpg
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware # Import CORSMiddleware

load_dotenv()

from fastapi.middleware.cors import CORSMiddleware # Import CORSMiddleware

app = FastAPI()

origins = [
    "http://localhost",
    "http://localhost:5173", # React development server
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database connection function
async def get_db_connection():
    return await asyncpg.connect(os.getenv("DATABASE_URL"))

@app.get("/test-db")
async def test_db():
    conn = None
    try:
        conn = await asyncpg.connect(
            host=os.getenv("PGHOST"),
            user=os.getenv("PGUSER"),
            password=os.getenv("PGPASSWORD"),
            database=os.getenv("PGDATABASE"),
            port=os.getenv("PGPORT")
        )
        result = await conn.fetchval("SELECT NOW();")  # simple query
        return {"status": "connected", "time": str(result)}
    except Exception as e:
        return {"status": "failed", "error": str(e)}
    finally:
        if conn:
            await conn.close()

class Menu(BaseModel):
    weekday: str
    breakfast: str = None
    lunch: str = None
    snacks: str = None
    dinner: str = None

@app.post("/menu")
async def create_or_update_menu(menu: Menu):
    conn = None
    try:
        conn = await get_db_connection()
        await conn.execute(
            """
            INSERT INTO menu (weekday, breakfast, lunch, snacks, dinner)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (weekday) DO UPDATE SET
                breakfast = EXCLUDED.breakfast,
                lunch = EXCLUDED.lunch,
                snacks = EXCLUDED.snacks,
                dinner = EXCLUDED.dinner
            """,
            menu.weekday, menu.breakfast, menu.lunch, menu.snacks, menu.dinner
        )
        return {"message": f"Menu for {menu.weekday} created/updated successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            await conn.close()

@app.get("/menu/{weekday}")
async def get_menu(weekday: str):
    conn = None
    try:
        conn = await get_db_connection()
        row = await conn.fetchrow(
            "SELECT breakfast, lunch, snacks, dinner FROM menu WHERE weekday = $1",
            weekday
        )
        if row:
            return {
                "weekday": weekday,
                "breakfast": row["breakfast"],
                "lunch": row["lunch"],
                "snacks": row["snacks"],
                "dinner": row["dinner"]
            }
        raise HTTPException(status_code=404, detail=f"Menu for {weekday} not found.")
    except asyncpg.exceptions.PostgresError as e:
        # Catch specific PostgreSQL errors if needed, otherwise re-raise as 500
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
    except HTTPException: # Re-raise HTTPException directly
        raise
    except Exception as e:
        # Catch other unexpected errors
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {e}")
    finally:
        if conn:
            await conn.close()

@app.get("/mealcount/tomorrow")
async def get_meal_counts_tomorrow():
    conn = None
    try:
        conn = await get_db_connection()
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        tomorrow_weekday = tomorrow.strftime("%A")

        # Initialize counts and lists for students
        veg_count = 0
        non_veg_count = 0
        caffeine_counts = {"Tea": 0, "Coffee": 0, "Black Coffee": 0, "Black Tea": 0, "None": 0}
        veg_students = []
        non_veg_students = []
        caffeine_students = {"Tea": [], "Coffee": [], "Black Coffee": [], "Black Tea": [], "None": []}

        # Fetch all students
        students = await conn.fetch("SELECT id, name, tg_user_id FROM students")

        for student in students:
            student_id = student["id"]
            student_name = student["name"]
            
            # 1. Check for today's meal choice (made yesterday)
            meal_choice = await conn.fetchrow(
                "SELECT veg_or_nonveg, caffeine_choice FROM meal_choices WHERE student_id = $1 AND date = $2",
                student_id, tomorrow - datetime.timedelta(days=1) # yesterday for tomorrow's meal
            )

            veg_or_nonveg = None
            caffeine_choice = None

            if meal_choice:
                veg_or_nonveg = meal_choice["veg_or_nonveg"]
                caffeine_choice = meal_choice["caffeine_choice"]
            else:
                # 2. Else check weekly choice
                weekly_choice = await conn.fetchrow(
                    "SELECT veg_or_nonveg, caffeine_choice FROM weekly_choices WHERE student_id = $1 AND weekday = $2",
                    student_id, tomorrow_weekday
                )
                if weekly_choice:
                    veg_or_nonveg = weekly_choice["veg_or_nonveg"]
                    caffeine_choice = weekly_choice["caffeine_choice"]
                else:
                    # 3. Else default to Non-Veg
                    veg_or_nonveg = "Non-Veg"
                    caffeine_choice = "None"
            
            # Aggregate counts and student names
            if veg_or_nonveg == "Veg":
                veg_count += 1
                veg_students.append(student_name)
            elif veg_or_nonveg == "Non-Veg":
                non_veg_count += 1
                non_veg_students.append(student_name)
            
            if caffeine_choice in caffeine_counts:
                caffeine_counts[caffeine_choice] += 1
                caffeine_students[caffeine_choice].append(student_name)

        return {
            "date": tomorrow.strftime("%Y-%m-%d"),
            "veg": veg_count,
            "non_veg": non_veg_count,
            "veg_students": veg_students,
            "non_veg_students": non_veg_students,
            "caffeine": caffeine_counts,
            "caffeine_students": caffeine_students
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if conn:
            await conn.close()

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)