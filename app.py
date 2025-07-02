import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, send_file
import pymysql
pymysql.install_as_MySQLdb()
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import bcrypt
from datetime import datetime, timedelta, date
import csv
from io import StringIO
from io import BytesIO
from decimal import Decimal
from flask import make_response
import pymysql
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

conn = pymysql.connect(
    host=os.getenv("MYSQLHOST"),
    user=os.getenv("MYSQLUSER"),
    password=os.getenv("MYSQLPASSWORD"),
    db=os.getenv("MYSQLDATABASE"),
    port=int(os.getenv("MYSQLPORT", 3306)),
    cursorclass=pymysql.cursors.DictCursor,
    autocommit=True
)

class MySQLWrapper:
    def __init__(self, app):
        self.app = app
        self._connection = None
    
    @property
    def connection(self):
        if not self._connection or not self._connection.open:
            self._connection = pymysql.connect(
app.config['MYSQL_HOST'] = os.getenv('MYSQL_HOST', 'localhost')
app.config['MYSQL_USER'] = os.getenv('MYSQL_USER', 'root')
app.config['MYSQL_PASSWORD'] = os.getenv('MYSQL_PASSWORD', '12345')
app.config['MYSQL_DB'] = os.getenv('MYSQL_DB', 'attendance_system')
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=True
            )
        return self._connection

mysql = MySQLWrapper(app)

# File upload configuration
UPLOAD_FOLDER = 'static/uploads/profile_pics'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Helper functions
def get_db_connection():
    return mysql.connection.cursor()

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
    cur = mysql.connection.cursor()
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
    cur = mysql.connection.cursor()
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
            cur = mysql.connection.cursor()
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
            cur = mysql.connection.cursor()
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
    
    cur = mysql.connection.cursor()
    
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
    
    cur = mysql.connection.cursor()
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
    cur = mysql.connection.cursor()
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
    cur = mysql.connection.cursor()
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
        mysql.connection.commit()
        flash('Leave balance updated successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
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
        cur = mysql.connection.cursor()
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
            
            mysql.connection.commit()
            flash('Employee added successfully!', 'success')
            return redirect(url_for('manage_employees'))
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Error adding employee: {str(e)}', 'danger')
        finally:
            cur.close()
    
    # GET request - show form
    cur = mysql.connection.cursor()
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
    
    cur = mysql.connection.cursor()
    
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
            
            mysql.connection.commit()
            flash('Employee updated successfully!', 'success')
            return redirect(url_for('manage_employees'))
        except Exception as e:
            mysql.connection.rollback()
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
    
    cur = mysql.connection.cursor()
    try:
        # Delete all related records first
        cur.execute("DELETE FROM leave_balance WHERE emp_id = %s", (emp_id,))
        cur.execute("DELETE FROM leave_application WHERE emp_id = %s", (emp_id,))
        cur.execute("DELETE FROM attendance WHERE emp_id = %s", (emp_id,))
        
        # Then delete the employee
        cur.execute("DELETE FROM employee WHERE emp_id = %s", (emp_id,))
        mysql.connection.commit()
        flash('Employee deleted successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
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
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            UPDATE employee 
            SET password_hash = %s 
            WHERE emp_id = %s
        """, (hashed_password, emp_id))
        mysql.connection.commit()
        flash('Password reset successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error resetting password: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('edit_employee', emp_id=emp_id))

# Department Management
@app.route('/admin/departments')
def manage_departments():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
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
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO department (dept_name, description) 
            VALUES (%s, %s)
        """, (dept_name, description))
        mysql.connection.commit()
        flash('Department added successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
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
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            UPDATE department 
            SET dept_name = %s, description = %s 
            WHERE dept_id = %s
        """, (dept_name, description, dept_id))
        mysql.connection.commit()
        flash('Department updated successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error updating department: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_departments'))

@app.route('/admin/department/delete/<int:dept_id>', methods=['POST'])
def delete_department(dept_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    try:
        # Check if department has employees
        cur.execute("SELECT COUNT(*) as emp_count FROM employee WHERE dept_id = %s", (dept_id,))
        result = cur.fetchone()
        
        if result['emp_count'] > 0:
            flash('Cannot delete department with assigned employees', 'danger')
            return redirect(url_for('manage_departments'))
        
        cur.execute("DELETE FROM department WHERE dept_id = %s", (dept_id,))
        mysql.connection.commit()
        flash('Department deleted successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error deleting department: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_departments'))

# Designation Management
@app.route('/admin/designations')
def manage_designations():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
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
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO designation (desig_name, description) 
            VALUES (%s, %s)
        """, (desig_name, description))
        mysql.connection.commit()
        flash('Designation added successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
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
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            UPDATE designation 
            SET desig_name = %s, description = %s 
            WHERE desig_id = %s
        """, (desig_name, description, desig_id))
        mysql.connection.commit()
        flash('Designation updated successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error updating designation: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_designations'))

@app.route('/admin/designation/delete/<int:desig_id>', methods=['POST'])
def delete_designation(desig_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    try:
        # Check if designation has employees
        cur.execute("SELECT COUNT(*) as emp_count FROM employee WHERE desig_id = %s", (desig_id,))
        result = cur.fetchone()
        
        if result['emp_count'] > 0:
            flash('Cannot delete designation with assigned employees', 'danger')
            return redirect(url_for('manage_designations'))
        
        cur.execute("DELETE FROM designation WHERE desig_id = %s", (desig_id,))
        mysql.connection.commit()
        flash('Designation deleted successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error deleting designation: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_designations'))

# Leave Type Management
@app.route('/admin/leave_types')
def manage_leave_types():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
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
    
    cur = mysql.connection.cursor()
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

        mysql.connection.commit()
        flash('Leave type added successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
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
    
    cur = mysql.connection.cursor()
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

        mysql.connection.commit()
        flash('Leave type updated successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error updating leave type: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_leave_types'))

@app.route('/admin/leave_type/delete/<int:leave_type_id>', methods=['POST'])
def delete_leave_type(leave_type_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
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
        mysql.connection.commit()
        flash('Leave type deleted successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
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
    
    cur = mysql.connection.cursor()
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
    
    cur = mysql.connection.cursor()
    try:
        # Get leave details
        cur.execute("""
            SELECT emp_id, leave_type_id, start_date, end_date, leave_duration
            FROM leave_application 
            WHERE leave_id = %s
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
            UPDATE leave_application 
            SET status = %s, processed_by = %s, processed_on = NOW(), comments = %s 
            WHERE leave_id = %s
        """, (action, admin_id, comments, leave_id))
        
        # If approved, update leave balance
        if action == 'approved':
            cur.execute("""
                UPDATE leave_balance 
                SET remaining_days = remaining_days - %s 
                WHERE emp_id = %s AND leave_type_id = %s
            """, (days, leave['emp_id'], leave['leave_type_id']))
        
        mysql.connection.commit()
        flash(f'Leave application {action} successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
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
    
    cur = mysql.connection.cursor()
    
    # Get permission balance for current month
    cur.execute("""
        SELECT allowed_hours, used_hours 
        FROM permission_balance 
        WHERE emp_id = %s AND month_year = %s
    """, (emp_id, current_month))
    balance = cur.fetchone()
    
    if not balance:
        # Initialize balance for new month
        cur.execute("""
            INSERT INTO permission_balance (emp_id, month_year, allowed_hours, used_hours)
            VALUES (%s, %s, 3.00, 0.00)
        """, (emp_id, current_month))
        mysql.connection.commit()
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
    
    return render_template('employee_permissions.html',
                         balance=balance,
                         permission_types=permission_types,
                         permissions=permissions,
                         status=status)

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
        
        cur = mysql.connection.cursor()
        
        # Check permission balance
        cur.execute("""
            SELECT allowed_hours, used_hours 
            FROM permission_balance 
            WHERE emp_id = %s AND month_year = %s
        """, (emp_id, current_month))
        balance = cur.fetchone()
        
        if not balance:
            # Initialize balance if not exists
            cur.execute("""
                INSERT INTO permission_balance (emp_id, month_year, allowed_hours, used_hours)
                VALUES (%s, %s, 3.00, 0.00)
            """, (emp_id, current_month))
            mysql.connection.commit()
            balance = {'allowed_hours': 3.00, 'used_hours': 0.00}
        
        remaining_hours = float(balance['allowed_hours']) - float(balance['used_hours'])
        
        if total_hours > remaining_hours:
            flash(f'Not enough permission balance. You have {remaining_hours:.2f} hours remaining.', 'danger')
            return redirect(url_for('employee_permissions'))
        
        # Check for overlapping permissions on same date
        cur.execute("""
            SELECT COUNT(*) as overlap_count 
            FROM permission_application 
            WHERE emp_id = %s AND date = %s AND status = 'approved'
            AND (
                (TIME(%s) BETWEEN start_time AND end_time) OR
                (TIME(%s) BETWEEN start_time AND end_time) OR
                (start_time BETWEEN TIME(%s) AND TIME(%s)) OR
                (end_time BETWEEN TIME(%s) AND TIME(%s))
            )
        """, (
            emp_id, date_str,
            start_time, end_time,
            start_time, end_time,
            start_time, end_time
        ))
        overlap = cur.fetchone()['overlap_count'] > 0
        
        if overlap:
            flash('You already have an approved permission during this time', 'danger')
            return redirect(url_for('employee_permissions'))
        
        # Apply permission
        cur.execute("""
            INSERT INTO permission_application 
            (emp_id, permission_type_id, date, start_time, end_time, total_hours, reason)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (emp_id, permission_type_id, date_str, start_time, end_time, total_hours, reason))
        
        mysql.connection.commit()
        flash('Permission application submitted successfully!', 'success')
    except ValueError as e:
        flash('Invalid date or time format', 'danger')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error applying for permission: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('employee_permissions'))

