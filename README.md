# EV Charging Station Reservation Management System

A Flask web application for browsing EV charging stations, booking time slots, reviewing reservations, and managing stations and payments through an administrator area. The app uses MySQL for persistence and server-rendered Jinja templates for its UI.

> **Development/demo project:** review the security notes before using this application with real customer data or real payments.

## Features

- User registration and login.
- Dashboard with station and charging-slot counts.
- Station browsing, slot availability, and time-based reservations.
- Reservation list, cancellation, and a payment confirmation flow.
- Role-protected admin dashboard for users, stations, slots, reservations, payments, and reports.
- Shared responsive CSS and a reusable navigation partial.

Payment processing is currently simulated: the application records a fixed **250.00** payment as `SUCCESS` when a payment method is selected. No payment provider or card processor is integrated.

## Technology

- Python 3.10 or newer
- Flask 3.x
- MySQL Server
- `mysql-connector-python`
- HTML, CSS, Jinja

## Project layout

```text
.
├── app.py
├── config.py
├── requirements.txt
├── database/
│   └── migrations/
│       └── 001_add_user_role.sql
├── templates/
│   ├── _navbar.html
│   ├── login.html
│   ├── register.html
│   ├── dashboard.html
│   ├── stations.html
│   ├── reservation.html
│   ├── my_reservations.html
│   ├── payment.html
│   ├── payment_success.html
│   ├── admin.html
│   ├── admin_users.html
│   ├── admin_add_user.html
│   ├── admin_edit_user.html
│   ├── admin_stations.html
│   ├── admin_add_station.html
│   ├── admin_edit_station.html
│   ├── admin_slots.html
│   ├── admin_add_slot.html
│   ├── admin_edit_slot.html
│   ├── admin_reservations.html
│   ├── admin_payments.html
│   └── admin_reports.html
└── static/
    └── style.css
```

## Database prerequisites

The repository does **not** include an initial database schema or seed data. Before starting the app, create `ev_charging_db` and install a schema containing the tables and columns used by the application:

- `users` — `user_id`, `name`, `email`, `phone`, `password`, and (after migration) `role`
- `vehicles` — `vehicle_id`, `user_id`, `vehicle_number`, `vehicle_model`, `battery_capacity`
- `charging_stations` — `station_id`, `station_name`, `location`, `contact_number`
- `charging_slots` — `slot_id`, `station_id`, `slot_number`, `charger_type`, `status`
- `reservations` — `reservation_id`, `user_id`, `vehicle_id`, `slot_id`, `reservation_date`, `start_time`, `end_time`, `status`
- `payments` — `payment_id`, `reservation_id`, `amount`, `payment_mode`, `payment_status`, `payment_date`

The `role` migration assumes the other database tables already exist. Apply it once after creating the base schema. By default, it promotes `arun@gmail.com`; change that email in the migration if a different account should be the administrator:

```powershell
& 'C:\Program Files\MySQL\MySQL Server 8.4\bin\mysql.exe' -u root -p ev_charging_db
```

At the MySQL prompt, run the statements from `database\migrations\001_add_user_role.sql`. The migration adds `role VARCHAR(20) NOT NULL DEFAULT 'USER'` and promotes the configured account to `ADMIN`. Existing users remain regular users unless explicitly promoted. Do not rerun the `ALTER TABLE` after the column has been added.

## Setup on Windows

Open PowerShell in the project directory.

### 1. Create and activate a virtual environment

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, either adjust the execution policy according to your organization's guidance or invoke the environment's executables directly (for example, `.\.venv\Scripts\python.exe`).

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 3. Configure credentials for this PowerShell session

Enter the database password without placing it in shell history. Provide a unique Flask session secret; the command below generates one using the Windows cryptographic random-number generator:

```powershell
$secure = Read-Host "MySQL password" -AsSecureString
$env:MYSQL_PASSWORD = (New-Object System.Net.NetworkCredential("", $secure)).Password
Remove-Variable secure

$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
$env:FLASK_SECRET_KEY = [Convert]::ToBase64String($bytes)
$rng.Dispose()
```

Optional connection settings default to `127.0.0.1`, MySQL user `root`, and database `ev_charging_db`. Override them if needed:

```powershell
$env:MYSQL_HOST = "127.0.0.1"
$env:MYSQL_USER = "root"
$env:MYSQL_DATABASE = "ev_charging_db"
```

These values are session-only. Set them again in a new PowerShell window, or use a properly secured secrets manager for persistent/deployed environments. Never commit database passwords or Flask secrets.

### 4. Start Flask

```powershell
python app.py
```

Open <http://127.0.0.1:5000/>. The home page redirects to login. The app currently starts with Flask debug mode enabled; use a production WSGI server and disable debug mode before exposing it beyond local development.

## Main routes

| Route | Purpose | Access |
|---|---|---|
| `/register`, `/login`, `/logout` | Account registration and session management | Public / signed-in |
| `/dashboard` | User dashboard | Signed-in |
| `/stations` | Browse stations | Signed-in |
| `/station/<station_id>` | View a station's charging slots | Signed-in |
| `/reserve/<slot_id>` | Reserve a slot | Signed-in |
| `/my-reservations` | View personal reservations | Signed-in |
| `/payment/<reservation_id>` | Demo payment form | Reservation owner |
| `/payment-success/<reservation_id>` | Verify and display successful demo payment | Reservation owner |
| `/cancel/<reservation_id>` | Cancel a personal reservation | Reservation owner |
| `/admin` | Admin dashboard | `ADMIN` role |
| `/admin/users`, `/admin/users/add`, `/admin/users/edit/<user_id>`, `/admin/users/delete/<user_id>` | User management | `ADMIN` role |
| `/admin/stations` and `/admin/stations/...` | Station management | `ADMIN` role |
| `/admin/slots` and `/admin/slots/...` | Charging-slot management | `ADMIN` role |
| `/admin/reservations` and `/admin/reservations/cancel/<reservation_id>` | Reservation management | `ADMIN` role |
| `/admin/payments` | Payment overview | `ADMIN` role |
| `/admin/reports` | Station reservation and daily revenue reports | `ADMIN` role |

## Testing and troubleshooting

There is no automated test suite included yet. For a quick syntax check:

```powershell
python -m py_compile app.py config.py
```

Common setup errors:

- **`Access denied for user`** — verify `MYSQL_USER`, `MYSQL_PASSWORD`, and `MYSQL_HOST`.
- **`Unknown column 'role'`** — apply `database\migrations\001_add_user_role.sql` to the same database configured for the app.
- **`Unknown database` / missing table** — create the database and install the base schema; this repository currently includes only the role migration.
- **`Set MYSQL_PASSWORD...` or `Set FLASK_SECRET_KEY...`** — configure the required environment variable in the same PowerShell session that starts Flask.

## Security and production readiness

This application is intended for development/demo use and needs security work before production:

- Registration and login currently store and compare passwords directly; use a password-hashing scheme such as Werkzeug's password utilities before handling real accounts.
- The payment route marks a database record successful without contacting a payment gateway. Do not treat it as real payment processing.
- Configure a strong, private `FLASK_SECRET_KEY`, disable Flask debug mode, and use HTTPS in any shared environment.
- Review authorization, CSRF protection, validation, error handling, and database constraints before deployment.
