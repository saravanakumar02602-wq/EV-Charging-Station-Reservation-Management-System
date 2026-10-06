import os

from flask import Flask, render_template, request, redirect, session
import mysql.connector
from config import DB_CONFIG
app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise RuntimeError("Set FLASK_SECRET_KEY in the environment before starting the app.")


# ==========================================================
# DATABASE CONNECTION
# ==========================================================

def get_db_connection():
    return mysql.connector.connect(**DB_CONFIG)


@app.before_request
def require_admin_role():
    if request.path == "/admin" or request.path.startswith("/admin/"):
        if "user_id" not in session or session.get("role") != "ADMIN":
            return redirect("/login")


# ==========================================================
# HOME
# ==========================================================

@app.route("/")
def home():
    return redirect("/login")


# ==========================================================
# REGISTER
# ==========================================================

@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        password = request.form["password"]

        db = get_db_connection()
        cursor = db.cursor()

        try:

            query = """
                INSERT INTO users
                (name, email, phone, password)
                VALUES (%s, %s, %s, %s)
            """

            cursor.execute(
                query,
                (name, email, phone, password)
            )

            db.commit()

        except mysql.connector.Error:

            db.rollback()

            cursor.close()
            db.close()

            return render_template(
                "register.html",
                error="Email already exists or registration failed."
            )

        cursor.close()
        db.close()

        return redirect("/login")

    return render_template("register.html")


# ==========================================================
# LOGIN
# ==========================================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form["email"]
        password = request.form["password"]

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)

        query = """
            SELECT user_id, name, email, role
            FROM users
            WHERE email = %s
            AND password = %s
        """

        cursor.execute(query, (email, password))

        user = cursor.fetchone()

        cursor.close()
        db.close()

        if user:

            session["user_id"] = user["user_id"]
            session["user_name"] = user["name"]
            session["user_email"] = user["email"]
            session["role"] = user["role"]

            return redirect("/dashboard")

        return render_template(
            "login.html",
            error="Invalid email or password."
        )

    return render_template("login.html")


# ==========================================================
# DASHBOARD
# ==========================================================

