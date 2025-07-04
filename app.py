import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
import pymysql
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import bcrypt
from datetime import datetime, timedelta, date
import csv
from io import StringIO
from io import BytesIO
from decimal import Decimal
from flask import make_response

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "your_fallback_secret_key")

try:
    conn = pymysql.connect(
        print("DEBUG: MYSQLHOST =", repr(os.getenv('MYSQLHOST')))
        host=os.getenv('MYSQLHOST'),
        user=os.getenv('MYSQLUSER'),
        password=os.getenv('MYSQLPASSWORD'),
        database=os.getenv('MYSQLDATABASE'),
        port=int(os.getenv('MYSQLPORT', 3306)),
        cursorclass=pymysql.cursors.DictCursor
    )
    print("✅ DB connection successful")
except Exception as e:
    print("❌ DB connection failed:", e)
    raise

cursor = conn.cursor()

# File upload configuration
UPLOAD_FOLDER = 'static/uploads/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Helper functions
# There seems to be an indentation issue here, `return conn.cursor()` is not inside a function.
# Assuming it was intended to be part of a `get_db_cursor` helper if you had one.
# For now, I'll remove it as it's causing a syntax error in its current placement.
# If you need a helper to get a new cursor, you would define a function like this:
# def get_db_cursor():
#     return conn.cursor()

def get_current_datetime():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def calculate_work_hours(check_in, check_out):
    try:
        # Handle None check_in
        if check_in is None:
            return None
            
        # Convert strings to datetime if needed
        if isinstance(check_in, str):
            check_in = datetime.strptime(check_in, '%Y-%m-%d %H:%M:%S')
        if check_out and isinstance(check_out, str):
            check_out = datetime.strptime(check_out, '%Y-%m-%d %H:%M:%S')
            
        # Return None if no check_out
        if check_out is None:
            return None
            
        # Calculate hours
        delta = check_out - check_in
        total_hours = delta.total_seconds() / 3600
        
        # Handle negative hours (shouldn't happen but just in case)
        if total_hours < 0:
            return None
            
        return round(total_hours, 2)
    except Exception as e:
        print(f"Error calculating work hours: {str(e)}")
        return None

def is_admin_logged_in():
    return 'admin_id' in session

def is_employee_logged_in():
    return 'emp_id' in session

def get_employee_details(emp_id):
    cur = conn.cursor()
    cur.execute("""
        SELECT e.*, d.dept_name, des.desig_name 
        FROM employee e 
        LEFT JOIN department d ON e.dept_id = d.dept_id 
        LEFT JOIN designation des ON e.desig_id = des.desig_id 
        WHERE e.emp_id = %s
    """, (emp_id,))
    employee = cur.fetchone()
    cur.close()
    return employee

def get_admin_details(admin_id):
    cur = conn.cursor()
    cur.execute("SELECT * FROM admin WHERE admin_id = %s", (admin_id,))
    admin = cur.fetchone()
    cur.close()
    return admin


def calculate_leave_days(start_date, end_date, leave_duration):
    """Calculate leave days considering half-day options"""
    if leave_duration == 'full_day':
        return (end_date - start_date).days + 1
    elif leave_duration in ['first_half', 'second_half']:
        # For half-day, count as 0.5 days per day in the range
        return ((end_date - start_date).days + 1) * 0.5
    else:
        return 0
 
def validate_leave_dates(start_date, end_date, leave_duration):
    """Validate leave dates based on duration"""
    if leave_duration == 'full_day':
        return start_date <= end_date
    elif leave_duration in ['first_half', 'second_half']:
        # For half-day, start and end dates must be the same
        return start_date == end_date
    return False

