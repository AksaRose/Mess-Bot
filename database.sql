CREATE TABLE students (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    admission_no VARCHAR(50) UNIQUE NOT NULL,
    passout_year INT,
    profile_file_id VARCHAR(255),
    tg_user_id BIGINT UNIQUE NOT NULL
);

CREATE TABLE mess_records (
    id SERIAL PRIMARY KEY,
    student_id INT NOT NULL REFERENCES students(id),
    date DATE NOT NULL,
    meal_type VARCHAR(50) NOT NULL,
    amount DECIMAL(10, 2) NOT NULL,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE weekly_choices (
    id SERIAL PRIMARY KEY,
    student_id INT NOT NULL REFERENCES students(id),
    weekday VARCHAR(10) NOT NULL,
    veg_or_nonveg VARCHAR(10),
    caffeine_choice VARCHAR(10),
    UNIQUE (student_id, weekday)
);

CREATE TABLE meal_choices (
    id SERIAL PRIMARY KEY,
    student_id INT NOT NULL REFERENCES students(id),
    date DATE NOT NULL,
    veg_or_nonveg VARCHAR(10) NOT NULL,
    caffeine_choice VARCHAR(10) NOT NULL
);

CREATE TABLE menus (
    id SERIAL PRIMARY KEY,
    weekday VARCHAR(10) UNIQUE NOT NULL,
    breakfast TEXT,
    lunch TEXT,
    snacks TEXT,
    dinner TEXT
);