@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Total stations
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM charging_stations
    """)

    total_stations = cursor.fetchone()["total"]

    # Total charging slots
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM charging_slots
    """)

    total_slots = cursor.fetchone()["total"]

    # Available charging slots
    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM charging_slots
        WHERE status = 'AVAILABLE'
    """)

    available_slots = cursor.fetchone()["total"]

    cursor.close()
    db.close()

    return render_template(
        "dashboard.html",
        name=session["user_name"],
        total_stations=total_stations,
        total_slots=total_slots,
        available_slots=available_slots
    )


@app.route("/stations")
def stations():
    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("""
        SELECT station_id, station_name, location, contact_number
        FROM charging_stations
        ORDER BY station_id
    """)
    stations = cursor.fetchall()
    cursor.close()
    db.close()

    return render_template("stations.html", stations=stations)


# ==========================================================
# STATION SLOTS
# ==========================================================

@app.route("/station/<int:station_id>")
def station_slots(station_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Get station information
    cursor.execute("""
        SELECT *
        FROM charging_stations
        WHERE station_id = %s
    """, (station_id,))

    station = cursor.fetchone()

    # If station does not exist
    if station is None:

        cursor.close()
        db.close()

        return "Charging station not found", 404

    # Get charging slots
    cursor.execute("""
        SELECT *
        FROM charging_slots
        WHERE station_id = %s
        ORDER BY slot_id
    """, (station_id,))

    slots = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "stations.html",
        station=station,
        slots=slots
    )


# ==========================================================
# RESERVATION
# ==========================================================

@app.route("/reserve/<int:slot_id>", methods=["GET", "POST"])
def reserve(slot_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    # Get slot and station information
    cursor.execute("""
        SELECT
            csl.slot_id,
            csl.slot_number,
            csl.charger_type,
            csl.status,
            cs.station_id,
            cs.station_name,
            cs.location
        FROM charging_slots csl
        JOIN charging_stations cs
            ON csl.station_id = cs.station_id
        WHERE csl.slot_id = %s
    """, (slot_id,))

    slot = cursor.fetchone()

    if slot is None:
        cursor.close()
        db.close()
        return "Charging slot not found", 404

    # Get vehicles belonging to logged-in user
    cursor.execute("""
        SELECT
            vehicle_id,
            vehicle_number,
            vehicle_model,
            battery_capacity
        FROM vehicles
        WHERE user_id = %s
        ORDER BY vehicle_id
    """, (session["user_id"],))

    vehicles = cursor.fetchall()

    # ======================================================
    # SUBMIT RESERVATION
    # ======================================================

    if request.method == "POST":

        vehicle_id = request.form["vehicle_id"]
        reservation_date = request.form["reservation_date"]
        start_time = request.form["start_time"]
        end_time = request.form["end_time"]

        # Check time
        if start_time >= end_time:

            cursor.close()
            db.close()

            return render_template(
                "reservation.html",
                slot=slot,
                vehicles=vehicles,
                error="End time must be later than start time."
            )

        try:

            # Start transaction
            db.start_transaction()

            # Lock the selected slot
            cursor.execute("""
                SELECT slot_id
                FROM charging_slots
                WHERE slot_id = %s
                FOR UPDATE
            """, (slot_id,))

            cursor.fetchone()

            # Check for overlapping reservation
            cursor.execute("""
                SELECT reservation_id
                FROM reservations
                WHERE slot_id = %s
                  AND reservation_date = %s
                  AND start_time < %s
                  AND end_time > %s
                  AND status = 'CONFIRMED'
            """, (
                slot_id,
                reservation_date,
                end_time,
                start_time
            ))

            existing = cursor.fetchone()

            if existing:

                db.rollback()

                cursor.close()
                db.close()

                return render_template(
                    "reservation.html",
                    slot=slot,
                    vehicles=vehicles,
                    error="This charging slot is already reserved for the selected time."
                )

            # Insert reservation
            cursor.execute("""
                INSERT INTO reservations
                (
                    user_id,
                    vehicle_id,
                    slot_id,
                    reservation_date,
                    start_time,
                    end_time,
                    status
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    'CONFIRMED'
                )
            """, (
                session["user_id"],
                vehicle_id,
                slot_id,
                reservation_date,
                start_time,
                end_time
            ))

            db.commit()

            cursor.close()
            db.close()

            return redirect("/my-reservations")

        except mysql.connector.Error as e:

            db.rollback()

            cursor.close()
            db.close()

            return render_template(
                "reservation.html",
                slot=slot,
                vehicles=vehicles,
                error=f"Reservation failed: {e}"
            )

    cursor.close()
    db.close()

    return render_template(
        "reservation.html",
        slot=slot,
        vehicles=vehicles
    )

# ==========================================================
# MY RESERVATIONS
# ==========================================================

@app.route("/my-reservations")
def my_reservations():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            r.reservation_id,
            r.reservation_date,
            r.start_time,
            r.end_time,
            r.status,

            v.vehicle_number,
            v.vehicle_model,

            csl.slot_number,
            csl.charger_type,

            cs.station_name,
            cs.location

        FROM reservations r

        JOIN vehicles v
            ON r.vehicle_id = v.vehicle_id

        JOIN charging_slots csl
            ON r.slot_id = csl.slot_id

        JOIN charging_stations cs
            ON csl.station_id = cs.station_id

        WHERE r.user_id = %s

        ORDER BY
            r.reservation_date DESC,
            r.start_time DESC
    """, (session["user_id"],))

    reservations = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "my_reservations.html",
        name=session["user_name"],
        reservations=reservations
    )

# ==========================================================
# PAYMENT
# ==========================================================

