from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
    CallbackQueryHandler
)
import logging
from config import BOT_TOKEN, DEVELOPER_CHAT_ID, CHANNEL_LINK
from database import (
    initialize_db, add_user, get_user, update_user_balance,
    add_american_email, get_available_american_emails, mark_emails_as_sold,
    delete_american_email, get_american_emails_counts, get_all_available_american_emails_for_admin,
    add_submitted_email, get_pending_submitted_emails, update_submitted_email_status, get_submitted_email_by_id,
    get_last_sold_emails_to_user,
    connect_db
)

# إعدادات التسجيل (Logging)
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# حالات ConversationHandler لإضافة الإيميلات الأمريكية (للمشرف)
ADD_AMERICAN_EMAILS_STATE = 1
    
# حالات ConversationHandler لبيع الإيميلات (للمستخدم العادي)
SELL_EMAILS_CHOICE = 2
SELL_AMERICAN_COUNT = 3
SELL_AMERICAN_POST_RECEIVE_CHOICE = 11 # ## جديد ## حالة بعد استلام الايميلات الامريكية

# حالات ConversationHandler لإدارة الإيميلات الأمريكية (للمشرف)
MANAGE_AMERICAN_EMAILS_CHOICE = 4
DELETE_AMERICAN_EMAIL_STATE = 5

# حالات ConversationHandler لإرسال الإيميلات للمراجعة (للمستخدم العادي)
SUBMIT_EMAILS_STATE = 6
SUBMIT_EMAILS_TYPE_CHOICE = 7

# حالات ConversationHandler لمراجعة إيميلات البيع (للمشرف)
REVIEW_EMAIL_CHOICE = 8
REJECT_EMAIL_REASON = 9
ACCEPT_EMAIL_BALANCE_ADJUST = 10