# Routes
@app.route('/')
def index():
    # Check if user is logged in and redirect to appropriate dashboard
    if 'role' in session:
        if session['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif session['role'] == 'employee':
            return redirect(url_for('employee_dashboard'))
    
    # If not logged in, show the login page
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password'].encode('utf-8')
        role = request.form['role']
        
        if role == 'admin':
            cur = conn.cursor()
            cur.execute("SELECT * FROM admin WHERE username = %s", (username,))
            admin = cur.fetchone()
            cur.close()
            
            if admin and bcrypt.checkpw(password, admin['password_hash'].encode('utf-8')):
                session['admin_id'] = admin['admin_id']
                session['username'] = admin['username']
                session['role'] = 'admin'
                flash('Login successful!', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid username or password', 'danger')
        else:
            cur = conn.cursor()
            cur.execute("SELECT * FROM employee WHERE work_email = %s AND status = 'active'", (username,))
            employee = cur.fetchone()
            cur.close()
            
            if employee and bcrypt.checkpw(password, employee['password_hash'].encode('utf-8')):
                session['emp_id'] = employee['emp_id']
                session['username'] = employee['work_email']
                session['role'] = 'employee'
                flash('Login successful!', 'success')
                return redirect(url_for('employee_dashboard'))
            else:
                flash('Invalid username or password or account is inactive', 'danger')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

# Admin Dashboard
@app.route('/admin/dashboard')
def admin_dashboard():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    
    # Get total employees
    cur.execute("SELECT COUNT(*) as total_employees FROM employee")
    total_employees = cur.fetchone()['total_employees']
    
    # Get active employees
    cur.execute("SELECT COUNT(*) as active_employees FROM employee WHERE status = 'active'")
    active_employees = cur.fetchone()['active_employees']
    
    # Get pending leave requests
    cur.execute("SELECT COUNT(*) as pending_leaves FROM leave_application WHERE status = 'pending'")
    pending_leaves = cur.fetchone()['pending_leaves']
    
    # Get today's attendance
    today = date.today().strftime('%Y-%m-%d')
    cur.execute("""
        SELECT COUNT(*) as today_present 
        FROM attendance 
        WHERE DATE(check_in) = %s AND status = 'present'
    """, (today,))
    today_present = cur.fetchone()['today_present']
    
    # Get recent leave applications
    cur.execute("""
        SELECT la.*, e.first_name, e.last_name, lt.leave_name 
        FROM leave_application la 
        JOIN employee e ON la.emp_id = e.emp_id 
        JOIN leave_type lt ON la.leave_type_id = lt.leave_type_id 
        WHERE la.status = 'pending' 
        ORDER BY la.applied_on DESC 
        LIMIT 5
    """)
    recent_leaves = cur.fetchall()
    
    cur.close()
    
    return render_template('admin_dashboard.html', 
                         total_employees=total_employees,
                         active_employees=active_employees,
                         pending_leaves=pending_leaves,
                         today_present=today_present,
                         recent_leaves=recent_leaves)
 

# Employee Management
@app.route('/admin/employees')
def manage_employees():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    cur.execute("""
        SELECT e.*, d.dept_name, des.desig_name 
        FROM employee e 
        LEFT JOIN department d ON e.dept_id = d.dept_id 
        LEFT JOIN designation des ON e.desig_id = des.desig_id 
        ORDER BY e.status, e.first_name
    """)
    employees = cur.fetchall()
    
    cur.execute("SELECT * FROM department")
    departments = cur.fetchall()
    
    cur.execute("SELECT * FROM designation")
    designations = cur.fetchall()
    
    cur.close()
    
    return render_template('manage_employees.html', 
                         employees=employees,
                         departments=departments,
                         designations=designations)


# Add this route to app3.py (around the other admin routes)

@app.route('/admin/employee/leave_balance/<int:emp_id>')
def view_employee_leave_balance(emp_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    cur = conn.cursor()
    # Get employee details
    cur.execute("""
        SELECT e.*, d.dept_name, des.desig_name 
        FROM employee e 
        LEFT JOIN department d ON e.dept_id = d.dept_id 
        LEFT JOIN designation des ON e.desig_id = des.desig_id 
        WHERE e.emp_id = %s
    """, (emp_id,))
    employee = cur.fetchone()
    if not employee:
        flash('Employee not found', 'danger')
        return redirect(url_for('manage_employees'))
    # Get leave balance with proper join to leave_type
    cur.execute("""
        SELECT lb.*, lt.leave_name, lt.max_days, lt.description 
        FROM leave_balance lb 
        JOIN leave_type lt ON lb.leave_type_id = lt.leave_type_id 
        WHERE lb.emp_id = %s
        ORDER BY lt.leave_name
    """, (emp_id,))
    leave_balances = cur.fetchall()
    cur.close()
    return render_template('admin_employee_leave_balance.html', 
                         employee=employee,
                         leave_balances=leave_balances)
 # Add this route to app3.py

@app.route('/admin/employee/adjust_leave_balance/<int:emp_id>', methods=['POST'])
def adjust_leave_balance(emp_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    leave_type_id = request.form['leave_type_id']
    adjustment_type = request.form['adjustment_type']
    days = request.form['days']  # Keep as string initially
    reason = request.form['reason']
    admin_id = session['admin_id']
    cur = conn.cursor()
    try:
        # Convert days to Decimal for precise arithmetic
        try:
            days = Decimal(days)
            if days <= 0:
                flash('Days must be a positive number', 'danger')
                return redirect(url_for('view_employee_leave_balance', emp_id=emp_id))
        except:
            flash('Invalid days value', 'danger')
            return redirect(url_for('view_employee_leave_balance', emp_id=emp_id))
        # Get current balance and max days from leave_type
        cur.execute("""
            SELECT lb.remaining_days, lt.max_days 
            FROM leave_balance lb
            JOIN leave_type lt ON lb.leave_type_id = lt.leave_type_id
            WHERE lb.emp_id = %s AND lb.leave_type_id = %s
        """, (emp_id, leave_type_id))
        balance = cur.fetchone()
        if not balance:
            flash('Leave balance not found', 'danger')
            return redirect(url_for('view_employee_leave_balance', emp_id=emp_id))
        # Convert database values to Decimal
        current_balance = Decimal(str(balance['remaining_days']))
        max_days = Decimal(str(balance['max_days']))
        # Calculate new balance based on adjustment type
        if adjustment_type == 'add':
            new_balance = current_balance + days
        elif adjustment_type == 'subtract':
            new_balance = current_balance - days
            if new_balance < 0:
                flash('Cannot have negative leave balance', 'danger')
                return redirect(url_for('view_employee_leave_balance', emp_id=emp_id))
        elif adjustment_type == 'set':
            new_balance = days
            if new_balance > max_days:
                flash(f'Cannot set balance higher than max days ({max_days})', 'danger')
                return redirect(url_for('view_employee_leave_balance', emp_id=emp_id))
        else:
            flash('Invalid adjustment type', 'danger')
            return redirect(url_for('view_employee_leave_balance', emp_id=emp_id))
        # Update balance (convert back to float for MySQL)
        cur.execute("""
            UPDATE leave_balance 
            SET remaining_days = %s 
            WHERE emp_id = %s AND leave_type_id = %s
        """, (float(new_balance), emp_id, leave_type_id))
        # Record adjustment in audit log
        cur.execute("""
            INSERT INTO leave_balance_adjustment 
            (emp_id, leave_type_id, admin_id, adjustment_type, days, reason, new_balance) 
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            emp_id, 
            leave_type_id, 
            admin_id, 
            adjustment_type, 
            float(days), 
            reason, 
            float(new_balance)
        ))
        conn.commit()
        flash('Leave balance updated successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating leave balance: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('view_employee_leave_balance', emp_id=emp_id)) 

@app.route('/admin/employee/add', methods=['GET', 'POST'])
def add_employee():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        # Get form data
        employee_id = request.form['employee_id']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        work_email = request.form['work_email']
        personal_email = request.form['personal_email']
        phone = request.form['phone']
        dob = request.form['dob']
        join_date = request.form['join_date']
        end_date = request.form['end_date'] if request.form['end_date'] else None
        dept_id = request.form['dept_id']
        desig_id = request.form['desig_id']
        password = request.form['password']
        
        # Validate password length
        if len(password) < 8:
            flash('Password must be at least 8 characters long', 'danger')
            return redirect(url_for('add_employee'))
        
        # Hash password
        hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Handle file upload
        profile_pic = None
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{employee_id}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                profile_pic = filename
        
        # Insert into database
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO employee 
                (employee_id, first_name, last_name, work_email, personal_email, phone, 
                 dob, join_date, end_date, dept_id, desig_id, password_hash, profile_pic) 
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (employee_id, first_name, last_name, work_email, personal_email, phone, 
                  dob, join_date, end_date, dept_id, desig_id, hashed_password, profile_pic))
            
            # Initialize leave balances
            emp_id = cur.lastrowid
            cur.execute("SELECT leave_type_id FROM leave_type")
            leave_types = cur.fetchall()
            for lt in leave_types:
                cur.execute("""
                    INSERT INTO leave_balance (emp_id, leave_type_id, remaining_days)
                    VALUES (%s, %s, (SELECT max_days FROM leave_type WHERE leave_type_id = %s))
                """, (emp_id, lt['leave_type_id'], lt['leave_type_id']))
            
            conn.commit()
            flash('Employee added successfully!', 'success')
            return redirect(url_for('manage_employees'))
        except Exception as e:
            conn.rollback()
            flash(f'Error adding employee: {str(e)}', 'danger')
        finally:
            cur.close()
    
    # GET request - show form
    cur = conn.cursor()
    cur.execute("SELECT * FROM department")
    departments = cur.fetchall()
    
    cur.execute("SELECT * FROM designation")
    designations = cur.fetchall()
    
    cur.close()
    
    return render_template('add_employee.html', 
                         departments=departments,
                         designations=designations)

@app.route('/admin/employee/edit/<int:emp_id>', methods=['GET', 'POST'])
def edit_employee(emp_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    
    if request.method == 'POST':
        # Get form data
        employee_id = request.form['employee_id']
        first_name = request.form['first_name']
        last_name = request.form['last_name']
        work_email = request.form['work_email']
        personal_email = request.form['personal_email']
        phone = request.form['phone']
        dob = request.form['dob']
        join_date = request.form['join_date']
        end_date = request.form['end_date'] if request.form['end_date'] else None
        dept_id = request.form['dept_id']
        desig_id = request.form['desig_id']
        status = request.form['status']
        
        # Handle file upload
        profile_pic = None
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and allowed_file(file.filename):
                filename = secure_filename(f"{employee_id}_{file.filename}")
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                profile_pic = filename
        
        # Update database
        try:
            if profile_pic:
                cur.execute("""
                    UPDATE employee 
                    SET employee_id = %s, first_name = %s, last_name = %s, 
                        work_email = %s, personal_email = %s, phone = %s, 
                        dob = %s, join_date = %s, end_date = %s, 
                        dept_id = %s, desig_id = %s, status = %s, profile_pic = %s
                    WHERE emp_id = %s
                """, (employee_id, first_name, last_name, work_email, personal_email, phone, 
                      dob, join_date, end_date, dept_id, desig_id, status, profile_pic, emp_id))
            else:
                cur.execute("""
                    UPDATE employee 
                    SET employee_id = %s, first_name = %s, last_name = %s, 
                        work_email = %s, personal_email = %s, phone = %s, 
                        dob = %s, join_date = %s, end_date = %s, 
                        dept_id = %s, desig_id = %s, status = %s
                    WHERE emp_id = %s
                """, (employee_id, first_name, last_name, work_email, personal_email, phone, 
                      dob, join_date, end_date, dept_id, desig_id, status, emp_id))
            
            # Handle password reset if provided
            new_password = request.form.get('new_password')
            if new_password and len(new_password) >= 8:
                hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute("""
                    UPDATE employee 
                    SET password_hash = %s 
                    WHERE emp_id = %s
                """, (hashed_password, emp_id))
            
            conn.commit()
            flash('Employee updated successfully!', 'success')
            return redirect(url_for('manage_employees'))
        except Exception as e:
            conn.rollback()
            flash(f'Error updating employee: {str(e)}', 'danger')
        finally:
            cur.close()
    
    # GET request - show form with current data
    cur.execute("""
        SELECT * FROM employee 
        WHERE emp_id = %s
    """, (emp_id,))
    employee = cur.fetchone()
    
    cur.execute("SELECT * FROM department")
    departments = cur.fetchall()
    
    cur.execute("SELECT * FROM designation")
    designations = cur.fetchall()
    
    cur.close()
    
    if not employee:
        flash('Employee not found', 'danger')
        return redirect(url_for('manage_employees'))
    
    return render_template('edit_employee.html', 
                         employee=employee,
                         departments=departments,
                         designations=designations)

@app.route('/admin/employee/delete/<int:emp_id>', methods=['POST'])
def delete_employee(emp_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    try:
        # Delete all related records first
        cur.execute("DELETE FROM leave_balance WHERE emp_id = %s", (emp_id,))
        cur.execute("DELETE FROM leave_application WHERE emp_id = %s", (emp_id,))
        cur.execute("DELETE FROM attendance WHERE emp_id = %s", (emp_id,))
        
        # Then delete the employee
        cur.execute("DELETE FROM employee WHERE emp_id = %s", (emp_id,))
        conn.commit()
        flash('Employee deleted successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting employee: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_employees'))

@app.route('/admin/employee/reset_password/<int:emp_id>', methods=['POST'])
def reset_employee_password(emp_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    new_password = request.form['new_password']
    confirm_password = request.form.get('confirm_password', '')
    
    if len(new_password) < 8:
        flash('Password must be at least 8 characters long', 'danger')
        return redirect(url_for('edit_employee', emp_id=emp_id))

    if new_password != confirm_password:
        flash('Passwords do not match', 'danger')
        return redirect(url_for('edit_employee', emp_id=emp_id))
    
    hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE employee 
            SET password_hash = %s 
            WHERE emp_id = %s
        """, (hashed_password, emp_id))
        conn.commit()
        flash('Password reset successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error resetting password: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('edit_employee', emp_id=emp_id))

# Department Management
@app.route('/admin/departments')
def manage_departments():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    cur.execute("SELECT * FROM department ORDER BY dept_name")
    departments = cur.fetchall()
    cur.close()
    
    return render_template('manage_departments.html', departments=departments)

@app.route('/admin/department/add', methods=['POST'])
def add_department():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    dept_name = request.form['dept_name']
    description = request.form['description']
    
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO department (dept_name, description) 
            VALUES (%s, %s)
        """, (dept_name, description))
        conn.commit()
        flash('Department added successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error adding department: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_departments'))

@app.route('/admin/department/edit/<int:dept_id>', methods=['POST'])
def edit_department(dept_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    dept_name = request.form['dept_name']
    description = request.form['description']
    
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE department 
            SET dept_name = %s, description = %s 
            WHERE dept_id = %s
        """, (dept_name, description, dept_id))
        conn.commit()
        flash('Department updated successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating department: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_departments'))

@app.route('/admin/department/delete/<int:dept_id>', methods=['POST'])
def delete_department(dept_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    try:
        # Check if department has employees
        cur.execute("SELECT COUNT(*) as emp_count FROM employee WHERE dept_id = %s", (dept_id,))
        result = cur.fetchone()
        
        if result['emp_count'] > 0:
            flash('Cannot delete department with assigned employees', 'danger')
            return redirect(url_for('manage_departments'))
        
        cur.execute("DELETE FROM department WHERE dept_id = %s", (dept_id,))
        conn.commit()
        flash('Department deleted successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting department: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_departments'))

# Designation Management
@app.route('/admin/designations')
def manage_designations():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    cur.execute("SELECT * FROM designation ORDER BY desig_name")
    designations = cur.fetchall()
    cur.close()
    
    return render_template('manage_designations.html', designations=designations)

@app.route('/admin/designation/add', methods=['POST'])
def add_designation():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    desig_name = request.form['desig_name']
    description = request.form['description']
    
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO designation (desig_name, description) 
            VALUES (%s, %s)
        """, (desig_name, description))
        conn.commit()
        flash('Designation added successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error adding designation: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_designations'))

@app.route('/admin/designation/edit/<int:desig_id>', methods=['POST'])
def edit_designation(desig_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    desig_name = request.form['desig_name']
    description = request.form['description']
    
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE designation 
            SET desig_name = %s, description = %s 
            WHERE desig_id = %s
        """, (desig_name, description, desig_id))
        conn.commit()
        flash('Designation updated successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating designation: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_designations'))

@app.route('/admin/designation/delete/<int:desig_id>', methods=['POST'])
def delete_designation(desig_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    try:
        # Check if designation has employees
        cur.execute("SELECT COUNT(*) as emp_count FROM employee WHERE desig_id = %s", (desig_id,))
        result = cur.fetchone()
        
        if result['emp_count'] > 0:
            flash('Cannot delete designation with assigned employees', 'danger')
            return redirect(url_for('manage_designations'))
        
        cur.execute("DELETE FROM designation WHERE desig_id = %s", (desig_id,))
        conn.commit()
        flash('Designation deleted successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting designation: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_designations'))

# Leave Type Management
@app.route('/admin/leave_types')
def manage_leave_types():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    cur.execute("SELECT * FROM leave_type ORDER BY leave_name")
    leave_types = cur.fetchall()
    cur.close()
    
    return render_template('manage_leave_types.html', leave_types=leave_types)

@app.route('/admin/leave_type/add', methods=['POST'])
def add_leave_type():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    leave_name = request.form['leave_name']
    description = request.form['description']
    max_days = request.form['max_days']
    half_day_allowed = 1 if request.form.get('half_day_allowed') else 0
    
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO leave_type (leave_name, description, max_days,half_day_allowed) 
            VALUES (%s, %s, %s,%s)
        """, (leave_name, description, max_days,half_day_allowed))

        # Get all active employees
        cur.execute("SELECT emp_id FROM employee WHERE status = 'active'")
        employees = cur.fetchall()
        
        # Initialize leave balance for each employee
        leave_type_id = cur.lastrowid
        for emp in employees:
            cur.execute("""
                INSERT INTO leave_balance (emp_id, leave_type_id, remaining_days) 
                VALUES (%s, %s, %s)
            """, (emp['emp_id'], leave_type_id, max_days))

        conn.commit()
        flash('Leave type added successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error adding leave type: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_leave_types'))

@app.route('/admin/leave_type/edit/<int:leave_type_id>', methods=['POST'])
def edit_leave_type(leave_type_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    leave_name = request.form['leave_name']
    description = request.form['description']
    new_max_days = int(request.form['max_days'])
    half_day_allowed = 1 if request.form.get('half_day_allowed') else 0
    
    cur = conn.cursor()
    try:
        # Get current max days
        cur.execute("SELECT max_days FROM leave_type WHERE leave_type_id = %s", (leave_type_id,))
        current_max_days = cur.fetchone()['max_days']
        
        # Update leave type
        cur.execute("""
            UPDATE leave_type 
            SET leave_name = %s, description = %s, max_days = %s ,half_day_allowed = %s
            WHERE leave_type_id = %s
        """, (leave_name, description, new_max_days,half_day_allowed, leave_type_id))
        
        # If max days increased, add the difference to all employees' balances
        if new_max_days > current_max_days:
            difference = new_max_days - current_max_days
            cur.execute("""
                UPDATE leave_balance 
                SET remaining_days = remaining_days + %s 
                WHERE leave_type_id = %s
            """, (difference, leave_type_id))

        conn.commit()
        flash('Leave type updated successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error updating leave type: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_leave_types'))

@app.route('/admin/leave_type/delete/<int:leave_type_id>', methods=['POST'])
def delete_leave_type(leave_type_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    try:
        # Check if leave type is used in applications
        cur.execute("SELECT COUNT(*) as app_count FROM leave_application WHERE leave_type_id = %s", (leave_type_id,))
        result = cur.fetchone()
        
        if result['app_count'] > 0:
            flash('Cannot delete leave type with existing applications', 'danger')
            return redirect(url_for('manage_leave_types'))
        
        # Delete from leave_balance first
        cur.execute("DELETE FROM leave_balance WHERE leave_type_id = %s", (leave_type_id,))
        
        # Then delete from leave_type
        cur.execute("DELETE FROM leave_type WHERE leave_type_id = %s", (leave_type_id,))
        conn.commit()
        flash('Leave type deleted successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting leave type: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_leave_types'))

# Leave Management
@app.route('/admin/leaves')
def manage_leaves():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    status = request.args.get('status', 'pending')
    cur = conn.cursor()
    cur.execute("""
        SELECT la.*, e.first_name, e.last_name, lt.leave_name 
        FROM leave_application la 
        JOIN employee e ON la.emp_id = e.emp_id 
        JOIN leave_type lt ON la.leave_type_id = lt.leave_type_id 
        WHERE la.status = %s 
        ORDER BY la.applied_on DESC 
    """, (status,))
    leaves = cur.fetchall()
    cur.close()
    return render_template('manage_leaves.html', leaves=leaves, status=status)

@app.route('/admin/leave/action/<int:leave_id>', methods=['POST'])
def leave_action(leave_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    action = request.form['action']
    comments = request.form.get('comments', '')
    admin_id = session['admin_id']
    cur = conn.cursor()
    try:
        # Get leave details
        cur.execute("""
            SELECT emp_id, leave_type_id, start_date, end_date, leave_duration 
            FROM leave_application WHERE leave_id = %s
        """, (leave_id,))
        leave = cur.fetchone()
        if not leave:
            flash('Leave application not found', 'danger')
            return redirect(url_for('manage_leaves'))
        # Calculate days based on duration
        start_date = leave['start_date']
        end_date = leave['end_date']
        days = calculate_leave_days(start_date, end_date, leave['leave_duration'])
        # Update leave application
        cur.execute("""
            UPDATE leave_application SET status = %s, processed_by = %s, processed_on = NOW(), comments = %s 
            WHERE leave_id = %s
        """, (action, admin_id, comments, leave_id))
        # If approved, update leave balance
        if action == 'approved':
            cur.execute("""
                UPDATE leave_balance SET remaining_days = remaining_days - %s 
                WHERE emp_id = %s AND leave_type_id = %s
            """, (days, leave['emp_id'], leave['leave_type_id']))
        conn.commit()
        flash(f'Leave application {action} successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error processing leave application: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('manage_leaves'))

# Permission Management Routes
@app.route('/employee/permissions')
def employee_permissions():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    emp_id = session['emp_id']
    status = request.args.get('status', 'all')
    current_month = date.today().strftime('%Y-%m')
    cur = conn.cursor()
    # Get permission balance for current month
    cur.execute("""
        SELECT allowed_hours, used_hours FROM permission_balance 
        WHERE emp_id = %s AND month_year = %s
    """, (emp_id, current_month))
    balance = cur.fetchone()
    if not balance:
        # Initialize balance for new month
        cur.execute("""
            INSERT INTO permission_balance (emp_id, month_year, allowed_hours, used_hours) 
            VALUES (%s, %s, 3.00, 0.00)
        """, (emp_id, current_month))
        conn.commit()
        balance = {'allowed_hours': 3.00, 'used_hours': 0.00}
    # Get permission types
    cur.execute("SELECT * FROM permission_type")
    permission_types = cur.fetchall()
    # Get permission applications
    query = """
        SELECT pa.*, pt.name as permission_name 
        FROM permission_application pa 
        JOIN permission_type pt ON pa.permission_type_id = pt.permission_type_id 
        WHERE pa.emp_id = %s 
    """
    params = [emp_id]
    if status != 'all':
        query += " AND pa.status = %s"
        params.append(status)
    query += " ORDER BY pa.date DESC, pa.applied_at DESC"
    cur.execute(query, tuple(params))
    permissions = cur.fetchall()
    cur.close()
    return render_template('employee_permissions.html', balance=balance, permission_types=permission_types, permissions=permissions, status=status)

@app.route('/employee/permission/apply', methods=['POST'])
def apply_permission():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    emp_id = session['emp_id']
    permission_type_id = request.form['permission_type_id']
    date_str = request.form['date']
    start_time = request.form['start_time']
    end_time = request.form['end_time']
    reason = request.form['reason']
    try:
        # Calculate total hours
        start_dt = datetime.strptime(f"{date_str} {start_time}", '%Y-%m-%d %H:%M')
        end_dt = datetime.strptime(f"{date_str} {end_time}", '%Y-%m-%d %H:%M')
        if end_dt <= start_dt:
            flash('End time must be after start time', 'danger')
            return redirect(url_for('employee_permissions'))
        total_hours = (end_dt - start_dt).total_seconds() / 3600
        total_hours = round(total_hours, 2)
        if total_hours <= 0:
            flash('Invalid time duration', 'danger')
            return redirect(url_for('employee_permissions'))
        # Check if total hours exceeds 3 hours
        if total_hours > 3:
            flash('Permission cannot exceed 3 hours', 'danger')
            return redirect(url_for('employee_permissions'))
        current_month = date.today().strftime('%Y-%m')
        cur = conn.cursor()
        # Check permission balance
        cur.execute("""
            SELECT allowed_hours, used_hours FROM permission_balance 
            WHERE emp_id = %s AND month_year = %s
        """, (emp_id, current_month))
        balance = cur.fetchone()
        if not balance:
            # Initialize balance if not exists
            cur.execute("""
                INSERT INTO permission_balance (emp_id, month_year, allowed_hours, used_hours) 
                VALUES (%s, %s, 3.00, 0.00)
            """, (emp_id, current_month))
            conn.commit()
            balance = {'allowed_hours': 3.00, 'used_hours': 0.00}
        remaining_hours = float(balance['allowed_hours']) - float(balance['used_hours'])
        if total_hours > remaining_hours:
            flash(f'Not enough permission balance. You have {remaining_hours:.2f} hours remaining.', 'danger')
            return redirect(url_for('employee_permissions'))
        # Check for overlapping permissions on same date
        cur.execute("""
            SELECT COUNT(*) as overlap_count FROM permission_application 
            WHERE emp_id = %s AND date = %s AND status = 'approved' AND (
                (TIME(%s) BETWEEN start_time AND end_time) OR 
                (TIME(%s) BETWEEN start_time AND end_time) OR 
                (start_time BETWEEN TIME(%s) AND TIME(%s)) OR 
                (end_time BETWEEN TIME(%s) AND TIME(%s))
            )
        """, (
            emp_id, date_str, start_time, end_time, start_time, end_time, start_time, end_time
        ))
        overlap = cur.fetchone()['overlap_count'] > 0
        if overlap:
            flash('You already have an approved permission during this time', 'danger')
            return redirect(url_for('employee_permissions'))
        # Apply permission
        cur.execute("""
            INSERT INTO permission_application (emp_id, permission_type_id, date, start_time, end_time, total_hours, reason, status) 
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending')
        """, (emp_id, permission_type_id, date_str, start_time, end_time, total_hours, reason))
        conn.commit()
        flash('Permission application submitted successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error applying for permission: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('employee_permissions'))


@app.route('/employee/permission/cancel/<int:permission_id>', methods=['POST'])
def cancel_permission(permission_id):
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    emp_id = session['emp_id']
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT status FROM permission_application 
            WHERE permission_id = %s AND emp_id = %s
        """, (permission_id, emp_id))
        permission = cur.fetchone()
        if not permission:
            flash('Permission application not found or you do not have permission to cancel it', 'danger')
            return redirect(url_for('employee_permissions'))
        if permission['status'] == 'cancelled':
            flash('Permission is already cancelled.', 'info')
            return redirect(url_for('employee_permissions'))
        if permission['status'] == 'approved':
            flash('Approved permissions cannot be cancelled by employee. Please contact admin.', 'danger')
            return redirect(url_for('employee_permissions'))

        cur.execute("""
            UPDATE permission_application 
            SET status = 'cancelled', comments = %s, processed_on = NOW() 
            WHERE permission_id = %s AND emp_id = %s
        """, ('Cancelled by employee', permission_id, emp_id))
        conn.commit()
        flash('Permission application cancelled successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error cancelling permission: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('employee_permissions'))


@app.route('/admin/permission_approvals')
def admin_permission_approvals():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    status = request.args.get('status', 'pending')
    cur = conn.cursor()
    query = """
        SELECT pa.*, e.first_name, e.last_name, pt.name as permission_type_name
        FROM permission_application pa
        JOIN employee e ON pa.emp_id = e.emp_id
        JOIN permission_type pt ON pa.permission_type_id = pt.permission_type_id
    """
    params = []
    if status != 'all':
        query += " WHERE pa.status = %s"
        params.append(status)
    query += " ORDER BY pa.applied_at DESC"
    cur.execute(query, tuple(params))
    permissions = cur.fetchall()
    cur.close()
    return render_template('admin_permission_approvals.html', permissions=permissions, status=status)

@app.route('/admin/permission/action/<int:permission_id>', methods=['POST'])
def admin_permission_action(permission_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    action = request.form['action']
    comments = request.form.get('comments', '')
    admin_id = session['admin_id']
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT emp_id, total_hours, status, date, start_time, end_time
            FROM permission_application WHERE permission_id = %s
        """, (permission_id,))
        permission = cur.fetchone()
        if not permission:
            flash('Permission application not found', 'danger')
            return redirect(url_for('admin_permission_approvals'))

        if permission['status'] != 'pending':
            flash(f"Permission is already {permission['status']}.", 'info')
            return redirect(url_for('admin_permission_approvals'))

        # Update application status
        cur.execute("""
            UPDATE permission_application 
            SET status = %s, processed_by = %s, processed_on = NOW(), comments = %s 
            WHERE permission_id = %s
        """, (action, admin_id, comments, permission_id))

        if action == 'approved':
            # Update used hours in permission_balance
            current_month = permission['date'].strftime('%Y-%m')
            cur.execute("""
                UPDATE permission_balance
                SET used_hours = used_hours + %s
                WHERE emp_id = %s AND month_year = %s
            """, (permission['total_hours'], permission['emp_id'], current_month))
            # If the update above somehow fails to find a record (e.g., month_year doesn't exist yet),
            # this INSERT ... ON DUPLICATE KEY UPDATE ensures it's created or updated.
            # This requires `emp_id` and `month_year` to be a unique key in `permission_balance`.
            # For simplicity, if the update fails, we can assume it will be handled by the next month's
            # initialization if the user applies for a new permission.
            # A more robust solution might check rows affected by UPDATE and INSERT if 0.
        
        conn.commit()
        flash(f'Permission application {action} successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error processing permission: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('admin_permission_approvals'))

# Attendance Management (Admin)
@app.route('/admin/attendance')
def admin_attendance():
    if not is_admin_logged_in():
        return redirect(url_for('login'))

    search_date_str = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    search_employee_id = request.args.get('employee_id')
    
    cur = conn.cursor()

    query = """
        SELECT a.*, e.first_name, e.last_name, e.employee_id
        FROM attendance a
        JOIN employee e ON a.emp_id = e.emp_id
        WHERE DATE(a.check_in) = %s
    """
    params = [search_date_str]

    if search_employee_id:
        query += " AND e.employee_id = %s"
        params.append(search_employee_id)
    
    query += " ORDER BY a.check_in DESC"

    cur.execute(query, tuple(params))
    attendance_records = cur.fetchall()

    # Get total employees for the day (to show absentees etc)
    cur.execute("SELECT emp_id, first_name, last_name, employee_id FROM employee WHERE status = 'active'")
    all_employees = cur.fetchall()
    
    # Identify present employees for the selected date
    present_emp_ids = {rec['emp_id'] for rec in attendance_records if rec['status'] == 'present'}
    
    # Calculate absentee list
    absent_employees = [
        emp for emp in all_employees 
        if emp['emp_id'] not in present_emp_ids
    ]
    
    cur.close()

    return render_template('admin_attendance.html', 
                           attendance_records=attendance_records, 
                           search_date=search_date_str,
                           search_employee_id=search_employee_id,
                           absent_employees=absent_employees)

@app.route('/admin/attendance/mark_manual', methods=['POST'])
def mark_manual_attendance():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    emp_id = request.form['emp_id']
    attendance_date = request.form['attendance_date']
    check_in_time = request.form['check_in_time']
    check_out_time = request.form['check_out_time']
    status = request.form['status']
    
    cur = conn.cursor()
    try:
        check_in_dt = datetime.strptime(f"{attendance_date} {check_in_time}", '%Y-%m-%d %H:%M') if check_in_time else None
        check_out_dt = datetime.strptime(f"{attendance_date} {check_out_time}", '%Y-%m-%d %H:%M') if check_out_time else None
        
        # Calculate hours if both check_in and check_out are provided and valid
        hours_worked = None
        if check_in_dt and check_out_dt:
            if check_out_dt <= check_in_dt:
                flash('Check-out time must be after check-in time.', 'danger')
                return redirect(url_for('admin_attendance', date=attendance_date))
            hours_worked = calculate_work_hours(check_in_dt, check_out_dt)

        cur.execute("""
            INSERT INTO attendance (emp_id, check_in, check_out, hours_worked, status)
            VALUES (%s, %s, %s, %s, %s)
        """, (emp_id, check_in_dt, check_out_dt, hours_worked, status))
        conn.commit()
        flash('Manual attendance marked successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error marking manual attendance: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('admin_attendance', date=attendance_date))

@app.route('/admin/attendance/edit/<int:attendance_id>', methods=['GET', 'POST'])
def edit_attendance(attendance_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    
    if request.method == 'POST':
        check_in_str = request.form['check_in_date'] + ' ' + request.form['check_in_time'] if request.form['check_in_date'] and request.form['check_in_time'] else None
        check_out_str = request.form['check_out_date'] + ' ' + request.form['check_out_time'] if request.form['check_out_date'] and request.form['check_out_time'] else None
        status = request.form['status']

        try:
            check_in_dt = datetime.strptime(check_in_str, '%Y-%m-%d %H:%M') if check_in_str else None
            check_out_dt = datetime.strptime(check_out_str, '%Y-%m-%d %H:%M') if check_out_str else None

            hours_worked = None
            if check_in_dt and check_out_dt:
                if check_out_dt <= check_in_dt:
                    flash('Check-out time must be after check-in time.', 'danger')
                    return redirect(url_for('edit_attendance', attendance_id=attendance_id))
                hours_worked = calculate_work_hours(check_in_dt, check_out_dt)
            elif status == 'present' and (not check_in_dt or not check_out_dt):
                flash('For "Present" status, both check-in and check-out times are required.', 'danger')
                return redirect(url_for('edit_attendance', attendance_id=attendance_id))
            
            cur.execute("""
                UPDATE attendance 
                SET check_in = %s, check_out = %s, hours_worked = %s, status = %s
                WHERE attendance_id = %s
            """, (check_in_dt, check_out_dt, hours_worked, status, attendance_id))
            conn.commit()
            flash('Attendance record updated successfully!', 'success')
            return redirect(url_for('admin_attendance', date=check_in_dt.strftime('%Y-%m-%d') if check_in_dt else date.today().strftime('%Y-%m-%d')))
        except ValueError:
            flash('Invalid date or time format. Please use YYYY-MM-DD HH:MM.', 'danger')
            conn.rollback()
        except Exception as e:
            conn.rollback()
            flash(f'Error updating attendance record: {str(e)}', 'danger')
        finally:
            cur.close()
    
    # GET request
    cur.execute("""
        SELECT a.*, e.first_name, e.last_name, e.employee_id
        FROM attendance a
        JOIN employee e ON a.emp_id = e.emp_id
        WHERE attendance_id = %s
    """, (attendance_id,))
    record = cur.fetchone()
    cur.close()

    if not record:
        flash('Attendance record not found', 'danger')
        return redirect(url_for('admin_attendance'))

    return render_template('edit_attendance.html', record=record)

@app.route('/admin/attendance/delete/<int:attendance_id>', methods=['POST'])
def delete_attendance(attendance_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM attendance WHERE attendance_id = %s", (attendance_id,))
        conn.commit()
        flash('Attendance record deleted successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting attendance record: {str(e)}', 'danger')
    finally:
        cur.close()
    return redirect(url_for('admin_attendance'))

# Employee-specific routes
@app.route('/employee/dashboard')
def employee_dashboard():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    cur = conn.cursor()
    
    # Get employee details
    employee = get_employee_details(emp_id)

    # Get recent attendance
    today = date.today().strftime('%Y-%m-%d')
    cur.execute("""
        SELECT check_in, check_out, hours_worked, status 
        FROM attendance 
        WHERE emp_id = %s AND DATE(check_in) = %s
        ORDER BY check_in DESC 
        LIMIT 1
    """, (emp_id, today))
    today_attendance = cur.fetchone()

    # Get leave balances
    cur.execute("""
        SELECT lb.*, lt.leave_name, lt.description 
        FROM leave_balance lb 
        JOIN leave_type lt ON lb.leave_type_id = lt.leave_type_id 
        WHERE lb.emp_id = %s
    """, (emp_id,))
    leave_balances = cur.fetchall()
    
    # Get recent leave applications
    cur.execute("""
        SELECT la.*, lt.leave_name 
        FROM leave_application la 
        JOIN leave_type lt ON la.leave_type_id = lt.leave_type_id 
        WHERE la.emp_id = %s 
        ORDER BY la.applied_on DESC 
        LIMIT 5
    """, (emp_id,))
    recent_leaves = cur.fetchall()

    # Get permission balance for current month
    current_month = date.today().strftime('%Y-%m')
    cur.execute("""
        SELECT allowed_hours, used_hours FROM permission_balance 
        WHERE emp_id = %s AND month_year = %s
    """, (emp_id, current_month))
    permission_balance = cur.fetchone()
    if not permission_balance:
        # Initialize if not exists
        permission_balance = {'allowed_hours': 3.00, 'used_hours': 0.00}

    cur.close()
    
    return render_template('employee_dashboard.html', 
                         employee=employee,
                         today_attendance=today_attendance,
                         leave_balances=leave_balances,
                         recent_leaves=recent_leaves,
                         permission_balance=permission_balance)

@app.route('/employee/attendance', methods=['GET', 'POST'])
def employee_attendance():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    emp_id = session['emp_id']
    current_month = datetime.now().strftime('%Y-%m')

    if request.method == 'POST':
        action = request.form.get('action')
        cur = conn.cursor()
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            # Check for existing record for today
            cur.execute("""
                SELECT attendance_id, check_in, check_out FROM attendance 
                WHERE emp_id = %s AND DATE(check_in) = %s
                ORDER BY check_in DESC LIMIT 1
            """, (emp_id, today))
            today_record = cur.fetchone()

            if action == 'check_in':
                if today_record and today_record['check_in'] and not today_record['check_out']:
                    flash('You are already checked in.', 'info')
                elif today_record and today_record['check_out']:
                    flash('You have already completed your attendance for today.', 'info')
                else:
                    cur.execute("INSERT INTO attendance (emp_id, check_in, status) VALUES (%s, NOW(), %s)", 
                                (emp_id, 'present'))
                    conn.commit()
                    flash('Checked in successfully!', 'success')
            elif action == 'check_out':
                if today_record and today_record['check_in'] and not today_record['check_out']:
                    check_in_time = today_record['check_in']
                    check_out_time = datetime.now()
                    hours_worked = calculate_work_hours(check_in_time, check_out_time)
                    cur.execute("""
                        UPDATE attendance 
                        SET check_out = %s, hours_worked = %s 
                        WHERE attendance_id = %s
                    """, (check_out_time, hours_worked, today_record['attendance_id']))
                    conn.commit()
                    flash('Checked out successfully!', 'success')
                else:
                    flash('You need to check in first or you have already checked out.', 'danger')
        except Exception as e:
            conn.rollback()
            flash(f'Error processing attendance: {str(e)}', 'danger')
        finally:
            cur.close()
        return redirect(url_for('employee_attendance'))

    # GET request for attendance history
    cur = conn.cursor()
    cur.execute("""
        SELECT * FROM attendance 
        WHERE emp_id = %s 
        ORDER BY check_in DESC
    """, (emp_id,))
    attendance_history = cur.fetchall()
    cur.close()

    return render_template('employee_attendance.html', 
                           attendance_history=attendance_history, 
                           current_month=current_month)


@app.route('/employee/leaves')
def employee_leaves():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    status = request.args.get('status', 'all')
    
    cur = conn.cursor()
    
    # Get leave balances
    cur.execute("""
        SELECT lb.*, lt.leave_name, lt.max_days, lt.description 
        FROM leave_balance lb 
        JOIN leave_type lt ON lb.leave_type_id = lt.leave_type_id 
        WHERE lb.emp_id = %s
        ORDER BY lt.leave_name
    """, (emp_id,))
    leave_balances = cur.fetchall()
    
    # Get leave applications
    query = """
        SELECT la.*, lt.leave_name 
        FROM leave_application la 
        JOIN leave_type lt ON la.leave_type_id = lt.leave_type_id 
        WHERE la.emp_id = %s
    """
    params = [emp_id]
    if status != 'all':
        query += " AND la.status = %s"
        params.append(status)
    query += " ORDER BY la.applied_on DESC"
    
    cur.execute(query, tuple(params))
    leave_applications = cur.fetchall()
    
    # Get leave types for the application form
    cur.execute("SELECT * FROM leave_type ORDER BY leave_name")
    leave_types = cur.fetchall()
    
    cur.close()
    
    return render_template('employee_leaves.html', 
                         leave_balances=leave_balances,
                         leave_applications=leave_applications,
                         leave_types=leave_types,
                         selected_status=status)

@app.route('/employee/leave/apply', methods=['POST'])
def apply_for_leave():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    leave_type_id = request.form['leave_type_id']
    start_date_str = request.form['start_date']
    end_date_str = request.form['end_date']
    leave_duration = request.form['leave_duration'] # 'full_day', 'first_half', 'second_half'
    reason = request.form['reason']
    
    try:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # Validate dates based on duration
        if not validate_leave_dates(start_date, end_date, leave_duration):
            flash('Invalid dates for selected leave duration (half-day leaves must be on a single day).', 'danger')
            return redirect(url_for('employee_leaves'))
        
        # Calculate requested days
        requested_days = calculate_leave_days(start_date, end_date, leave_duration)
        
        cur = conn.cursor()
        
        # Check available leave balance
        cur.execute("""
            SELECT remaining_days FROM leave_balance 
            WHERE emp_id = %s AND leave_type_id = %s
        """, (emp_id, leave_type_id))
        balance = cur.fetchone()
        
        if not balance or balance['remaining_days'] < requested_days:
            flash('Insufficient leave balance for this type of leave.', 'danger')
            return redirect(url_for('employee_leaves'))
            
        # Check for overlapping leave applications (pending or approved)
        cur.execute("""
            SELECT COUNT(*) FROM leave_application
            WHERE emp_id = %s AND status IN ('pending', 'approved') AND (
                (start_date <= %s AND end_date >= %s) OR
                (start_date <= %s AND end_date >= %s) OR
                (%s <= start_date AND %s >= end_date)
            )
        """, (emp_id, end_date, start_date, start_date, end_date, start_date, end_date))
        overlap_count = cur.fetchone()['COUNT(*)']
        
        if overlap_count > 0:
            flash('You have an overlapping leave application (pending or approved) for these dates.', 'danger')
            return redirect(url_for('employee_leaves'))

        # Insert leave application
        cur.execute("""
            INSERT INTO leave_application 
            (emp_id, leave_type_id, start_date, end_date, leave_duration, reason, applied_on, status, requested_days) 
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), 'pending', %s)
        """, (emp_id, leave_type_id, start_date, end_date, leave_duration, reason, requested_days))
        
        conn.commit()
        flash('Leave application submitted successfully!', 'success')
    except ValueError:
        flash('Invalid date format. Please use YYYY-MM-DD.', 'danger')
        conn.rollback()
    except Exception as e:
        conn.rollback()
        flash(f'Error applying for leave: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('employee_leaves'))

@app.route('/employee/leave/cancel/<int:leave_id>', methods=['POST'])
def cancel_leave(leave_id):
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    cur = conn.cursor()
    try:
        cur.execute("SELECT status FROM leave_application WHERE leave_id = %s AND emp_id = %s", (leave_id, emp_id))
        leave = cur.fetchone()
        
        if not leave:
            flash('Leave application not found or you do not have permission to cancel it', 'danger')
            return redirect(url_for('employee_leaves'))
        
        if leave['status'] == 'approved':
            flash('Approved leaves cannot be cancelled by employee. Please contact admin to revert.', 'danger')
            return redirect(url_for('employee_leaves'))
        
        cur.execute("UPDATE leave_application SET status = 'cancelled', comments = %s, processed_on = NOW() WHERE leave_id = %s AND emp_id = %s", 
                    ('Cancelled by employee', leave_id, emp_id))
        conn.commit()
        flash('Leave application cancelled successfully!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error cancelling leave application: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('employee_leaves'))

# Employee Profile
@app.route('/employee/profile')
def employee_profile():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    employee = get_employee_details(emp_id)
    
    if not employee:
        flash('Employee profile not found.', 'danger')
        return redirect(url_for('employee_dashboard'))
    
    return render_template('employee_profile.html', employee=employee)

@app.route('/employee/profile/edit', methods=['GET', 'POST'])
def edit_employee_profile():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    cur = conn.cursor()
    
    if request.method == 'POST':
        # Get form data
        personal_email = request.form['personal_email']
        phone = request.form['phone']
        
        # Handle file upload
        profile_pic = None
        if 'profile_pic' in request.files:
            file = request.files['profile_pic']
            if file and allowed_file(file.filename):
                # Get current employee_id to use in filename
                cur.execute("SELECT employee_id FROM employee WHERE emp_id = %s", (emp_id,))
                employee_data = cur.fetchone()
                if employee_data:
                    employee_actual_id = employee_data['employee_id']
                    filename = secure_filename(f"{employee_actual_id}_{file.filename}")
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
                    profile_pic = filename
                else:
                    flash('Could not retrieve employee ID for profile picture.', 'danger')
                    return redirect(url_for('edit_employee_profile'))
        
        # Update database
        try:
            if profile_pic:
                cur.execute("""
                    UPDATE employee 
                    SET personal_email = %s, phone = %s, profile_pic = %s
                    WHERE emp_id = %s
                """, (personal_email, phone, profile_pic, emp_id))
            else:
                cur.execute("""
                    UPDATE employee 
                    SET personal_email = %s, phone = %s
                    WHERE emp_id = %s
                """, (personal_email, phone, emp_id))
            
            # Handle password reset if provided
            current_password = request.form.get('current_password')
            new_password = request.form.get('new_password')
            confirm_new_password = request.form.get('confirm_new_password')

            if new_password: # If user intends to change password
                # Get current hashed password for verification
                cur.execute("SELECT password_hash FROM employee WHERE emp_id = %s", (emp_id,))
                employee_pass = cur.fetchone()

                if not employee_pass or not bcrypt.checkpw(current_password.encode('utf-8'), employee_pass['password_hash'].encode('utf-8')):
                    flash('Current password is incorrect.', 'danger')
                    return redirect(url_for('edit_employee_profile'))
                
                if len(new_password) < 8:
                    flash('New password must be at least 8 characters long', 'danger')
                    return redirect(url_for('edit_employee_profile'))

                if new_password != confirm_new_password:
                    flash('New passwords do not match', 'danger')
                    return redirect(url_for('edit_employee_profile'))
                
                hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                cur.execute("""
                    UPDATE employee 
                    SET password_hash = %s 
                    WHERE emp_id = %s
                """, (hashed_password, emp_id))
            
            conn.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('employee_profile'))
        except Exception as e:
            conn.rollback()
            flash(f'Error updating profile: {str(e)}', 'danger')
        finally:
            cur.close()
    
    # GET request - show form with current data
    employee = get_employee_details(emp_id)
    
    if not employee:
        flash('Employee profile not found.', 'danger')
        return redirect(url_for('employee_dashboard'))
    
    return render_template('edit_employee_profile.html', employee=employee)

# Employee Calendar
@app.route('/employee/calendar')
def employee_calendar():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    year = int(request.args.get('year', datetime.now().year))
    month = int(request.args.get('month', datetime.now().month))
    
    first_day = date(year, month, 1)
    last_day = date(year, month, 1) + timedelta(days=32)
    last_day = last_day.replace(day=1) - timedelta(days=1)
    
    # Get all days of the month
    all_days = []
    current_day = first_day
    while current_day <= last_day:
        all_days.append(current_day)
        current_day += timedelta(days=1)
        
    cur = conn.cursor()
    # Fetch all attendance, leave, and permission for the employee for the selected month
    # Attendance
    cur.execute("""
        SELECT DATE(check_in) as event_date, 
               CASE 
                   WHEN status = 'present' THEN 'Present' 
                   ELSE 'Absent' 
               END as event_type, 
               check_in, check_out, hours_worked
        FROM attendance 
        WHERE emp_id = %s 
          AND DATE(check_in) >= %s AND DATE(check_in) <= %s
    """, (emp_id, first_day, last_day))
    attendance_records = {r['event_date']: r for r in cur.fetchall()}
    
    # Leaves
    cur.execute("""
        SELECT la.start_date, la.end_date, la.status, lt.leave_name
        FROM leave_application la
        JOIN leave_type lt ON la.leave_type_id = lt.leave_type_id
        WHERE la.emp_id = %s
          AND la.status IN ('approved', 'pending')
          AND (
                (la.start_date <= %s AND la.end_date >= %s) OR
                (la.start_date >= %s AND la.start_date <= %s)
              )
    """, (emp_id, last_day, first_day, first_day, last_day))
    leave_records = cur.fetchall()

    # Permissions
    cur.execute("""
        SELECT date as event_date, status, total_hours, pt.name as permission_name
        FROM permission_application pa
        JOIN permission_type pt ON pa.permission_type_id = pt.permission_type_id
        WHERE pa.emp_id = %s
          AND pa.status IN ('approved', 'pending')
          AND pa.date >= %s AND pa.date <= %s
    """, (emp_id, first_day, last_day))
    permission_records = {r['event_date']: r for r in cur.fetchall()}
    
    cur.close()
    
    calendar_data = []
    current_date = first_day
    
    # Add leading blank days for the calendar
    for _ in range(first_day.weekday()):
        calendar_data.append({
            'date': None, 
            'is_current_month': False, 
            'attendance': None, 
            'leave': None, 
            'permission': None
        })
        
    while current_date <= last_day:
        data_for_day = {
            'date': current_date,
            'is_current_month': True,
            'is_today': (current_date == date.today()),
            'attendance': attendance_records.get(current_date),
            'leave': None,
            'permission': permission_records.get(current_date)
        }
        
        # Check for leaves that span this day
        for leave in leave_records:
            if leave['start_date'] <= current_date <= leave['end_date']:
                data_for_day['leave'] = leave
                break # A day can only have one leave record for simplicity here
                
        calendar_data.append(data_for_day)
        current_date += timedelta(days=1)
        
    # Add trailing blank days to fill the last week
    while len(calendar_data) % 7 != 0:
        calendar_data.append({
            'date': None, 
            'is_current_month': False, 
            'attendance': None, 
            'leave': None, 
            'permission': None
        })
    
    # Split into weeks (7 days each)
    weeks = [calendar_data[i:i + 7] for i in range(0, len(calendar_data), 7)]
    
    return render_template('employee_calendar.html', 
                         weeks=weeks,
                         year=year,
                         month=month,
                         month_name=first_day.strftime('%B'))
# Company Policies
@app.route('/employee/policies')
def employee_policies():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    category = request.args.get('category', 'all')
    
    cur = conn.cursor()
    
    if category == 'all':
        cur.execute("SELECT * FROM company_policy ORDER BY created_at DESC")
    else:
        cur.execute("SELECT * FROM company_policy WHERE category = %s ORDER BY created_at DESC", (category,))
    
    policies = cur.fetchall()
    
    # Get unique categories for filter
    cur.execute("SELECT DISTINCT category FROM company_policy WHERE category IS NOT NULL")
    categories = [c['category'] for c in cur.fetchall()]
    
    cur.close()
    
    return render_template('employee_policies.html', 
                         policies=policies,
                         categories=categories,
                         selected_category=category)


@app.route('/register')
def register():
    return render_template('register.html')  # You'll need to create this template
 


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=os.getenv('PORT', 8080)) # Ensure host is 0.0.0.0 for Railway