@app.route("/payment/<int:reservation_id>", methods=["GET", "POST"])
def payment(reservation_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            r.reservation_id,
            r.reservation_date,
            r.start_time,
            r.end_time,
            r.status,

            v.vehicle_number,

            csl.slot_number,

            cs.station_name,
            cs.location

        FROM reservations r

        JOIN vehicles v
            ON r.vehicle_id = v.vehicle_id

        JOIN charging_slots csl
            ON r.slot_id = csl.slot_id

        JOIN charging_stations cs
            ON csl.station_id = cs.station_id

        WHERE r.reservation_id = %s
        AND r.user_id = %s
    """, (
        reservation_id,
        session["user_id"]
    ))

    reservation = cursor.fetchone()

    if reservation is None:

        cursor.close()
        db.close()

        return "Reservation not found", 404

    # Example charging amount
    amount = 250.00

    if request.method == "POST":

        payment_mode = request.form["payment_mode"]

        try:

            db.start_transaction()

            cursor.execute("""
                INSERT INTO payments
                (
                    reservation_id,
                    amount,
                    payment_mode,
                    payment_status
                )
                VALUES
                (
                    %s,
                    %s,
                    %s,
                    'SUCCESS'
                )
            """, (
                reservation_id,
                amount,
                payment_mode
            ))

            db.commit()

            cursor.close()
            db.close()

            return redirect(
                f"/payment-success/{reservation_id}"
            )

        except mysql.connector.Error as e:

            db.rollback()

            cursor.close()
            db.close()

            return f"Payment failed: {e}"

    cursor.close()
    db.close()

    return render_template(
        "payment.html",
        reservation=reservation,
        amount=amount
    )

# ==========================================================
# CANCEL RESERVATION
# ==========================================================

@app.route("/cancel/<int:reservation_id>")
def cancel_reservation(reservation_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        db.start_transaction()

        # Find the reservation belonging to the logged-in user
        cursor.execute("""
            SELECT
                reservation_id,
                slot_id,
                status
            FROM reservations
            WHERE reservation_id = %s
            AND user_id = %s
            FOR UPDATE
        """, (
            reservation_id,
            session["user_id"]
        ))

        reservation = cursor.fetchone()

        if reservation is None:

            db.rollback()
            cursor.close()
            db.close()

            return "Reservation not found", 404

        # Check current status
        if reservation["status"] == "CANCELLED":

            db.rollback()
            cursor.close()
            db.close()

            return redirect("/my-reservations")

        # Cancel reservation
        cursor.execute("""
            UPDATE reservations
            SET status = 'CANCELLED'
            WHERE reservation_id = %s
        """, (reservation_id,))

        # Make slot available again
        cursor.execute("""
            UPDATE charging_slots
            SET status = 'AVAILABLE'
            WHERE slot_id = %s
        """, (reservation["slot_id"],))

        db.commit()

        cursor.close()
        db.close()

        return redirect("/my-reservations")

    except mysql.connector.Error as e:

        db.rollback()

        cursor.close()
        db.close()

        return f"Cancellation failed: {e}", 500

@app.route("/admin")
def admin_dashboard():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("SELECT COUNT(*) AS total FROM users")
    total_users = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM vehicles")
    total_vehicles = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM charging_stations")
    total_stations = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM charging_slots")
    total_slots = cursor.fetchone()["total"]

    cursor.execute("SELECT COUNT(*) AS total FROM reservations")
    total_reservations = cursor.fetchone()["total"]

    cursor.execute("""
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM payments
        WHERE payment_status = 'SUCCESS'
    """)
    total_revenue = cursor.fetchone()["total"]

    cursor.close()
    db.close()

    return render_template(
        "admin.html",
        total_users=total_users,
        total_vehicles=total_vehicles,
        total_stations=total_stations,
        total_slots=total_slots,
        total_reservations=total_reservations,
        total_revenue=total_revenue
    )

# ==========================================================
# PAYMENT SUCCESS
# ==========================================================

@app.route("/payment-success/<int:reservation_id>")
def payment_success(reservation_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor()

    cursor.execute("""
        SELECT 1
        FROM payments p
        JOIN reservations r
            ON p.reservation_id = r.reservation_id
        WHERE p.reservation_id = %s
        AND r.user_id = %s
        AND p.payment_status = 'SUCCESS'
        LIMIT 1
    """, (
        reservation_id,
        session["user_id"]
    ))

    payment_record = cursor.fetchone()

    cursor.close()
    db.close()

    if payment_record is None:
        return "Successful payment not found for this reservation", 404

    return render_template(
        "payment_success.html",
        reservation_id=reservation_id
    )

# ==========================================================
# ADMIN - USERS
# ==========================================================

@app.route("/admin/users")
def admin_users():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT user_id, name, email, phone
        FROM users
        ORDER BY user_id
    """)

    users = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "admin_users.html",
        users=users
    )


# ==========================================================
# ADD USER
# ==========================================================

