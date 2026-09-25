# ClassTrack — Class Attendance Management System

> Simple • Fast • Reliable Class Attendance

## Live Demo

[Open ClassTrack](https://classtrack-v661.onrender.com)

## Overview

ClassTrack is a secure, responsive web application for managing classroom attendance. Authorized users can manage the nominal roll, mark daily attendance, view date-wise records, search students, and generate copy-ready attendance reports.

## Features

- Secure single-passcode authentication
- Excel (`.xlsx`) nominal roll import
- Student management and search
- Exact preservation of nominal roll order
- Daily attendance management
- Present/Absent status tracking
- Date-wise attendance records
- Attendance statistics and percentage
- Search by roll number or student name
- Copy-ready full attendance report
- Copy-ready absentees-only report
- Light/Dark theme
- Responsive design
- PostgreSQL production database with SQLite local fallback
- Environment-variable-based configuration

## Technology Stack

**Frontend:** HTML5, CSS3, JavaScript  
**Backend:** Python, Flask, Gunicorn  
**Database:** PostgreSQL with Neon for production, SQLite for local development  
**Data Processing:** Pandas, OpenPyXL  
**Deployment:** Render, Neon PostgreSQL, Docker support  
**Development:** VS Code, Git, GitHub

## Project Structure

```text
ClassTrack/
├── app.py
├── requirements.txt
├── database/
│   ├── __init__.py
│   └── db.py
├── static/
│   ├── css/style.css
│   └── js/script.js
└── templates/
    ├── base.html
    ├── login.html
    ├── dashboard.html
    ├── attendance.html
    ├── records.html
    └── students.html
```

Private configuration, databases, uploaded files, and virtual environments are excluded from the repository.

## System Architecture

```text
User
  ↓
Render Flask Web Service
  ↓
ClassTrack Backend
  ↓
Neon PostgreSQL
  ↓
Students + Attendance Records
```

SQLite is used as the local development fallback when `DATABASE_URL` is not configured.

## Application Pages

- **Dashboard:** View today’s attendance summary and recent attendance dates.
- **Attendance:** Mark and edit today’s attendance using the active nominal roll.
- **Records:** View date-wise attendance, search records, and copy attendance reports.
- **Students:** Import, view, and search the official nominal roll.

## Security

- Single-passcode authentication
- Secrets loaded through environment variables
- `.env` excluded from Git
- Database credentials are not stored in source code
- Protected pages and APIs require authentication

## Deployment

- GitHub repository used as the source
- Flask application deployed on Render
- Neon PostgreSQL used for persistent production data
- Gunicorn used as the production WSGI server

## Author

**Jashwanth Reddy**  
B.Tech — Electronics and Communication Engineering
