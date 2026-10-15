# AI-Powered Voice Interview Simulator with Holographic Avatar

An AI-assisted interview simulation system designed to help candidates practice technical interviews, receive structured feedback, and assess their skills.

## Project Overview

This project is built with Django and Python. It includes a question bank, interview session management, adaptive question selection, answer evaluation, and final assessment components.

The goal is to develop an interactive interview experience that can eventually integrate voice interaction and a holographic avatar.

## Current Features

* **Django Web Application:** Backend structure, URL routing, and interview views.
* **Question Bank:** Technical interview questions stored in JSON and database models.
* **Interview Management:** Models for interview sessions, questions, answers, evaluations, and final assessments.
* **Question Selection:** Question engine with difficulty adjustment and skill-based selection logic.
* **Answer Evaluation:** Rule-based evaluation of answers using keywords, expected concepts, and scoring categories.
* **Assessment Components:** A separate final assessment engine.
* **Web Interface:** Templates for the home page, interview setup, interview room, and interview completion.
* **Database:** SQLite for local development.

## Technology Stack

* Python
* Django
* SQLite
* JSON
* HTML and CSS templates
* uv for Python project and dependency management

## Project Structure

```text
AI_Interview_System/
├── config/
├── data/
│   └── question_bank.json
├── interviews/
│   ├── templates/
│   ├── evaluation_engine.py
│   ├── final_assessment_engine.py
│   ├── models.py
│   ├── question_engine.py
│   └── views.py
├── roles/
├── src/
├── manage.py
├── pyproject.toml
└── uv.lock
```

## Local Setup

1. Install Python and uv.

2. Open a terminal in the project directory.

3. Install project dependencies:

   ```bash
   uv sync
   ```

4. Apply database migrations:

   ```bash
   uv run python manage.py migrate
   ```

5. Start the development server:

   ```bash
   uv run python manage.py runserver
   ```

6. Open `http://127.0.0.1:8000/` in your browser.

If the question bank has not been populated, check the project's seed command:

```bash
uv run python manage.py seed_question_bank
```

## Development Status

The Django foundation, question bank, question selection logic, evaluation engine, and assessment components are present in the codebase. Their end-to-end behavior still requires systematic testing.

Voice interaction, speech processing, and holographic avatar integration must be verified separately before being described as completed.

## Notes

* The evaluation engine currently uses rule-based scoring; its results should not be treated as a validated measure of real-world interview ability.
* Local database files, environment variables, and secrets should not be committed to version control.
* This project is under active development.