@app.route("/admin/users/add", methods=["GET", "POST"])
def admin_add_user():

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        password = request.form["password"]

        db = get_db_connection()
        cursor = db.cursor()

        try:

            cursor.execute("""
                INSERT INTO users
                (name, email, phone, password)
                VALUES (%s, %s, %s, %s)
            """, (
                name,
                email,
                phone,
                password
            ))

            db.commit()

        except mysql.connector.Error as e:

            db.rollback()
            cursor.close()
            db.close()

            return f"Error: {e}", 500

        cursor.close()
        db.close()

        return redirect("/admin/users")

    return render_template("admin_add_user.html")


# ==========================================================
# EDIT USER
# ==========================================================

@app.route("/admin/users/edit/<int:user_id>", methods=["GET", "POST"])
def admin_edit_user(user_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]

        cursor.execute("""
            UPDATE users
            SET name = %s,
                email = %s,
                phone = %s
            WHERE user_id = %s
        """, (
            name,
            email,
            phone,
            user_id
        ))

        db.commit()

        cursor.close()
        db.close()

        return redirect("/admin/users")

    cursor.execute("""
        SELECT user_id, name, email, phone
        FROM users
        WHERE user_id = %s
    """, (user_id,))

    user = cursor.fetchone()

    cursor.close()
    db.close()

    if user is None:
        return "User not found", 404

    return render_template(
        "admin_edit_user.html",
        user=user
    )


# ==========================================================
# DELETE USER
# ==========================================================

@app.route("/admin/users/delete/<int:user_id>")
def admin_delete_user(user_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor()

    try:

        cursor.execute("""
            DELETE FROM users
            WHERE user_id = %s
        """, (user_id,))

        db.commit()

    except mysql.connector.Error as e:

        db.rollback()
        cursor.close()
        db.close()

        return f"Cannot delete user: {e}", 500

    cursor.close()
    db.close()

    return redirect("/admin/users")

# ==========================================================
# ADMIN - MANAGE CHARGING STATIONS
# ==========================================================

@app.route("/admin/stations")
def admin_stations():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            station_id,
            station_name,
            location,
            contact_number
        FROM charging_stations
        ORDER BY station_id
    """)

    stations = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "admin_stations.html",
        stations=stations
    )


# ==========================================================
# ADD STATION
# ==========================================================

@app.route("/admin/stations/add", methods=["GET", "POST"])
def admin_add_station():

    if "user_id" not in session:
        return redirect("/login")

    if request.method == "POST":

        station_name = request.form["station_name"]
        location = request.form["location"]
        contact_number = request.form["contact_number"]

        db = get_db_connection()
        cursor = db.cursor()

        try:

            cursor.execute("""
                INSERT INTO charging_stations
                (station_name, location, contact_number)
                VALUES (%s, %s, %s)
            """, (
                station_name,
                location,
                contact_number
            ))

            db.commit()

        except mysql.connector.Error as e:

            db.rollback()
            cursor.close()
            db.close()

            return f"Error adding station: {e}", 500

        cursor.close()
        db.close()

        return redirect("/admin/stations")

    return render_template("admin_add_station.html")


# ==========================================================
# EDIT STATION
# ==========================================================

@app.route(
    "/admin/stations/edit/<int:station_id>",
    methods=["GET", "POST"]
)
def admin_edit_station(station_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":

        station_name = request.form["station_name"]
        location = request.form["location"]
        contact_number = request.form["contact_number"]

        cursor.execute("""
            UPDATE charging_stations
            SET
                station_name = %s,
                location = %s,
                contact_number = %s
            WHERE station_id = %s
        """, (
            station_name,
            location,
            contact_number,
            station_id
        ))

        db.commit()

        cursor.close()
        db.close()

        return redirect("/admin/stations")

    cursor.execute("""
        SELECT
            station_id,
            station_name,
            location,
            contact_number
        FROM charging_stations
        WHERE station_id = %s
    """, (station_id,))

    station = cursor.fetchone()

    cursor.close()
    db.close()

    if station is None:
        return "Station not found", 404

    return render_template(
        "admin_edit_station.html",
        station=station
    )


# ==========================================================
# DELETE STATION
# ==========================================================

@app.route("/admin/stations/delete/<int:station_id>")
def admin_delete_station(station_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor()

    try:

        cursor.execute("""
            DELETE FROM charging_stations
            WHERE station_id = %s
        """, (station_id,))

        db.commit()

    except mysql.connector.Error as e:

        db.rollback()
        cursor.close()
        db.close()

        return (
            "Cannot delete station. "
            "It may contain charging slots or reservations.<br><br>"
            f"Database Error: {e}"
        ), 500

    cursor.close()
    db.close()

    return redirect("/admin/stations")

# ==========================================================
# ADMIN - MANAGE CHARGING SLOTS
# ==========================================================

@app.route("/admin/slots")
def admin_slots():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            csl.slot_id,
            csl.station_id,
            csl.slot_number,
            csl.charger_type,
            csl.status,
            cs.station_name,
            cs.location
        FROM charging_slots csl
        JOIN charging_stations cs
            ON csl.station_id = cs.station_id
        ORDER BY csl.slot_id
    """)

    slots = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "admin_slots.html",
        slots=slots
    )