# دوال لوحات المفاتيح (Keyboards)
def get_user_keyboard():
    """لوحة مفاتيح المستخدم العادي (لمى)."""
    keyboard = [
        [KeyboardButton("بيع إيميلات"), KeyboardButton("إرسال الإيميلات")],
        [KeyboardButton("الرصيد"), KeyboardButton("سحب الأرباح")],
        [KeyboardButton("إحصائيات البوت")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

def get_admin_keyboard():
    """لوحة مفاتيح المشرف (علي)."""
    keyboard = [
        [KeyboardButton("إضافة إيميلات أمريكية"), KeyboardButton("إدارة الإيميلات الأمريكية")],
        [KeyboardButton("مراجعة إيميلات البيع"), KeyboardButton("مراجعة طلبات السحب")],
        [KeyboardButton("إدارة الرصيد"), KeyboardButton("رسالة جماعية")],
        [KeyboardButton("إحصائيات البوت")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

# ## جديد ## لوحة مفاتيح بعد استلام الإيميلات الأمريكية
def get_post_receive_american_emails_keyboard():
    keyboard = [
        [KeyboardButton("إرسال الإيميلات")],
        [KeyboardButton("رجوع للقائمة الرئيسية")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True) # One-time keyboard


# دالة الرد على أمر /start
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name if update.effective_user else "يا صديقي"

    initialize_db()

    if user_id == DEVELOPER_CHAT_ID:
        add_user(user_id, role='admin')
        user_data = get_user(user_id)
    else:
        add_user(user_id, role='user')
        user_data = get_user(user_id)

    if user_data:
        role = user_data["role"]
        if role == 'admin':
            keyboard = get_admin_keyboard()
            await update.message.reply_html(
                f"أهلاً بك يا مشرفنا **{user_name}**! جاهز لخدمتك.",
                reply_markup=keyboard
            )
            logger.info(f"المشرف {user_name} ({user_id}) بدأ البوت.")
        else:
            keyboard = get_user_keyboard()
            # ## تعديل ## رسالة الترحيب للمستخدم العادي مع طلب الانضمام للقناة
            await update.message.reply_html(
                f"أهلاً بك يا {user_name}!\n\n"
                f"جاهز لمساعدتك. اختر من القائمة أدناه.\n"
                f"لا تنسَ الانضمام لقناتنا للبقاء على اطلاع دائم: {CHANNEL_LINK}\n\n"
                f"بالتوفيق في عملك! 💪",
                reply_markup=keyboard
            )
            logger.info(f"المستخدم {user_name} ({user_id}) بدأ البوت.")
    else:
        await update.message.reply_text("عذراً، حدث خطأ في تسجيل بياناتك. يرجى المحاولة لاحقاً.")
        logger.error(f"فشل في جلب بيانات المستخدم {user_id} بعد الإضافة.")


# دوال إضافة الإيميلات الأمريكية (للمشرف)
async def add_american_emails_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id != DEVELOPER_CHAT_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return ConversationHandler.END

    await update.message.reply_text(
        "أدخل الإيميلات الأمريكية مع كلمات السر، كل إيميل على سطر جديد. "
        "مثال:\nemail1@example.com:password123\nemail2@example.com:password456\n\n"
        "أرسل /cancel للإلغاء."
    )
    return ADD_AMERICAN_EMAILS_STATE

async def receive_american_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_input = update.message.text
    emails_added_count = 0
    
    lines = user_input.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if ':' in line:
            parts = line.split(':', 1)
            email = parts[0].strip()
            password = parts[1].strip()
            if email and password:
                if add_american_email(email, password):
                    emails_added_count += 1
                else:
                    await update.message.reply_text(f"لم يتم إضافة الإيميل {email} (قد يكون موجوداً مسبقاً أو هناك خطأ).")
            else:
                await update.message.reply_text(f"تنسيق خاطئ في السطر: {line}. يجب أن يكون: email:password")
        else:
            await update.message.reply_text(f"تنسيق خاطئ في السطر: {line}. يجب أن يكون: email:password")

    if emails_added_count > 0:
        await update.message.reply_text(f"تم إضافة {emails_added_count} إيميل أمريكي بنجاح.", reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text("لم يتم إضافة أي إيميل. يرجى التأكد من التنسيق الصحيح (email:password كل سطر).", reply_markup=get_admin_keyboard())

    return ConversationHandler.END

async def cancel_add_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يلغي عملية إضافة الإيميلات.
    """
    await update.message.reply_text("تم إلغاء عملية إضافة الإيميلات الأمريكية.", reply_markup=get_admin_keyboard())
    return ConversationHandler.END


# دوال بيع الإيميلات للمستخدم العادي (لمى)
async def sell_emails_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يبدأ عملية بيع الإيميلات ويعرض خيارات (أمريكية/عشوائية).
    """
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data or user_data['role'] != 'user':
        await update.message.reply_text("عذراً، هذا القسم مخصص للمستخدمين العاديين.")
        return ConversationHandler.END

    keyboard = [
        [KeyboardButton("إيميلات أمريكية")],
        [KeyboardButton("إيميلات عشوائية")],
        [KeyboardButton("رجوع للقائمة الرئيسية")]
    ]
    await update.message.reply_text(
        "اختر نوع الإيميلات التي ترغب ببيعها:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    )
    return SELL_EMAILS_CHOICE

async def choose_american_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يطلب من المستخدم إدخال عدد الإيميلات الأمريكية المطلوبة.
    """
    await update.message.reply_text(
        "أدخل عدد الإيميلات الأمريكية التي ترغب بها (من 1 إلى 5):",
        reply_markup=ReplyKeyboardRemove()
    )
    return SELL_AMERICAN_COUNT

async def receive_american_emails_count(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يستقبل العدد المطلوب من المستخدم، ويجلب الإيميلات، ثم يرسلها.
    """
    user_id = update.effective_user.id
    try:
        count = int(update.message.text.strip())
        if not (1 <= count <= 5):
            await update.message.reply_text("العدد يجب أن يكون بين 1 و 5. يرجى المحاولة مرة أخرى أو أرسل /cancel.")
            return SELL_AMERICAN_COUNT
            
        available_emails = get_available_american_emails(count)
        
        if not available_emails:
            await update.message.reply_text("عذراً، لا توجد إيميلات أمريكية متاحة حالياً بهذا العدد. يرجى المحاولة لاحقاً.", reply_markup=get_user_keyboard())
            return ConversationHandler.END

        if len(available_emails) < count:
            await update.message.reply_text(f"عذراً، لم نتمكن من توفير {count} إيميل. تم توفير {len(available_emails)} إيميل فقط.", reply_markup=get_user_keyboard())
            count = len(available_emails)
            
        emails_to_send = []
        email_ids_to_mark_sold = []
        for email_data in available_emails:
            emails_to_send.append(f"• الإيميل: `{email_data['email']}`\nكلمة السر: `{email_data['password']}`")
            email_ids_to_mark_sold.append(email_data['id'])
        
        if mark_emails_as_sold(email_ids_to_mark_sold, user_id):
            response_text = "تم توفير الإيميلات الأمريكية المطلوبة:\n\n" + "\n\n".join(emails_to_send)
            response_text += "\n\n"
            response_text += "🔴 ملاحظة هامة: لديك 24 ساعة لبيع هذه الإيميلات وقبولها من المشرف. بعد 24 ساعة لن يتم قبول الإيميلات."
            
            # ## تعديل ## إرسال لوحة مفاتيح خاصة بعد استلام الإيميلات
            await update.message.reply_text(response_text, parse_mode='Markdown', reply_markup=get_post_receive_american_emails_keyboard())
            logger.info(f"المستخدم {user_id} استلم {count} إيميل أمريكي.")
        else:
            await update.message.reply_text("حدث خطأ في معالجة طلبك. يرجى المحاولة مرة أخرى.", reply_markup=get_user_keyboard())
            logger.error(f"فشل في تحديث حالة الإيميلات كـ 'مباع' للمستخدم {user_id}.")

    except ValueError:
        await update.message.reply_text("الرجاء إدخال رقم صحيح للعدد. يرجى المحاولة مرة أخرى أو أرسل /cancel.")
        return SELL_AMERICAN_COUNT
        
    return ConversationHandler.END # المحادثة ستنتهي هنا، واللوحة الجديدة ستكون جاهزة

async def sell_random_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    وظيفة مؤقتة لبيع الإيميلات العشوائية.
    """
    await update.message.reply_text("ميزة بيع الإيميلات العشوائية قيد التطوير حالياً. يرجى الانتظار.", reply_markup=get_user_keyboard())
    return ConversationHandler.END

async def cancel_sell_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يلغي عملية بيع الإيميلات.
    """
    await update.message.reply_text("تم إلغاء عملية بيع الإيميلات.", reply_markup=get_user_keyboard())
    return ConversationHandler.END

# دوال إرسال الإيميلات للمراجعة (للمستخدم العادي)
async def submit_emails_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يبدأ عملية إرسال الإيميلات للمراجعة ويطلب من المستخدم إدخالها.
    """
    user_id = update.effective_user.id
    user_data = get_user(user_id)
    if not user_data or user_data['role'] != 'user':
        await update.message.reply_text("عذراً، هذا القسم مخصص للمستخدمين العاديين.")
        return ConversationHandler.END
    
    keyboard = [
        [KeyboardButton("إيميل أمريكي (من البوت)")],
        [KeyboardButton("إيميل عشوائي (منك)")]
    ]
    await update.message.reply_text(
        "اختر نوع الإيميل الذي ترسله للمراجعة:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    )
    return SUBMIT_EMAILS_TYPE_CHOICE

async def submit_emails_type_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    choice = update.message.text
    context.user_data['submission_type'] = choice
    
    if choice == "إيميل أمريكي (من البوت)":
        await update.message.reply_text(
            "أدخل الإيميلات الأمريكية (التي اشتريتها من البوت) مع كلمات السر.\n"
            "ملاحظة: يجب أن تكون الإيميلات هي آخر 5 إيميلات اشتريتها من البوت. "
            "كل إيميل على سطر جديد:\nemail:password\n\n"
            "أرسل /cancel للإلغاء.",
            reply_markup=ReplyKeyboardRemove()
        )
        return SUBMIT_EMAILS_STATE
    elif choice == "إيميل عشوائي (منك)":
        await update.message.reply_text(
            "أدخل الإيميل العشوائي مع كلمة السر.\n"
            "مثال:\nemail@example.com:password123\n\n"
            "أرسل /cancel للإلغاء.",
            reply_markup=ReplyKeyboardRemove()
        )
        return SUBMIT_EMAILS_STATE
    else:
        await update.message.reply_text("خيار غير صالح. يرجى اختيار 'إيميل أمريكي (من البوت)' أو 'إيميل عشوائي (منك)' أو /cancel.", reply_markup=get_user_keyboard())
        return ConversationHandler.END

async def receive_submitted_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يستقبل الإيميلات المرسلة للمراجعة من المستخدم ويخزنها ويرسل إشعار للمشرف.
    """
    user_id = update.effective_user.id
    user_name = update.effective_user.first_name
    user_input = update.message.text
    submission_type = context.user_data.get('submission_type')
    
    submitted_count = 0
    all_submitted_emails_text = []

    lines = user_input.split('\n')
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        if ':' in line:
            parts = line.split(':', 1)
            email = parts[0].strip()
            password = parts[1].strip()
            
            if email and password:
                if add_submitted_email(user_id, email, password, submission_type):
                    submitted_count += 1
                    all_submitted_emails_text.append(f"• الإيميل: `{email}`\nكلمة السر: `{password}`")
                else:
                    await update.message.reply_text(f"لم يتم إضافة الإيميل {email} للمراجعة (قد يكون هناك خطأ).")
            else:
                await update.message.reply_text(f"تنسيق خاطئ في السطر: {line}. يجب أن يكون: email:password")
        else:
            await update.message.reply_text(f"تنسيق خاطئ في السطر: {line}. يجب أن يكون: email:password")

    if submitted_count > 0:
        await update.message.reply_text(
            f"تم إرسال {submitted_count} إيميل للمراجعة بنجاح. سيتم إشعارك بالقبول أو الرفض خلال 24 ساعة.",
            reply_markup=get_user_keyboard()
        )
        logger.info(f"المستخدم {user_id} أرسل {submitted_count} إيميل للمراجعة.")

        # جلب آخر 5 إيميلات باعها البوت للمستخدم
        last_sold_emails = get_last_sold_emails_to_user(user_id, count=5)
        last_sold_emails_text = ""
        if last_sold_emails:
            last_sold_emails_text = "\n\n**آخر 5 إيميلات تم توفيرها من البوت لهذا المستخدم (للتحقق):**\n"
            for i, email_data in enumerate(last_sold_emails):
                last_sold_emails_text += f"• `{email_data['email']}` : `{email_data['password']}`\n"
        else:
            last_sold_emails_text = "\n\n*(لم يتم توفير أي إيميلات أمريكية من البوت لهذا المستخدم بعد.)*"


        # إرسال إشعار للمشرف
        admin_notification_text = (
            f"🔔 طلب مراجعة إيميلات جديد من المستخدم: {user_name} (ID: {user_id})\n"
            f"النوع: **{submission_type}**\n"
            f"الإيميلات المرسلة للمراجعة:\n" + "\n\n".join(all_submitted_emails_text) + "\n" + last_sold_emails_text + "\n\n"
            f"يرجى مراجعتها في قسم 'مراجعة إيميلات البيع'."
        )
        try:
            await context.bot.send_message(chat_id=DEVELOPER_CHAT_ID, text=admin_notification_text, parse_mode='Markdown')
            logger.info(f"تم إرسال إشعار مراجعة الإيميلات للمشرف.")
        except Exception as e:
            logger.error(f"فشل إرسال إشعار مراجعة الإيميلات للمشرف: {e}")
            
    else:
        await update.message.reply_text("لم يتم إرسال أي إيميل للمراجعة. يرجى التأكد من التنسيق الصحيح.", reply_markup=get_user_keyboard())

    return ConversationHandler.END

async def cancel_submit_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يلغي عملية إرسال الإيميلات للمراجعة.
    """
    await update.message.reply_text("تم إلغاء عملية إرسال الإيميلات للمراجعة.", reply_markup=get_user_keyboard())
    return ConversationHandler.END

# دوال إدارة الإيميلات الأمريكية (للمشرف)
async def manage_american_emails_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يبدأ عملية إدارة الإيميلات الأمريكية ويعرض خيارات (عرض، حذف).
    """
    user_id = update.effective_user.id
    if user_id != DEVELOPER_CHAT_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return ConversationHandler.END

    counts = get_american_emails_counts()
    response_text = (
        f"🔴 إحصائيات الإيميلات الأمريكية:\n"
        f"   - المتاح: {counts['available']} إيميل\n"
        f"   - المباع: {counts['sold']} إيميل\n"
        f"   - الإجمالي: {counts['total']} إيميل\n\n"
        "اختر العملية:"
    )

    keyboard = [
        [KeyboardButton("عرض الإيميلات المتاحة")],
        [KeyboardButton("حذف إيميل أمريكي")],
        [KeyboardButton("رجوع للقائمة الرئيسية \\(إدارة الإيميلات\\)")]
    ]
    await update.message.reply_text(
        response_text,
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    )
    return MANAGE_AMERICAN_EMAILS_CHOICE

async def display_available_american_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يعرض جميع الإيميلات الأمريكية المتاحة للمشرف.
    """
    emails = get_all_available_american_emails_for_admin()
    if emails:
        response_text = "الإيميلات الأمريكية المتاحة:\n\n"
        for i, email_data in enumerate(emails):
            response_text += f"{i+1}. الإيميل: `{email_data['email']}`\n   كلمة السر: `{email_data['password']}`\n"
        await update.message.reply_text(response_text, parse_mode='Markdown', reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text("لا توجد إيميلات أمريكية متاحة حالياً.", reply_markup=get_admin_keyboard())
    return ConversationHandler.END

async def delete_american_email_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يطلب من المشرف إدخال الإيميل المراد حذفه.
    """
    await update.message.reply_text(
        "أدخل الإيميل الأمريكي الذي ترغب بحذفه (كامل وصحيح):\n\n"
        "أرسل /cancel للإلغاء.",
        reply_markup=ReplyKeyboardRemove()
    )
    return DELETE_AMERICAN_EMAIL_STATE

async def process_delete_american_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يستقبل الإيميل من المشرف ويحذفه من قاعدة البيانات.
    """
    email_to_delete = update.message.text.strip()
    if delete_american_email(email_to_delete):
        await update.message.reply_text(f"تم حذف الإيميل {email_to_delete} بنجاح.", reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text(f"لم يتم العثور على الإيميل {email_to_delete} أو حدث خطأ أثناء الحذف.", reply_markup=get_admin_keyboard())
    return ConversationHandler.END

async def cancel_manage_emails(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يلغي عملية إدارة الإيميلات ويعود للقائمة الرئيسية للمشرف.
    """
    await update.message.reply_text("تم إلغاء عملية إدارة الإيميلات.", reply_markup=get_admin_keyboard())
    return ConversationHandler.END


# دوال مراجعة إيميلات البيع (للمشرف)
async def review_emails_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يبدأ عملية مراجعة الإيميلات ويعرض الإيميلات المعلقة.
    """
    user_id = update.effective_user.id
    if user_id != DEVELOPER_CHAT_ID:
        await update.message.reply_text("عذراً، هذا الأمر مخصص للمشرفين فقط.")
        return ConversationHandler.END

    pending_emails = get_pending_submitted_emails()

    if not pending_emails:
        await update.message.reply_text("لا توجد إيميلات معلقة للمراجعة حالياً.", reply_markup=get_admin_keyboard())
        return ConversationHandler.END
    
    for email_data in pending_emails:
        seller_user_data = get_user(email_data['seller_user_id'])
        seller_name = seller_user_data['user_id'] if not seller_user_data else f"{seller_user_data['user_id']} ({seller_user_data.get('username', 'N/A')})"

        keyboard = [
            [InlineKeyboardButton("✅ قبول", callback_data=f"accept_{email_data['id']}"),
             InlineKeyboardButton("❌ رفض", callback_data=f"reject_{email_data['id']}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        message_text = (
            f"🔔 طلب مراجعة إيميل:\n"
            f"   - من المستخدم: {seller_name}\n"
            f"   - نوع الإيميل: **{email_data['type']}**\n"
            f"   - الإيميل: `{email_data['email']}`\n"
            f"   - كلمة السر: `{email_data['password']}`\n"
            f"   - تاريخ الإرسال: {email_data['created_at']}"
        )
        await update.message.reply_text(message_text, parse_mode='Markdown', reply_markup=reply_markup)
        logger.info(f"تم عرض إيميل {email_data['id']} للمراجعة للمشرف {user_id}.")

    await update.message.reply_text("تم عرض جميع الإيميلات المعلقة للمراجعة. يرجى استخدام الأزرار أدناه للتعامل معها.", reply_markup=get_admin_keyboard())
    return ConversationHandler.END

async def handle_review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يعالج ضغط المشرف على زر "قبول" أو "رفض" لإيميل معين.
    """
    query = update.callback_query
    await query.answer()

    action, email_id = query.data.split('_')
    email_id = int(email_id)

    email_data = get_submitted_email_by_id(email_id)
    if not email_data:
        await query.edit_message_text("عذراً، هذا الإيميل لم يعد موجوداً أو تم التعامل معه مسبقاً.")
        return ConversationHandler.END

    seller_user_id = email_data['seller_user_id']
    seller_user_data = get_user(seller_user_id)
    seller_name = seller_user_data['user_id'] if not seller_user_data else f"{seller_user_data['user_id']} ({seller_user_data.get('username', 'N/A')})"

    if action == "accept":
        context.user_data['current_email_id_to_accept'] = email_id
        context.user_data['current_seller_user_id'] = seller_user_id
        context.user_data['current_email_type'] = email_data['type']
        
        await query.edit_message_text(f"تم قبول الإيميل:\n   - الإيميل: `{email_data['email']}`\n   - كلمة السر: `{email_data['password']}`\n\nأدخل الرصيد الذي سيتم إضافته للمستخدم {seller_name} (ID: {seller_user_id}):\nأرسل /cancel للإلغاء.")
        return ACCEPT_EMAIL_BALANCE_ADJUST
        
    elif action == "reject":
        context.user_data['current_email_id_to_reject'] = email_id
        context.user_data['current_seller_user_id'] = seller_user_id
        await query.edit_message_text(f"تم اختيار رفض الإيميل:\n   - الإيميل: `{email_data['email']}`\n\nأدخل سبب الرفض:\nأرسل /cancel للإلغاء.")
        return REJECT_EMAIL_REASON

    return ConversationHandler.END


async def process_rejection_reason(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يستقبل سبب الرفض من المشرف ويحدث حالة الإيميل ويرسل إشعار للمستخدم.
    """
    email_id = context.user_data.pop('current_email_id_to_reject', None)
    seller_user_id = context.user_data.pop('current_seller_user_id', None)
    rejection_reason = update.message.text.strip()

    if email_id and seller_user_id:
        if update_submitted_email_status(email_id, 'rejected', rejection_reason):
            await update.message.reply_text("تم رفض الإيميل وإرسال الإشعار للمستخدم.", reply_markup=get_admin_keyboard())
            await context.bot.send_message(
                chat_id=seller_user_id,
                text=f"🔴 تم رفض الإيميل الذي أرسلته للمراجعة.\nالسبب: {rejection_reason}\n\nيرجى بيعه في خانة الإيميلات العشوائية أو تغيير كلمة سره لحمايتك.",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("بيع كإيميل عشوائي")],
                    [KeyboardButton("رجوع للقائمة الرئيسية")]
                ], resize_keyboard=True, one_time_keyboard=True)
            )
            logger.info(f"الإيميل {email_id} تم رفضه من المشرف. السبب: {rejection_reason}")
        else:
            await update.message.reply_text("حدث خطأ أثناء رفض الإيميل.", reply_markup=get_admin_keyboard())
    else:
        await update.message.reply_text("خطأ في معالجة طلب الرفض.", reply_markup=get_admin_keyboard())
    
    return ConversationHandler.END

async def process_accepted_email_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """
    يستقبل مبلغ الرصيد من المشرف، يحدث رصيد المستخدم، ويشعر المستخدم بالقبول.
    """
    email_id = context.user_data.pop('current_email_id_to_accept', None)
    seller_user_id = context.user_data.pop('current_seller_user_id', None)
    email_type = context.user_data.pop('current_email_type', None)
    
    try:
        amount_to_add = int(update.message.text.strip())

        if email_id and seller_user_id:
            if update_submitted_email_status(email_id, 'approved') and update_user_balance(seller_user_id, amount_to_add):
                await update.message.reply_text(f"تم قبول الإيميل وإضافة {amount_to_add} ليرة لرصيد المستخدم {seller_user_id}.", reply_markup=get_admin_keyboard())
                await context.bot.send_message(
                    chat_id=seller_user_id,
                    text=f"✅ تم إضافة الرصيد إلى حسابك! مبلغ: {amount_to_add} ليرة.\n"
                         f"رصيدك الحالي: {get_user(seller_user_id)['balance']} ليرة."
                )
                logger.info(f"الإيميل {email_id} تم قبوله. تم إضافة {amount_to_add} للمستخدم {seller_user_id}.")
            else:
                await update.message.reply_text("حدث خطأ أثناء قبول الإيميل أو تعديل الرصيد.", reply_markup=get_admin_keyboard())
        else:
            await update.message.reply_text("خطأ في معالجة طلب القبول.", reply_markup=get_admin_keyboard())
            
    except ValueError:
        await update.message.reply_text("الرجاء إدخال رقم صحيح للمبلغ. يرجى المحاولة مرة أخرى أو أرسل /cancel.", reply_markup=get_admin_keyboard())
        return ACCEPT_EMAIL_BALANCE_ADJUST
    
    return ConversationHandler.END


# دالة عند بدء تشغيل البوت وإرسال رسالة للمشرف
async def post_init(application: Application) -> None:
    """
    تُنفذ بعد بدء تشغيل البوت مباشرة.
    """
    initialize_db()
    add_user(DEVELOPER_CHAT_ID, role='admin')

    try:
        await application.bot.send_message(
            chat_id=DEVELOPER_CHAT_ID,
            text="جاهز لخدمتك. 🚀",
            reply_markup=get_admin_keyboard()
        )
        logger.info("تم إرسال رسالة بدء التشغيل للمشرف.")
    except Exception as e:
        logger.error(f"فشل إرسال رسالة بدء التشغيل للمشرف: {e}")


# الدالة الرئيسية لتشغيل البوت
def main() -> None:
    """تشغيل البوت."""
    application = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    # إضافة معالج المحادثات لإضافة الإيميلات الأمريكية (للمشرف)
    add_emails_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^إضافة إيميلات أمريكية$"), add_american_emails_start)],
        states={
            ADD_AMERICAN_EMAILS_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_american_emails)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add_emails)],
    )
    application.add_handler(add_emails_conv_handler)

    # إضافة معالج المحادثات لبيع الإيميلات للمستخدم العادي
    sell_emails_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^بيع إيميلات$"), sell_emails_start)],
        states={
            SELL_EMAILS_CHOICE: [
                MessageHandler(filters.Regex("^إيميلات أمريكية$"), choose_american_emails),
                MessageHandler(filters.Regex("^إيميلات عشوائية$"), sell_random_emails),
                MessageHandler(filters.Regex("^رجوع للقائمة الرئيسية$"), cancel_sell_emails)
            ],
            SELL_AMERICAN_COUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_american_emails_count)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_sell_emails)],
    )
    application.add_handler(sell_emails_conv_handler)

    # إضافة معالج المحادثات لإدارة الإيميلات الأمريكية للمشرف
    manage_emails_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^إدارة الإيميلات الأمريكية$"), manage_american_emails_start)],
        states={
            MANAGE_AMERICAN_EMAILS_CHOICE: [
                MessageHandler(filters.Regex("^عرض الإيميلات المتاحة$"), display_available_american_emails),
                MessageHandler(filters.Regex("^حذف إيميل أمريكي$"), delete_american_email_start),
                MessageHandler(filters.Regex("^رجوع للقائمة الرئيسية \\(إدارة الإيميلات\\)$"), cancel_manage_emails)
            ],
            DELETE_AMERICAN_EMAIL_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_delete_american_email)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_manage_emails)]
    )
    application.add_handler(manage_emails_conv_handler)

    # إضافة معالج المحادثات لإرسال الإيميلات للمراجعة (للمستخدم العادي)
    submit_emails_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^إرسال الإيميلات$"), submit_emails_start)],
        states={
            SUBMIT_EMAILS_TYPE_CHOICE: [
                MessageHandler(filters.Regex("^(إيميل أمريكي \(من البوت\)|إيميل عشوائي \(منك\))$"), submit_emails_type_choice)
            ],
            SUBMIT_EMAILS_STATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_submitted_emails)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_submit_emails)],
    )
    application.add_handler(submit_emails_conv_handler)

    # إضافة معالج المحادثات لمراجعة إيميلات البيع (للمشرف)
    review_emails_conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^مراجعة إيميلات البيع$"), review_emails_start)],
        states={
            REJECT_EMAIL_REASON: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_rejection_reason)
            ],
            ACCEPT_EMAIL_BALANCE_ADJUST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_accepted_email_balance)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel_manage_emails)]
    )
    application.add_handler(review_emails_conv_handler)

    # إضافة معالج لـ Inline Keyboard Callbacks (للأزرار قبول/رفض)
    application.add_handler(CallbackQueryHandler(handle_review_callback, pattern=r"^(accept|reject)_\d+$"))

    # إضافة معالج الأوامر (Command Handler) لأمر /start
    application.add_handler(CommandHandler("start", start_command))
    
    # إضافة معالجات لأزرار المشرف الأخرى (مؤقتاً)
    application.add_handler(MessageHandler(filters.Regex("^إدارة الرصيد$"), coming_soon_admin))
    application.add_handler(MessageHandler(filters.Regex("^رسالة جماعية$"), coming_soon_admin))
    application.add_handler(MessageHandler(filters.Regex("^إحصائيات البوت$"), coming_soon_admin_stats))

    # إضافة معالجات لأزرار المستخدم العادي (مؤقتاً)
    application.add_handler(MessageHandler(filters.Regex("^الرصيد$"), coming_soon_user))
    application.add_handler(MessageHandler(filters.Regex("^سحب الأرباح$"), coming_soon_user))
    # ## جديد ## معالج لزر "رجوع للقائمة الرئيسية" من الكيبورد المؤقت بعد استلام الايميلات
    application.add_handler(MessageHandler(filters.Regex("^رجوع للقائمة الرئيسية$"), go_back_to_main_user_keyboard))

    logger.info("البوت بدأ التشغيل...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

# دوال مؤقتة للأزرار (لتوضيح أن الميزة قيد التطوير)
async def coming_soon_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("هذه الميزة قيد التطوير. يرجى الانتظار.", reply_markup=get_admin_keyboard())
    logger.info(f"المشرف {update.effective_user.id} ضغط زر غير مبرمج: {update.message.text}")

async def coming_soon_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("هذه الميزة قيد التطوير. يرجى الانتظار.", reply_markup=get_user_keyboard())
    logger.info(f"المستخدم {update.effective_user.id} ضغط زر غير مبرمج: {update.message.text}")

async def coming_soon_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    conn = connect_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(user_id) FROM users")
    total_users = cursor.fetchone()[0]
    conn.close()
    await update.message.reply_text(f"عدد المستخدمين الكلي للبوت: {total_users}", reply_markup=get_admin_keyboard())
    logger.info(f"المشرف {update.effective_user.id} طلب إحصائيات البوت.")

# ## جديد ## دالة للرجوع للقائمة الرئيسية للمستخدم
async def go_back_to_main_user_keyboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("تم الرجوع للقائمة الرئيسية.", reply_markup=get_user_keyboard())


if __name__ == "__main__":
    main()
