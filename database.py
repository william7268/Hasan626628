import sqlite3
import logging
import datetime

logger = logging.getLogger(__name__)

# اسم ملف قاعدة البيانات
DB_NAME = 'hasan_bot.db'

def connect_db():
    """يتصل بقاعدة البيانات ويرجع كائن الاتصال."""
    return sqlite3.connect(DB_NAME)

def initialize_db():
    """يهيئ قاعدة البيانات وينشئ الجداول إذا لم تكن موجودة."""
    conn = connect_db()
    cursor = conn.cursor()

    # جدول المستخدمين
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            role TEXT DEFAULT 'user',
            referred_by INTEGER,
            referral_count INTEGER DEFAULT 0
        )
    ''')

    # جدول الإيميلات الأمريكية
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS american_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL,
            status TEXT DEFAULT 'available',
            sold_to_user_id INTEGER,
            sold_at TEXT
        )
    ''')

    # جدول الإيميلات التي أرسلها المستخدمون للمراجعة (سواء أمريكية بعد الـ 24 ساعة أو عشوائية)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS submitted_emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_user_id INTEGER NOT NULL,
            email TEXT NOT NULL,
            password TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            rejection_reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # جدول طلبات السحب
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS withdrawal_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount INTEGER NOT NULL,
            method TEXT NOT NULL,
            phone_number TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            rejection_reason TEXT,
            requested_at TEXT DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT
        )
    ''')

    conn.commit()
    conn.close()
    logger.info("تم تهيئة قاعدة البيانات والجداول بنجاح.")

# دوال التعامل مع قاعدة البيانات
def add_user(user_id, role='user', referred_by=None):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, role, referred_by) VALUES (?, ?, ?)",
                       (user_id, role, referred_by))
        conn.commit()
        logger.info(f"تم إضافة/تحديث المستخدم {user_id} بالدور {role}.")
    except sqlite3.Error as e:
        logger.error(f"خطأ في إضافة المستخدم {user_id}: {e}")
    finally:
        conn.close()

def get_user(user_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, balance, role, referred_by, referral_count FROM users WHERE user_id = ?", (user_id,))
    user_data = cursor.fetchone()
    conn.close()
    if user_data:
        return {
            "user_id": user_data[0],
            "balance": user_data[1],
            "role": user_data[2],
            "referred_by": user_data[3],
            "referral_count": user_data[4]
        }
    return None

def update_user_balance(user_id, amount):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        logger.info(f"تم تحديث رصيد المستخدم {user_id} بـ {amount}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"خطأ في تحديث رصيد المستخدم {user_id}: {e}")
        return False
    finally:
        conn.close()

def add_american_email(email, password):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO american_emails (email, password) VALUES (?, ?)", (email, password))
        conn.commit()
        logger.info(f"تم إضافة الإيميل الأمريكي: {email}.")
        return True
    except sqlite3.IntegrityError: # لو الإيميل موجود مسبقا (UNIQUE)
        logger.warning(f"الإيميل {email} موجود مسبقاً في قاعدة البيانات.")
        return False
    except sqlite3.Error as e:
        logger.error(f"خطأ في إضافة الإيميل الأمريكي {email}: {e}")
        return False
    finally:
        conn.close()

def get_available_american_emails(count):
    conn = connect_db()
    cursor = conn.cursor()
    # نختار الإيميلات المتاحة فقط
    cursor.execute("SELECT id, email, password FROM american_emails WHERE status = 'available' LIMIT ?", (count,))
    emails = cursor.fetchall()
    conn.close()
    # نرجعها كقائمة من القواميس لسهولة التعامل
    return [{"id": row[0], "email": row[1], "password": row[2]} for row in emails]

def mark_emails_as_sold(email_ids, user_id):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        now = datetime.datetime.now().isoformat() # الوقت الحالي بصيغة ISO
        # نحدّث حالة الإيميلات المحددة ونسجل مين اللي اشتراها ومتى
        for email_id in email_ids:
            cursor.execute(
                "UPDATE american_emails SET status = 'sold', sold_to_user_id = ?, sold_at = ? WHERE id = ?",
                (user_id, now, email_id)
            )
        conn.commit()
        logger.info(f"تم تحديث حالة الإيميلات {email_ids} كـ 'مباع' للمستخدم {user_id}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"خطأ في تحديث حالة الإيميلات كـ 'مباع': {e}")
        return False
    finally:
        conn.close()

def delete_american_email(email):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM american_emails WHERE email = ?", (email,))
        conn.commit()
        if cursor.rowcount > 0: # إذا تم حذف سطر واحد على الأقل
            logger.info(f"تم حذف الإيميل الأمريكي: {email}.")
            return True
        else:
            logger.warning(f"لم يتم العثور على الإيميل {email} للحذف.")
            return False
    except sqlite3.Error as e:
        logger.error(f"خطأ في حذف الإيميل الأمريكي {email}: {e}")
        return False
    finally:
        conn.close()

def get_american_emails_counts():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT status, COUNT(*) FROM american_emails GROUP BY status")
    counts = cursor.fetchall()
    conn.close()

    status_counts = {row[0]: row[1] for row in counts}
    return {
        'available': status_counts.get('available', 0),
        'sold': status_counts.get('sold', 0),
        'total': sum(status_counts.values())
    }

def get_all_available_american_emails_for_admin():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT email, password FROM american_emails WHERE status = 'available'")
    emails = cursor.fetchall()
    conn.close()
    return [{"email": row[0], "password": row[1]} for row in emails]

def add_submitted_email(seller_user_id, email, password, email_type):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO submitted_emails (seller_user_id, email, password, type, status) VALUES (?, ?, ?, ?, ?)",
            (seller_user_id, email, password, email_type, 'pending')
        )
        conn.commit()
        logger.info(f"تم إضافة الإيميل المرسل للمراجعة: {email} من المستخدم {seller_user_id} نوع {email_type}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"خطأ في إضافة الإيميل المرسل للمراجعة {email}: {e}")
        return False
    finally:
        conn.close()

def get_pending_submitted_emails():
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, seller_user_id, email, password, type, created_at FROM submitted_emails WHERE status = 'pending'")
    emails = cursor.fetchall()
    conn.close()
    return [{
        "id": row[0],
        "seller_user_id": row[1],
        "email": row[2],
        "password": row[3],
        "type": row[4],
        "created_at": row[5]
    } for row in emails]

def update_submitted_email_status(email_id, status, rejection_reason=None):
    conn = connect_db()
    cursor = conn.cursor()
    try:
        if rejection_reason:
            cursor.execute("UPDATE submitted_emails SET status = ?, rejection_reason = ? WHERE id = ?",
                           (status, rejection_reason, email_id))
        else:
            cursor.execute("UPDATE submitted_emails SET status = ? WHERE id = ?",
                           (status, email_id))
        conn.commit()
        logger.info(f"تم تحديث حالة الإيميل المرسل {email_id} إلى {status}.")
        return True
    except sqlite3.Error as e:
        logger.error(f"خطأ في تحديث حالة الإيميل المرسل {email_id}: {e}")
        return False
    finally:
        conn.close()

def get_submitted_email_by_id(email_id):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, seller_user_id, email, password, type, status, created_at FROM submitted_emails WHERE id = ?", (email_id,))
    email_data = cursor.fetchone()
    conn.close()
    if email_data:
        return {
            "id": email_data[0],
            "seller_user_id": email_data[1],
            "email": email_data[2],
            "password": email_data[3],
            "type": email_data[4],
            "status": email_data[5],
            "created_at": email_data[6]
        }
    return None

# ## هنا دالة get_last_sold_emails_to_user اللي كانت مفقودة ##
def get_last_sold_emails_to_user(user_id, count=5):
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT email, password FROM american_emails WHERE sold_to_user_id = ? ORDER BY sold_at DESC LIMIT ?",
        (user_id, count)
    )
    emails = cursor.fetchall()
    conn.close()
    return [{"email": row[0], "password": row[1]} for row in emails]


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    initialize_db()