# ==========================================================
# ADD CHARGING SLOT
# ==========================================================

@app.route("/admin/slots/add", methods=["GET", "POST"])
def admin_add_slot():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":

        station_id = request.form["station_id"]
        slot_number = request.form["slot_number"]
        charger_type = request.form["charger_type"]
        status = request.form["status"]

        try:

            cursor.execute("""
                INSERT INTO charging_slots
                (
                    station_id,
                    slot_number,
                    charger_type,
                    status
                )
                VALUES (%s, %s, %s, %s)
            """, (
                station_id,
                slot_number,
                charger_type,
                status
            ))

            db.commit()

        except mysql.connector.Error as e:

            db.rollback()
            cursor.close()
            db.close()

            return f"Error adding slot: {e}", 500

        cursor.close()
        db.close()

        return redirect("/admin/slots")

    cursor.execute("""
        SELECT
            station_id,
            station_name,
            location
        FROM charging_stations
        ORDER BY station_name
    """)

    stations = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "admin_add_slot.html",
        stations=stations
    )


# ==========================================================
# EDIT CHARGING SLOT
# ==========================================================

@app.route(
    "/admin/slots/edit/<int:slot_id>",
    methods=["GET", "POST"]
)
def admin_edit_slot(slot_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    if request.method == "POST":

        station_id = request.form["station_id"]
        slot_number = request.form["slot_number"]
        charger_type = request.form["charger_type"]
        status = request.form["status"]

        try:

            cursor.execute("""
                UPDATE charging_slots
                SET
                    station_id = %s,
                    slot_number = %s,
                    charger_type = %s,
                    status = %s
                WHERE slot_id = %s
            """, (
                station_id,
                slot_number,
                charger_type,
                status,
                slot_id
            ))

            db.commit()

        except mysql.connector.Error as e:

            db.rollback()
            cursor.close()
            db.close()

            return f"Error updating slot: {e}", 500

        cursor.close()
        db.close()

        return redirect("/admin/slots")

    cursor.execute("""
        SELECT
            slot_id,
            station_id,
            slot_number,
            charger_type,
            status
        FROM charging_slots
        WHERE slot_id = %s
    """, (slot_id,))

    slot = cursor.fetchone()

    if slot is None:

        cursor.close()
        db.close()

        return "Charging slot not found", 404

    cursor.execute("""
        SELECT
            station_id,
            station_name,
            location
        FROM charging_stations
        ORDER BY station_name
    """)

    stations = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "admin_edit_slot.html",
        slot=slot,
        stations=stations
    )


# ==========================================================
# DELETE CHARGING SLOT
# ==========================================================