@app.route('/employee/permission/cancel/<int:permission_id>', methods=['POST'])
def cancel_permission(permission_id):
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    
    cur = mysql.connection.cursor()
    try:
        # Check if permission can be cancelled (status is pending)
        cur.execute("""
            SELECT status FROM permission_application 
            WHERE permission_id = %s AND emp_id = %s
        """, (permission_id, emp_id))
        permission = cur.fetchone()
        
        if not permission:
            flash('Permission application not found', 'danger')
            return redirect(url_for('employee_permissions'))
        
        if permission['status'] != 'pending':
            flash('Only pending permissions can be cancelled', 'danger')
            return redirect(url_for('employee_permissions'))
        
        # Delete permission application
        cur.execute("""
            DELETE FROM permission_application 
            WHERE permission_id = %s
        """, (permission_id,))
        mysql.connection.commit()
        flash('Permission application cancelled successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error cancelling permission: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('employee_permissions'))

# Admin Permission Management
@app.route('/admin/permissions')
def manage_permissions():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    status = request.args.get('status', 'pending')
    month_year = request.args.get('month', date.today().strftime('%Y-%m'))
    
    cur = mysql.connection.cursor()
    
    # Get permission applications
    cur.execute("""
        SELECT pa.*, e.first_name, e.last_name, e.employee_id, pt.name as permission_name 
        FROM permission_application pa
        JOIN employee e ON pa.emp_id = e.emp_id
        JOIN permission_type pt ON pa.permission_type_id = pt.permission_type_id
        WHERE pa.status = %s AND DATE_FORMAT(pa.date, '%%Y-%%m') = %s
        ORDER BY pa.date, pa.applied_at
    """, (status, month_year))
    permissions = cur.fetchall()
    
    # Get permission types for filter
    cur.execute("SELECT * FROM permission_type")
    permission_types = cur.fetchall()
    
    cur.close()
    
    return render_template('manage_permissions.html',
                         permissions=permissions,
                         permission_types=permission_types,
                         status=status,
                         month_year=month_year)

@app.route('/admin/permission/action/<int:permission_id>', methods=['POST'])
def permission_action(permission_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    action = request.form['action']  # This will be 'approved' or 'rejected'
    comments = request.form.get('comments', '')
    admin_id = session['admin_id']
    
    cur = mysql.connection.cursor()
    try:
        # Get permission details
        cur.execute("""
            SELECT emp_id, date, total_hours 
            FROM permission_application 
            WHERE permission_id = %s
        """, (permission_id,))
        permission = cur.fetchone()
        
        if not permission:
            flash('Permission application not found', 'danger')
            return redirect(url_for('manage_permissions'))
        
        # Update permission application
        cur.execute("""
            UPDATE permission_application 
            SET status = %s, processed_by = %s, processed_at = NOW(), comments = %s 
            WHERE permission_id = %s
        """, (action, admin_id, comments, permission_id))
        
        # Only deduct hours if approved
        if action == 'approved':
            month_year = permission['date'].strftime('%Y-%m')
            
            # Check if balance record exists
            cur.execute("""
                SELECT used_hours 
                FROM permission_balance 
                WHERE emp_id = %s AND month_year = %s
            """, (permission['emp_id'], month_year))
            balance = cur.fetchone()
            
            if balance:
                cur.execute("""
                    UPDATE permission_balance 
                    SET used_hours = used_hours + %s 
                    WHERE emp_id = %s AND month_year = %s
                """, (permission['total_hours'], permission['emp_id'], month_year))
            else:
                cur.execute("""
                    INSERT INTO permission_balance (emp_id, month_year, allowed_hours, used_hours)
                    VALUES (%s, %s, 3.00, %s)
                """, (permission['emp_id'], month_year, permission['total_hours']))
        
        mysql.connection.commit()
        flash(f'Permission application {action} successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error processing permission application: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_permissions'))

@app.route('/admin/permission_types')
def manage_permission_types():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    cur.execute("SELECT * FROM permission_type ORDER BY name")
    permission_types = cur.fetchall()
    cur.close()
    
    return render_template('manage_permission_types.html',
                         permission_types=permission_types)

@app.route('/admin/permission_type/add', methods=['POST'])
def add_permission_type():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    name = request.form['name']
    description = request.form['description']
    max_hours = request.form.get('max_hours', 3.00)
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO permission_type (name, description, max_hours)
            VALUES (%s, %s, %s)
        """, (name, description, max_hours))
        mysql.connection.commit()
        flash('Permission type added successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error adding permission type: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_permission_types'))

@app.route('/admin/permission_type/edit/<int:permission_type_id>', methods=['POST'])
def edit_permission_type(permission_type_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    name = request.form['name']
    description = request.form['description']
    max_hours = request.form.get('max_hours', 3.00)
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            UPDATE permission_type 
            SET name = %s, description = %s, max_hours = %s
            WHERE permission_type_id = %s
        """, (name, description, max_hours, permission_type_id))
        mysql.connection.commit()
        flash('Permission type updated successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error updating permission type: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_permission_types'))