@app.route("/admin/slots/delete/<int:slot_id>")
def admin_delete_slot(slot_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor()

    try:

        cursor.execute("""
            DELETE FROM charging_slots
            WHERE slot_id = %s
        """, (slot_id,))

        db.commit()

    except mysql.connector.Error as e:

        db.rollback()

        cursor.close()
        db.close()

        return (
            "Cannot delete this slot because it may be "
            "used by an existing reservation.<br><br>"
            f"Database Error: {e}"
        ), 500

    cursor.close()
    db.close()

    return redirect("/admin/slots")

# ==========================================================
# ADMIN - MANAGE RESERVATIONS
# ==========================================================

@app.route("/admin/reservations")
def admin_reservations():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            r.reservation_id,

            u.name AS customer_name,

            v.vehicle_number,
            v.vehicle_model,

            cs.station_name,

            csl.slot_number,
            csl.charger_type,

            r.reservation_date,
            r.start_time,
            r.end_time,
            r.status

        FROM reservations r

        JOIN users u
            ON r.user_id = u.user_id

        JOIN vehicles v
            ON r.vehicle_id = v.vehicle_id

        JOIN charging_slots csl
            ON r.slot_id = csl.slot_id

        JOIN charging_stations cs
            ON csl.station_id = cs.station_id

        ORDER BY
            r.reservation_date DESC,
            r.start_time DESC
    """)

    reservations = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "admin_reservations.html",
        reservations=reservations
    )


# ==========================================================
# ADMIN - CANCEL RESERVATION
# ==========================================================

@app.route("/admin/reservations/cancel/<int:reservation_id>")
def admin_cancel_reservation(reservation_id):

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    try:

        db.start_transaction()

        # Lock reservation row
        cursor.execute("""
            SELECT
                reservation_id,
                slot_id,
                status
            FROM reservations
            WHERE reservation_id = %s
            FOR UPDATE
        """, (reservation_id,))

        reservation = cursor.fetchone()

        if reservation is None:

            db.rollback()

            cursor.close()
            db.close()

            return "Reservation not found", 404

        # Only confirmed reservations can be cancelled
        if reservation["status"] != "CONFIRMED":

            db.rollback()

            cursor.close()
            db.close()

            return redirect("/admin/reservations")

        # Cancel reservation
        cursor.execute("""
            UPDATE reservations
            SET status = 'CANCELLED'
            WHERE reservation_id = %s
        """, (reservation_id,))

        # Make slot available
        cursor.execute("""
            UPDATE charging_slots
            SET status = 'AVAILABLE'
            WHERE slot_id = %s
        """, (reservation["slot_id"],))

        db.commit()

    except mysql.connector.Error as e:

        db.rollback()

        cursor.close()
        db.close()

        return f"Cancellation failed: {e}", 500

    cursor.close()
    db.close()

    return redirect("/admin/reservations")

@app.route("/admin/payments")
def admin_payments():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            p.payment_id,
            p.reservation_id,
            u.name AS customer_name,
            cs.station_name,
            csl.slot_number,
            p.amount,
            p.payment_mode,
            p.payment_status,
            p.payment_date
        FROM payments p
        JOIN reservations r
            ON p.reservation_id = r.reservation_id
        JOIN users u
            ON r.user_id = u.user_id
        JOIN charging_slots csl
            ON r.slot_id = csl.slot_id
        JOIN charging_stations cs
            ON csl.station_id = cs.station_id
        ORDER BY p.payment_date DESC
    """)

    payments = cursor.fetchall()

    cursor.execute("""
        SELECT
            COUNT(payment_id) AS total_payments,
            COALESCE(SUM(amount),0) AS total_revenue,
            COALESCE(AVG(amount),0) AS average_payment,
            COALESCE(MAX(amount),0) AS highest_payment,
            COALESCE(MIN(amount),0) AS lowest_payment
        FROM payments
        WHERE payment_status = 'SUCCESS'
    """)

    summary = cursor.fetchone()

    cursor.close()
    db.close()

    return render_template(
        "admin_payments.html",
        payments=payments,
        summary=summary
    )

@app.route("/admin/reports")
def admin_reports():

    if "user_id" not in session:
        return redirect("/login")

    db = get_db_connection()
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT
            cs.station_name,
            COUNT(r.reservation_id) AS total_reservations
        FROM charging_stations cs
        LEFT JOIN charging_slots csl
            ON cs.station_id = csl.station_id
        LEFT JOIN reservations r
            ON csl.slot_id = r.slot_id
        GROUP BY cs.station_id, cs.station_name
        ORDER BY total_reservations DESC
    """)

    station_report = cursor.fetchall()

    cursor.execute("""
        SELECT
            DATE(payment_date) AS payment_day,
            COUNT(payment_id) AS payments,
            SUM(amount) AS revenue
        FROM payments
        WHERE payment_status = 'SUCCESS'
        GROUP BY DATE(payment_date)
        ORDER BY payment_day DESC
    """)

    revenue_report = cursor.fetchall()

    cursor.close()
    db.close()

    return render_template(
        "admin_reports.html",
        station_report=station_report,
        revenue_report=revenue_report
    )

# ==========================================================
# LOGOUT
# ==========================================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect("/login")


# ==========================================================
# RUN APPLICATION
# ==========================================================

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)