@app.route('/admin/permission_type/delete/<int:permission_type_id>', methods=['POST'])
def delete_permission_type(permission_type_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    try:
        # Check if permission type is used in applications
        cur.execute("""
            SELECT COUNT(*) as app_count 
            FROM permission_application 
            WHERE permission_type_id = %s
        """, (permission_type_id,))
        result = cur.fetchone()
        
        if result['app_count'] > 0:
            flash('Cannot delete permission type with existing applications', 'danger')
            return redirect(url_for('manage_permission_types'))
        
        cur.execute("DELETE FROM permission_type WHERE permission_type_id = %s", (permission_type_id,))
        mysql.connection.commit()
        flash('Permission type deleted successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error deleting permission type: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_permission_types'))

# Permission Reports
@app.route('/admin/reports/permissions')
def permission_report():
    if not is_admin_logged_in():
        return redirect(url_for('login'))

    try:
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        emp_id = request.args.get('emp_id', 'all')
        status = request.args.get('status', 'all')
        
        cur = mysql.connection.cursor()
        
        # Get all active employees for filter dropdown
        cur.execute("SELECT emp_id, first_name, last_name, employee_id FROM employee WHERE status = 'active'")
        employees = cur.fetchall()
        
        # Build query based on filters
        query = """
            SELECT 
                pa.*, 
                e.first_name, 
                e.last_name, 
                e.employee_id, 
                pt.name as permission_name,
                TIME(pa.start_time) as start_time,
                TIME(pa.end_time) as end_time,
                pa.total_hours,
                DATE(pa.date) as date_only,
                DATE_FORMAT(pa.applied_at, '%%Y-%%m-%%d %%H:%%i') as formatted_applied_at,
                DATE_FORMAT(pa.processed_at, '%%Y-%%m-%%d %%H:%%i') as formatted_processed_at
            FROM permission_application pa
            JOIN employee e ON pa.emp_id = e.emp_id
            JOIN permission_type pt ON pa.permission_type_id = pt.permission_type_id
            WHERE 1=1
        """
        params = []
        
        if start_date:
            query += " AND pa.date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND pa.date <= %s"
            params.append(end_date)
        
        if emp_id != 'all':
            query += " AND pa.emp_id = %s"
            params.append(emp_id)
        
        if status != 'all':
            query += " AND pa.status = %s"
            params.append(status)
        
        query += " ORDER BY pa.date DESC, pa.applied_at DESC"
        
        cur.execute(query, tuple(params))
        permissions = cur.fetchall()
        
        # Process permissions to format all time data properly
        processed_permissions = []
        for perm in permissions:
            perm = dict(perm)
            
            # Format total_hours
            if perm.get('total_hours'):
                if isinstance(perm['total_hours'], timedelta):
                    total_seconds = perm['total_hours'].total_seconds()
                    hours = int(total_seconds // 3600)
                    minutes = int((total_seconds % 3600) // 60)
                    perm['hours_display'] = f"{hours}h {minutes}m"
                elif isinstance(perm['total_hours'], (float, int)):
                    hours = int(perm['total_hours'])
                    minutes = int((perm['total_hours'] - hours) * 60)
                    perm['hours_display'] = f"{hours}h {minutes}m"
                else:
                    perm['hours_display'] = '-'
            else:
                perm['hours_display'] = '-'
                
            processed_permissions.append(perm)
        
        return render_template('permission_report.html',
                            permissions=processed_permissions,
                            employees=employees,
                            start_date=start_date,
                            end_date=end_date,
                            selected_emp_id=int(emp_id) if emp_id != 'all' else None,
                            status=status)
    
    except Exception as e:
        flash(f"Error generating report: {str(e)}", "danger")
        return redirect(url_for('admin_dashboard'))
    finally:
        cur.close()

@app.route('/admin/reports/export_permissions')
def export_permissions():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    try:
        start_date = request.args.get('start_date', '')
        end_date = request.args.get('end_date', '')
        emp_id = request.args.get('emp_id', None)
        status = request.args.get('status', 'all')
        
        cur = mysql.connection.cursor()
        
        # Build query based on filters
        query = """
            SELECT 
                e.employee_id, 
                e.first_name, 
                e.last_name, 
                pt.name as permission_name, 
                DATE(pa.date) as date,
                TIME(pa.start_time) as start_time,
                TIME(pa.end_time) as end_time,
                pa.total_hours,
                pa.reason, 
                pa.status, 
                pa.applied_at,
                pa.processed_at, 
                pa.comments
            FROM permission_application pa
            JOIN employee e ON pa.emp_id = e.emp_id
            JOIN permission_type pt ON pa.permission_type_id = pt.permission_type_id
            WHERE 1=1
        """
        params = []
        
        if start_date:
            query += " AND pa.date >= %s"
            params.append(start_date)
        if end_date:
            query += " AND pa.date <= %s"
            params.append(end_date)
        
        if emp_id and emp_id != 'all':
            query += " AND pa.emp_id = %s"
            params.append(emp_id)
        
        if status != 'all':
            query += " AND pa.status = %s"
            params.append(status)
        
        query += " ORDER BY pa.date DESC, pa.applied_at DESC"
        
        cur.execute(query, tuple(params))
        permissions = cur.fetchall()
        
        # Create CSV output
        output = StringIO()
        writer = csv.writer(output)
        
        # Write header
        writer.writerow([
            'Employee ID', 'First Name', 'Last Name', 'Permission Type',
            'Date', 'Start Time', 'End Time', 'Duration (hours)',
            'Reason', 'Status', 'Applied At', 'Processed At', 'Comments'
        ])
        
        # Write data rows
        for perm in permissions:
            # Format total_hours
            if perm['total_hours'] is not None:
                if isinstance(perm['total_hours'], timedelta):
                    total_hours = perm['total_hours'].total_seconds() / 3600
                    hours_display = f"{total_hours:.2f}"
                elif isinstance(perm['total_hours'], (float, int)):
                    hours_display = f"{perm['total_hours']:.2f}"
                else:
                    hours_display = ''
            else:
                hours_display = ''
            
            # Format time fields safely
            def format_time(value):
                if value is None:
                    return ''
                if isinstance(value, str):
                    return value
                if hasattr(value, 'strftime'):
                    return value.strftime('%H:%M')
                return str(value)
            
            def format_datetime(value):
                if value is None:
                    return ''
                if isinstance(value, str):
                    return value
                if hasattr(value, 'strftime'):
                    return value.strftime('%Y-%m-%d %H:%M')
                return str(value)
            
            writer.writerow([
                perm['employee_id'],
                perm['first_name'],
                perm['last_name'],
                perm['permission_name'],
                perm['date'].strftime('%Y-%m-%d') if perm['date'] else '',
                format_time(perm['start_time']),
                format_time(perm['end_time']),
                hours_display,
                perm['reason'] or '',
                perm['status'],
                format_datetime(perm['applied_at']),
                format_datetime(perm['processed_at']),
                perm['comments'] or ''
            ])
        
        output.seek(0)
        
        # Generate filename
        filename = f"permission_report_{start_date}_to_{end_date}.csv" if start_date and end_date else "permission_report_all.csv"
        
        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename={filename}'
        
        return response
    
    except Exception as e:
        flash(f"Error exporting report: {str(e)}", "danger")
        return redirect(url_for('permission_report'))
    finally:
        cur.close()


# Attendance Management
@app.route('/admin/attendance')
def manage_attendance():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    date_filter = request.args.get('date', date.today().strftime('%Y-%m-%d'))
    
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT a.*, e.first_name, e.last_name, e.employee_id 
        FROM attendance a 
        JOIN employee e ON a.emp_id = e.emp_id 
        WHERE DATE(a.check_in) = %s 
        ORDER BY a.check_in
    """, (date_filter,))
    attendance = cur.fetchall()
    
    cur.execute("""
        SELECT e.emp_id, e.first_name, e.last_name, e.employee_id 
        FROM employee e 
        WHERE e.status = 'active' AND e.emp_id NOT IN (
            SELECT emp_id FROM attendance WHERE DATE(check_in) = %s
        )
    """, (date_filter,))
    absent_employees = cur.fetchall()
    
    cur.close()
    
    return render_template('manage_attendance.html', 
                         attendance=attendance,
                         absent_employees=absent_employees,
                         date_filter=date_filter)

@app.route('/admin/attendance/manual_entry', methods=['POST'])
def manual_attendance_entry():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    emp_id = request.form['emp_id']
    date_str = request.form['date']
    check_in = request.form['check_in']
    check_out = request.form.get('check_out', None)
    
    check_in_datetime = f"{date_str} {check_in}" 
    check_out_datetime = f"{date_str} {check_out}" if check_out else None
    
    total_hours = calculate_work_hours(check_in_datetime, check_out_datetime) if check_out else None
    
    cur = mysql.connection.cursor()
    try:
        cur.execute("""
            INSERT INTO attendance (emp_id, check_in, check_out, total_hours, status) 
            VALUES (%s, %s, %s, %s, 'present')
        """, (emp_id, check_in_datetime, check_out_datetime, total_hours))
        mysql.connection.commit()
        flash('Attendance recorded successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error recording attendance: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('manage_attendance', date=date_str))

@app.route('/admin/attendance/update/<int:att_id>', methods=['POST'])
def update_attendance(att_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    check_in = request.form['check_in']
    check_out = request.form.get('check_out', None)
    
    total_hours = calculate_work_hours(check_in, check_out) if check_out else None
    
    cur = mysql.connection.cursor()
    try:
        if check_out:
            cur.execute("""
                UPDATE attendance 
                SET check_in = %s, check_out = %s, total_hours = %s 
                WHERE att_id = %s
            """, (check_in, check_out, total_hours, att_id))
        else:
            cur.execute("""
                UPDATE attendance 
                SET check_in = %s, check_out = NULL, total_hours = NULL 
                WHERE att_id = %s
            """, (check_in, att_id))
        
        mysql.connection.commit()
        flash('Attendance updated successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error updating attendance: {str(e)}', 'danger')
    finally:
        cur.close()
    
    date_str = check_in.split()[0]
    return redirect(url_for('manage_attendance', date=date_str))

@app.route('/admin/attendance/delete/<int:att_id>', methods=['POST'])
def delete_attendance(att_id):
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    cur = mysql.connection.cursor()
    try:
        # Get date before deleting for redirect
        cur.execute("SELECT DATE(check_in) as date FROM attendance WHERE att_id = %s", (att_id,))
        date_str = cur.fetchone()['date']
        
        cur.execute("DELETE FROM attendance WHERE att_id = %s", (att_id,))
        mysql.connection.commit()
        flash('Attendance record deleted successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error deleting attendance record: {str(e)}', 'danger')
        return redirect(url_for('manage_attendance'))
    finally:
        cur.close()
    
    return redirect(url_for('manage_attendance', date=date_str))

# Reports
@app.route('/admin/reports/attendance')
def attendance_report():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    # Get filter parameters with defaults
    start_date = request.args.get('start_date', (date.today() - timedelta(days=30)).strftime('%Y-%m-%d'))
    end_date = request.args.get('end_date', date.today().strftime('%Y-%m-%d'))
    emp_id = request.args.get('emp_id', None)
    
    cur = mysql.connection.cursor()
    
    # Get all active employees for filter dropdown
    cur.execute("SELECT emp_id, first_name, last_name, employee_id FROM employee WHERE status = 'active'")
    employees = cur.fetchall()
    
    # Build base query
    query = """
        SELECT 
            a.att_id,
            a.emp_id,
            e.employee_id,
            e.first_name,
            e.last_name,
            DATE(a.check_in) as date,
            TIME(a.check_in) as check_in_time,
            TIME(a.check_out) as check_out_time,
            a.total_hours,
            a.status
        FROM attendance a
        JOIN employee e ON a.emp_id = e.emp_id
        WHERE DATE(a.check_in) BETWEEN %s AND %s
    """
    params = [start_date, end_date]
    
    # Add employee filter if specified
    if emp_id and emp_id != 'all':
        query += " AND a.emp_id = %s"
        params.append(emp_id)
    
    query += " ORDER BY date, e.first_name, e.last_name"
    
    # Execute query
    cur.execute(query, tuple(params))
    attendance_records = cur.fetchall()
    cur.close()
    
    # Calculate summary statistics
    total_days = len(attendance_records)
    present_days = sum(1 for r in attendance_records if r['check_out_time'] is not None)
    
    # Calculate total hours (only for complete records)
    total_hours = 0.0
    for record in attendance_records:
        if record['total_hours'] is not None:
            try:
                total_hours += float(record['total_hours'])
            except (TypeError, ValueError):
                pass
    
    avg_hours = total_hours / present_days if present_days > 0 else 0.0
    
    return render_template('attendance_report.html',
                         attendance=attendance_records,
                         employees=employees,
                         start_date=start_date,
                         end_date=end_date,
                         selected_emp_id=emp_id,
                         total_days=total_days,
                         present_days=present_days,
                         total_hours=round(total_hours, 2),
                         avg_hours=round(avg_hours, 2))


@app.route('/admin/reports/export_leave')
def export_leave():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    # Get filter parameters
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    emp_id = request.args.get('emp_id', None)
    
    cur = mysql.connection.cursor()
    
    # Build query based on filters (same as leave_report)
    query = """
        SELECT e.employee_id, e.first_name, e.last_name, 
               lt.leave_name, la.start_date, la.end_date, 
               DATEDIFF(la.end_date, la.start_date) + 1 as days,
               la.reason, la.status, la.applied_on,
               la.processed_on, la.comments
        FROM leave_application la 
        JOIN employee e ON la.emp_id = e.emp_id 
        JOIN leave_type lt ON la.leave_type_id = lt.leave_type_id 
        WHERE 1=1
    """
    params = []
    
    if start_date:
        query += " AND la.start_date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND la.end_date <= %s"
        params.append(end_date)
    
    if emp_id:
        query += " AND la.emp_id = %s"
        params.append(emp_id)
    
    query += " ORDER BY la.start_date DESC"
    
    cur.execute(query, tuple(params))
    leaves = cur.fetchall()
    cur.close()
    
    # Create CSV content
    csv_data = []
    # Add header
    csv_data.append("Employee ID,First Name,Last Name,Leave Type,Start Date,End Date,Days,Reason,Status,Applied On,Processed On,Comments\n")
    
    # Add rows
    for leave in leaves:
        row = [
            str(leave['employee_id']),
            str(leave['first_name']),
            str(leave['last_name']),
            str(leave['leave_name']),
            leave['start_date'].strftime('%Y-%m-%d') if leave['start_date'] else '',
            leave['end_date'].strftime('%Y-%m-%d') if leave['end_date'] else '',
            str(leave['days']),
            f'"{str(leave["reason"])}"',  # Wrap in quotes to handle commas
            str(leave['status']),
            leave['applied_on'].strftime('%Y-%m-%d %H:%M:%S') if leave['applied_on'] else '',
            leave['processed_on'].strftime('%Y-%m-%d %H:%M:%S') if leave['processed_on'] else '',
            f'"{str(leave["comments"])}"' if leave['comments'] else ''
        ]
        csv_data.append(','.join(row) + '\n')
    
    # Convert to bytes
    output = BytesIO()
    output.write(''.join(csv_data).encode('utf-8'))
    output.seek(0)
    
    # Generate filename
    filename = f"leave_report_{start_date}_to_{end_date}.csv" if start_date and end_date else "leave_report_all.csv"
    
    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )



@app.route('/admin/reports/leave')
def leave_report():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    emp_id = request.args.get('emp_id', None)
    
    cur = mysql.connection.cursor()
    
    # Get all active employees for filter dropdown
    cur.execute("SELECT emp_id, first_name, last_name, employee_id FROM employee WHERE status = 'active'")
    employees = cur.fetchall()
    
    # Build query based on filters
    query = """
        SELECT la.*, e.first_name, e.last_name, e.employee_id, lt.leave_name 
        FROM leave_application la 
        JOIN employee e ON la.emp_id = e.emp_id 
        JOIN leave_type lt ON la.leave_type_id = lt.leave_type_id 
        WHERE 1=1
    """
    params = []
    
    # Add date filters if provided
    if start_date:
        query += " AND la.start_date >= %s"
        params.append(start_date)
    if end_date:
        query += " AND la.end_date <= %s"
        params.append(end_date)
    
    if emp_id:
        query += " AND la.emp_id = %s"
        params.append(emp_id)
    
    query += " ORDER BY la.start_date DESC"
    
    cur.execute(query, tuple(params))
    leaves = cur.fetchall()
    
    cur.close()
    
    return render_template('leave_report.html', 
                         leaves=leaves,
                         employees=employees,
                         start_date=start_date,
                         end_date=end_date,
                         selected_emp_id=int(emp_id) if emp_id else None)

@app.route('/admin/reports/export_attendance')
def export_attendance():
    if not is_admin_logged_in():
        return redirect(url_for('login'))
    
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    emp_id = request.args.get('emp_id', None)
    
    cur = mysql.connection.cursor()
    
    query = """
        SELECT e.employee_id, e.first_name, e.last_name, 
               a.check_in, a.check_out, a.total_hours,
               DATE(a.check_in) as date 
        FROM attendance a 
        JOIN employee e ON a.emp_id = e.emp_id 
        WHERE 1=1    
    """
    params = []
    
    if start_date:
        query += " AND DATE(a.check_in) >= %s"
        params.append(start_date)
    if end_date:
        query += " AND DATE(a.check_in) <= %s"
        params.append(end_date)

    if emp_id:
        query += " AND a.emp_id = %s"
        params.append(emp_id)
    
    query += " ORDER BY e.employee_id, a.check_in"
    
    cur.execute(query, tuple(params))
    attendance = cur.fetchall()
    cur.close()
    
    csv_data = []
    csv_data.append("Employee ID,First Name,Last Name,Date,Check In,Check Out,Total Hours\n")
    
    for record in attendance:
        date_str = record['date'].strftime('%Y-%m-%d') if record['date'] else ''
        check_in_time = record['check_in'].strftime('%H:%M:%S') if record['check_in'] else ''
        check_out_time = record['check_out'].strftime('%H:%M:%S') if record['check_out'] else ''
        total_hours = f"{float(record['total_hours']):.2f}" if record['total_hours'] is not None else ''
        
        row = [
            str(record['employee_id']),
            str(record['first_name']),
            str(record['last_name']),
            date_str,
            check_in_time,
            check_out_time,
            total_hours
        ]
        csv_data.append(','.join(row) + '\n')

    output = BytesIO()
    output.write(''.join(csv_data).encode('utf-8'))
    output.seek(0)

    filename = f"attendance_report_{start_date}_to_{end_date}.csv" if start_date and end_date else "attendance_report.csv"

    return send_file(
        output,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


# Employee Dashboard
@app.route('/employee/dashboard')
def employee_dashboard():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    employee = get_employee_details(emp_id)
    
    cur = mysql.connection.cursor()
    
    # Get today's attendance
    today = date.today().strftime('%Y-%m-%d')
    cur.execute("""
        SELECT * FROM attendance 
        WHERE emp_id = %s AND DATE(check_in) = %s
    """, (emp_id, today))
    today_attendance = cur.fetchone()

    # Check if previous day wasn't checked out
    yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
    cur.execute("""
        SELECT * FROM attendance 
        WHERE emp_id = %s AND DATE(check_in) = %s AND check_out IS NULL
    """, (emp_id, yesterday))
    has_pending_checkout = cur.fetchone() is not None
    
    # Get leave balance
    cur.execute("""
        SELECT lt.leave_name, lb.remaining_days, lt.max_days 
        FROM leave_balance lb 
        JOIN leave_type lt ON lb.leave_type_id = lt.leave_type_id 
        WHERE lb.emp_id = %s
    """, (emp_id,))
    leave_balance = cur.fetchall()
    
    # Get recent attendance (last 5 days)
    cur.execute("""
        SELECT DATE(check_in) as date, 
               TIME(check_in) as check_in_time, 
               TIME(check_out) as check_out_time, 
               total_hours 
        FROM attendance 
        WHERE emp_id = %s 
        ORDER BY date DESC 
        LIMIT 5
    """, (emp_id,))
    recent_attendance = cur.fetchall()
    
    # Get pending leave applications
    cur.execute("""
        SELECT la.*, lt.leave_name 
        FROM leave_application la 
        JOIN leave_type lt ON la.leave_type_id = lt.leave_type_id 
        WHERE la.emp_id = %s AND la.status = 'pending' 
        ORDER BY la.applied_on DESC
    """, (emp_id,))
    pending_leaves = cur.fetchall()
    
    cur.close()
    
    return render_template('employee_dashboard.html', 
                         employee=employee,
                         today_attendance=today_attendance,
                         has_pending_checkout=has_pending_checkout,
                         leave_balance=leave_balance,
                         recent_attendance=recent_attendance,
                         pending_leaves=pending_leaves)

# Employee Attendance
@app.route('/employee/attendance')
def employee_attendance():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    month = request.args.get('month', date.today().strftime('%Y-%m'))
    
    cur = mysql.connection.cursor()
    cur.execute("""
        SELECT DATE(check_in) as date, 
               TIME(check_in) as check_in, 
               TIME(check_out) as check_out, 
               total_hours 
        FROM attendance 
        WHERE emp_id = %s AND DATE_FORMAT(check_in, '%%Y-%%m') = %s 
        ORDER BY date
    """, (emp_id, month))
    attendance = cur.fetchall()
    
    # Calculate summary
    total_days = len(attendance)
    total_hours = sum(record['total_hours'] or 0 for record in attendance)
    avg_hours = total_hours / total_days if total_days > 0 else 0
    
    cur.close()
    
    return render_template('employee_attendance.html', 
                         attendance=attendance,
                         month=month,
                         total_days=total_days,
                         total_hours=round(total_hours, 2),
                         avg_hours=round(avg_hours, 2))

@app.route('/employee/check_in', methods=['POST'])
def employee_check_in():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    current_time = get_current_datetime()
    today = date.today().strftime('%Y-%m-%d')
    
    cur = mysql.connection.cursor()
    try:
        # Check if already checked in today
        cur.execute("""
            SELECT * FROM attendance 
            WHERE emp_id = %s AND DATE(check_in) = %s
        """, (emp_id, today))
        existing = cur.fetchone()
        
        if existing:
            flash('You have already checked in today and not checked out yet', 'warning')
            return redirect(url_for('employee_dashboard'))
        
        # Check if previous day wasn't checked out
        yesterday = (date.today() - timedelta(days=1)).strftime('%Y-%m-%d')
        cur.execute("""
            SELECT * FROM attendance 
            WHERE emp_id = %s AND DATE(check_in) = %s
        """, (emp_id, yesterday))
        previous_day = cur.fetchone()
        
        if previous_day:
            flash('You cannot check in today because you were not checked out yesterday. Please contact admin.', 'danger')
            return redirect(url_for('employee_dashboard'))
        
        # Record check-in with status
        cur.execute("""
            INSERT INTO attendance (emp_id, check_in, status) 
            VALUES (%s, %s, 'present')
        """, (emp_id, current_time))
        
        mysql.connection.commit()
        flash('Check-in recorded successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error recording check-in: {str(e)}', 'danger')
        app.logger.error(f"Error in check_in: {str(e)}")  # Add logging
    finally:
        cur.close()
    
    return redirect(url_for('employee_dashboard'))


@app.route('/employee/check_out', methods=['POST'])
def employee_check_out():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    current_time = get_current_datetime()
    
    cur = mysql.connection.cursor()
    try:
        # Get today's check-in
        today = date.today().strftime('%Y-%m-%d')
        cur.execute("""
            SELECT * FROM attendance 
            WHERE emp_id = %s AND DATE(check_in) = %s AND check_out IS NULL
        """, (emp_id, today))
        attendance = cur.fetchone()
        
        if not attendance:
            flash('You need to check in first', 'warning')
            return redirect(url_for('employee_dashboard'))
        
        # Calculate work hours
        check_in = attendance['check_in'].strftime('%Y-%m-%d %H:%M:%S')
        total_hours = calculate_work_hours(check_in, current_time)
        
        # Record check-out
        cur.execute("""
            UPDATE attendance 
            SET check_out = %s, total_hours = %s 
            WHERE att_id = %s
        """, (current_time, total_hours, attendance['att_id']))
        mysql.connection.commit()
        flash('Check-out recorded successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error recording check-out: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('employee_dashboard'))

# Employee Leave Management
@app.route('/employee/leaves')
def employee_leaves():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    status = request.args.get('status', 'all')
    
    cur = mysql.connection.cursor()
    
    # Get leave balance
    cur.execute("""
        SELECT lt.leave_name, lb.remaining_days, lt.max_days 
        FROM leave_balance lb 
        JOIN leave_type lt ON lb.leave_type_id = lt.leave_type_id 
        WHERE lb.emp_id = %s
    """, (emp_id,))
    leave_balance = cur.fetchall()
    
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
    leaves = cur.fetchall()
    
    # Get leave types for new application form
    cur.execute("SELECT * FROM leave_type")
    leave_types = cur.fetchall()
    
    cur.close()
    
    return render_template('employee_leaves.html', 
                         leave_balance=leave_balance,
                         leaves=leaves,
                         leave_types=leave_types,
                         status=status)

@app.route('/employee/leave/apply', methods=['POST'])
def apply_leave():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    leave_type_id = request.form['leave_type_id']
    start_date = request.form['start_date']
    end_date = request.form['end_date']
    leave_duration = request.form['leave_duration']  # 'full_day', 'first_half', 'second_half'
    reason = request.form['reason']
    
    # Convert to date objects
    start_dt = datetime.strptime(start_date, '%Y-%m-%d').date()
    end_dt = datetime.strptime(end_date, '%Y-%m-%d').date()
    
    # Validate dates based on leave duration
    if not validate_leave_dates(start_dt, end_dt, leave_duration):
        if leave_duration == 'full_day':
            flash('End date must be after or same as start date for full day leave', 'danger')
        else:
            flash('Start and end date must be same for half-day leave', 'danger')
        return redirect(url_for('employee_leaves'))
    
    # Calculate days
    days = calculate_leave_days(start_dt, end_dt, leave_duration)
    
    cur = mysql.connection.cursor()
    try:
        # Check leave balance and if half-day is allowed
        cur.execute("""
            SELECT lt.max_days, lt.half_day_allowed, lb.remaining_days 
            FROM leave_balance lb 
            JOIN leave_type lt ON lb.leave_type_id = lt.leave_type_id 
            WHERE lb.emp_id = %s AND lb.leave_type_id = %s
        """, (emp_id, leave_type_id))
        result = cur.fetchone()
        
        if not result:
            flash('Leave type not found', 'danger')
            return redirect(url_for('employee_leaves'))
            
        if leave_duration != 'full_day' and not result['half_day_allowed']:
            flash('Half-day leave is not allowed for this leave type', 'danger')
            return redirect(url_for('employee_leaves'))
            
        if result['remaining_days'] < days:
            flash(f'Not enough leave balance. You have {result["remaining_days"]} days remaining but requested {days} days.', 'danger')
            return redirect(url_for('employee_leaves'))
        
        # Check for overlapping leave applications - simplified query
        cur.execute("""
            SELECT COUNT(*) as overlap_count 
            FROM leave_application 
            WHERE emp_id = %s 
            AND status = 'approved'
            AND (
                (%s BETWEEN start_date AND end_date)
                OR (%s BETWEEN start_date AND end_date)
                OR (start_date BETWEEN %s AND %s)
                OR (end_date BETWEEN %s AND %s)
            )
        """, (
            emp_id,
            start_date, end_date,
            start_date, end_date,
            start_date, end_date
        ))
        overlap = cur.fetchone()['overlap_count'] > 0
        
        if overlap:
            flash('You already have an approved leave during this period', 'danger')
            return redirect(url_for('employee_leaves'))
 
        # Apply leave
        cur.execute("""
            INSERT INTO leave_application 
            (emp_id, leave_type_id, start_date, end_date, leave_duration, reason) 
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (emp_id, leave_type_id, start_date, end_date, leave_duration, reason))
        
        mysql.connection.commit()
        flash('Leave application submitted successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error applying for leave: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('employee_leaves'))

@app.route('/employee/leave/cancel/<int:leave_id>', methods=['POST'])
def cancel_leave(leave_id):
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    
    cur = mysql.connection.cursor()
    try:
        # Check if leave can be cancelled (status is pending)
        cur.execute("""
            SELECT status FROM leave_application 
            WHERE leave_id = %s AND emp_id = %s
        """, (leave_id, emp_id))
        leave = cur.fetchone()
        
        if not leave:
            flash('Leave application not found', 'danger')
            return redirect(url_for('employee_leaves'))
        
        if leave['status'] != 'pending':
            flash('Only pending leaves can be cancelled', 'danger')
            return redirect(url_for('employee_leaves'))
        
        # Delete leave application
        cur.execute("""
            DELETE FROM leave_application 
            WHERE leave_id = %s
        """, (leave_id,))
        mysql.connection.commit()
        flash('Leave application cancelled successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error cancelling leave: {str(e)}', 'danger')
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
    
    return render_template('employee_profile.html', employee=employee)

@app.route('/employee/change_password', methods=['POST'])
def change_employee_password():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    current_password = request.form['current_password'].encode('utf-8')
    new_password = request.form['new_password']
    
    if len(new_password) < 8:
        flash('Password must be at least 8 characters long', 'danger')
        return redirect(url_for('employee_profile'))
    
    cur = mysql.connection.cursor()
    try:
        # Verify current password
        cur.execute("SELECT password_hash FROM employee WHERE emp_id = %s", (emp_id,))
        employee = cur.fetchone()
        
        if not employee or not bcrypt.checkpw(current_password, employee['password_hash'].encode('utf-8')):
            flash('Current password is incorrect', 'danger')
            return redirect(url_for('employee_profile'))
        
        # Update password
        hashed_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute("""
            UPDATE employee 
            SET password_hash = %s 
            WHERE emp_id = %s
        """, (hashed_password, emp_id))
        mysql.connection.commit()
        flash('Password changed successfully!', 'success')
    except Exception as e:
        mysql.connection.rollback()
        flash(f'Error changing password: {str(e)}', 'danger')
    finally:
        cur.close()
    
    return redirect(url_for('employee_profile'))

@app.route('/employee/update_profile_pic', methods=['POST'])
def update_employee_profile_pic():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    
    if 'profile_pic' not in request.files:
        flash('No file selected', 'danger')
        return redirect(url_for('employee_profile'))
    
    file = request.files['profile_pic']
    if file.filename == '':
        flash('No file selected', 'danger')
        return redirect(url_for('employee_profile'))
    
    if file and allowed_file(file.filename):
        # Get employee details to use the employee_id in filename
        cur = mysql.connection.cursor()
        cur.execute("SELECT employee_id FROM employee WHERE emp_id = %s", (emp_id,))
        employee = cur.fetchone()
        cur.close()
        
        if not employee:
            flash('Employee not found', 'danger')
            return redirect(url_for('employee_profile'))
        
        filename = secure_filename(f"{employee['employee_id']}_{file.filename}")
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        
        # Delete old profile pic if exists
        cur = mysql.connection.cursor()
        cur.execute("SELECT profile_pic FROM employee WHERE emp_id = %s", (emp_id,))
        old_pic = cur.fetchone()['profile_pic']
        
        if old_pic and os.path.exists(os.path.join(app.config['UPLOAD_FOLDER'], old_pic)):
            try:
                os.remove(os.path.join(app.config['UPLOAD_FOLDER'], old_pic))
            except:
                pass
        
        # Save new file
        file.save(filepath)
        
        # Update database
        try:
            cur.execute("""
                UPDATE employee 
                SET profile_pic = %s 
                WHERE emp_id = %s
            """, (filename, emp_id))
            mysql.connection.commit()
            flash('Profile picture updated successfully!', 'success')
        except Exception as e:
            mysql.connection.rollback()
            flash(f'Error updating profile picture: {str(e)}', 'danger')
        finally:
            cur.close()
    else:
        flash('Allowed file types are: png, jpg, jpeg, gif', 'danger')
    
    return redirect(url_for('employee_profile'))


# Calendar View
@app.route('/employee/calendar')
def employee_calendar():
    if not is_employee_logged_in():
        return redirect(url_for('login'))
    
    emp_id = session['emp_id']
    year = request.args.get('year', date.today().year)
    month = request.args.get('month', date.today().month)
    
    cur = mysql.connection.cursor()
    
    # Get attendance for the month
    cur.execute("""
        SELECT DATE(check_in) as date, 
               TIME(check_in) as check_in, 
               TIME(check_out) as check_out, 
               total_hours 
        FROM attendance 
        WHERE emp_id = %s AND YEAR(check_in) = %s AND MONTH(check_in) = %s 
        ORDER BY date
    """, (emp_id, year, month))
    attendance = cur.fetchall()
    
    # Get leaves for the month
    cur.execute("""
        SELECT start_date, end_date, status 
        FROM leave_application 
        WHERE emp_id = %s AND (
            (YEAR(start_date) = %s AND MONTH(start_date) = %s) OR
            (YEAR(end_date) = %s AND MONTH(end_date) = %s)
        )
    """, (emp_id, year, month, year, month))
    leaves = cur.fetchall()
    
    cur.close()
    
    # Create calendar data structure
    calendar_data = []
    
    # Get first and last day of month
    first_day = date(int(year), int(month), 1)
    last_day = date(int(year), int(month) + 1, 1) - timedelta(days=1) if int(month) < 12 else date(int(year) + 1, 1, 1) - timedelta(days=1)
    
    # Get days from previous month to show
    prev_month_days = (first_day.weekday() + 1) % 7  # +1 for Monday as first day
    
    # Add days from previous month
    prev_month_last_day = first_day - timedelta(days=1)
    for day in range(prev_month_last_day.day - prev_month_days + 1, prev_month_last_day.day + 1):
        calendar_data.append({
            'day': day,
            'month': 'prev',
            'attendance': None,
            'leave': None
        })
    
    # Add days from current month
    for day in range(1, last_day.day + 1):
        current_date = date(int(year), int(month), day)
        date_str = current_date.strftime('%Y-%m-%d')
        
        # Find attendance for this day
        day_attendance = next((a for a in attendance if a['date'] == current_date), None)
        
        # Find leave for this day
        day_leave = None
        for leave in leaves:
            if leave['start_date'] <= current_date <= leave['end_date']:
                day_leave = leave
                break
        
        calendar_data.append({
            'day': day,
            'month': 'current',
            'attendance': day_attendance,
            'leave': day_leave
        })
    
    # Add days from next month to complete the grid
    next_month_days = (6 - last_day.weekday()) % 7  # 6 for Sunday as last day
    for day in range(1, next_month_days + 1):
        calendar_data.append({
            'day': day,
            'month': 'next',
            'attendance': None,
            'leave': None
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
    
    cur = mysql.connection.cursor()
    
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
    app.run(host='0.0.0.0', port=5001, debug=True)
