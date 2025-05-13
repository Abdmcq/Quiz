# --- START OF FILE my_telegram_bot_v2.py ---

import logging
import random
import re
from functools import wraps
from datetime import datetime
import pytz
import asyncio
import os # لاستيراد الوظائف المتعلقة بنظام التشغيل (اختياري لحفظ حالة المستخدم)

from telegram import Update, Poll, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode

# --- إعدادات البوت ---
TELEGRAM_BOT_TOKEN = "7865670236:AAEaQGl13J57u4Hf8mzO5_Bd7Zlwe0RvFGU" # استبدل بالتوكن الخاص بك
QUESTIONS_FILE_PATH = "questions.txt"
OWNER_ID = 1749717270 # استبدل بمعرفك
OWNER_USERNAME = "@ll7ddd" # استبدل باسم المستخدم الخاص بك
DEVELOPER_INFO = f"مبرمج البوت: عبدالرحمن حسن ({OWNER_USERNAME})"
TIMEZONE = "Asia/Baghdad" # مثال، غيّره لمنطقتك الزمنية

# --- متغيرات عالمية لتتبع المستخدمين (للحفاظ على الحالة بين عمليات إعادة التشغيل، يفضل استخدام ملف أو قاعدة بيانات) ---
# سنستخدم مجموعة بسيطة في الذاكرة الآن
known_user_ids = set()
user_counter = 0
USER_DATA_FILE = "user_data.txt" # ملف لحفظ معرفات المستخدمين

# قاموس عالمي لتخزين الأسئلة مفهرسة حسب المحاضرة
LOADED_QUESTIONS_BY_LECTURE = {}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- وظائف مساعدة ---

def load_user_data():
    """تحميل بيانات المستخدمين من ملف عند بدء التشغيل."""
    global known_user_ids, user_counter
    try:
        if os.path.exists(USER_DATA_FILE):
            with open(USER_DATA_FILE, 'r') as f:
                for line in f:
                    try:
                        user_id = int(line.strip())
                        known_user_ids.add(user_id)
                    except ValueError:
                        logger.warning(f"Invalid user ID found in {USER_DATA_FILE}: {line.strip()}")
            user_counter = len(known_user_ids) # تحديث العداد بناءً على الملف
            logger.info(f"Loaded {user_counter} known user IDs from {USER_DATA_FILE}")
        else:
             logger.info(f"{USER_DATA_FILE} not found. Starting with empty user data.")

    except Exception as e:
        logger.error(f"Failed to load user data from {USER_DATA_FILE}: {e}")

def save_user_data(user_id: int):
    """حفظ معرف مستخدم جديد في الملف."""
    try:
        with open(USER_DATA_FILE, 'a') as f:
            f.write(f"{user_id}\n")
    except Exception as e:
        logger.error(f"Failed to save user ID {user_id} to {USER_DATA_FILE}: {e}")

def get_current_time_str() -> str:
    """الحصول على الوقت الحالي بالتنسيق المطلوب."""
    try:
        tz = pytz.timezone(TIMEZONE)
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        logger.warning(f"Could not use timezone {TIMEZONE}. Using default.")
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")

# --- مزيّن التحقق من المالك (يبقى للوظائف الإدارية المستقبلية أو الإشعارات) ---
# لم نعد نستخدمه للأوامر العامة، لكنه مفيد لإرسال الإشعارات
def owner_only(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user and user.id != OWNER_ID:
            logger.warning(f"Unauthorized attempt to access owner-only function {func.__name__} by {user.id} (@{user.username})")
            # لا نرسل رسالة للمستخدم هنا لأنه قد يكون مجرد خطأ برمجي
            return
        return await func(update, context, *args, **kwargs)
    return wrapped


# --- وظائف تحليل ملف الأسئلة (تبقى كما هي) ---
def parse_questions_file(file_path: str) -> dict:
    lectures_data = {}
    current_lecture_name = None
    question_buffer = []
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    if question_buffer:
                        parsed_q = parse_single_question_block(question_buffer, current_lecture_name, line_num)
                        if parsed_q and current_lecture_name:
                            if current_lecture_name not in lectures_data:
                                lectures_data[current_lecture_name] = []
                            lectures_data[current_lecture_name].append(parsed_q)
                        question_buffer = []
                    continue

                if line.upper().startswith("LECTURE:"):
                    if question_buffer:
                        parsed_q = parse_single_question_block(question_buffer, current_lecture_name, line_num)
                        if parsed_q and current_lecture_name:
                            if current_lecture_name not in lectures_data:
                                lectures_data[current_lecture_name] = []
                            lectures_data[current_lecture_name].append(parsed_q)
                        question_buffer = []
                    current_lecture_name = line.split("LECTURE:", 1)[1].strip()
                    if not current_lecture_name:
                        logger.warning(f"Empty lecture name at line {line_num}. Using default.")
                        current_lecture_name = f"Unnamed Lecture {line_num}"
                    logger.info(f"Found lecture: {current_lecture_name}")
                    question_buffer = []
                elif current_lecture_name:
                    question_buffer.append(line)
                else:
                     logger.warning(f"Line outside a lecture block (line {line_num}): {line}")

            if question_buffer and current_lecture_name:
                parsed_q = parse_single_question_block(question_buffer, current_lecture_name, line_num + 1)
                if parsed_q:
                    if current_lecture_name not in lectures_data:
                        lectures_data[current_lecture_name] = []
                    lectures_data[current_lecture_name].append(parsed_q)

        total_questions_loaded = sum(len(qs) for qs in lectures_data.values())
        logger.info(f"Successfully loaded {total_questions_loaded} questions from {len(lectures_data)} lectures.")
        return lectures_data
    except FileNotFoundError:
        logger.error(f"Error: Questions file not found at {file_path}")
        return {}
    except Exception as e:
        logger.error(f"Error parsing questions file {file_path}: {e}", exc_info=True)
        return {}

def parse_single_question_block(question_lines: list, lecture_name: str, line_num_context: int) -> dict or None:
    if not question_lines:
        return None
    question_text = question_lines[0]
    options_lines = []
    answer_line = ""
    for line in question_lines[1:]:
        if line.strip().lower().startswith("answer:"):
            answer_line = line.strip()
        elif re.match(r'^[A-Z]\s*[).]\s*', line.strip(), re.IGNORECASE): # دعم الحروف الصغيرة والكبيرة للخيارات
            options_lines.append(line.strip())
    if not question_text or not options_lines or not answer_line:
        logger.warning(f"Malformed question block in lecture '{lecture_name}' near line {line_num_context - len(question_lines)}: {question_lines}")
        return None
    parsed_options = [re.sub(r'^[A-Z]\s*[).]\s*', '', opt_line, flags=re.IGNORECASE).strip() for opt_line in options_lines]
    correct_answer_char_match = re.search(r'Answer:\s*([A-Z])', answer_line, re.IGNORECASE)
    if not correct_answer_char_match:
        logger.warning(f"Could not find correct answer char for question in '{lecture_name}': {question_text}")
        return None
    correct_answer_char = correct_answer_char_match.group(1).upper()
    try:
        # تحديد معرف الخيار الصحيح بناءً على ترتيبه في القائمة (A=0, B=1, ...)
        option_chars = [re.match(r'^([A-Z])\s*[).]', line, re.IGNORECASE).group(1).upper() for line in options_lines if re.match(r'^[A-Z]\s*[).]', line, re.IGNORECASE)]
        if correct_answer_char in option_chars:
             correct_option_id = option_chars.index(correct_answer_char)
        else:
             logger.warning(f"Correct answer char '{correct_answer_char}' does not match any option prefix (A, B, C...) for question in '{lecture_name}': {question_text}")
             return None

        if not (0 <= correct_option_id < len(parsed_options)):
             logger.warning(f"Correct answer index calculation failed for question in '{lecture_name}': {question_text}")
             return None

    except (TypeError, ValueError, IndexError) as e:
        logger.warning(f"Could not determine correct_option_id for question in '{lecture_name}' (Char: {correct_answer_char}, Options: {options_lines}): {question_text} - Error: {e}")
        return None
    return {
        "question": question_text,
        "options": parsed_options,
        "correct_option_id": correct_option_id
    }


# --- وظيفة إرسال الاستفتاء (تبقى كما هي تقريبًا) ---
async def send_quiz_poll(chat_id: int, context: ContextTypes.DEFAULT_TYPE, question_data: dict) -> None:
    question_text = question_data["question"]
    options = question_data["options"]
    correct_option_id = question_data["correct_option_id"]

    # التحقق من عدد الخيارات (بين 2 و 10)
    if not (2 <= len(options) <= 10):
        logger.error(f"Invalid number of options ({len(options)}) for question: {question_text} in chat {chat_id}. Skipping.")
        # إعلام المالك بالمشكلة قد يكون مفيدًا
        try:
            await context.bot.send_message(OWNER_ID, f"⚠️ خطأ في السؤال:\nالسؤال: {question_text}\nالمشكلة: عدد الخيارات غير صالح ({len(options)}), يجب أن يكون بين 2 و 10.\nلن يتم إرسال هذا السؤال.")
        except Exception as notify_err:
            logger.error(f"Failed to send error notification to owner: {notify_err}")
        return

    # التأكد من أن correct_option_id ضمن النطاق الصحيح
    if not (0 <= correct_option_id < len(options)):
         logger.error(f"Invalid correct_option_id ({correct_option_id}) for question with {len(options)} options: {question_text} in chat {chat_id}. Skipping.")
         try:
            await context.bot.send_message(OWNER_ID, f"⚠️ خطأ في السؤال:\nالسؤال: {question_text}\nالمشكلة: فهرس الإجابة الصحيحة ({correct_option_id}) خارج نطاق الخيارات (0-{len(options)-1}).\nلن يتم إرسال هذا السؤال.")
         except Exception as notify_err:
            logger.error(f"Failed to send error notification to owner: {notify_err}")
         return

    try:
        await context.bot.send_poll(
            chat_id=chat_id,
            question=question_text,
            options=options,
            is_anonymous=True, # يبقى مجهول الهوية للمستخدمين
            type=Poll.QUIZ,
            correct_option_id=correct_option_id,
            # يمكنك إضافة explanation إذا أردت شرح الإجابة بعد انتهاء الاستفتاء
            # explanation="هذا هو الشرح...",
            # explanation_parse_mode=ParseMode.MARKDOWN_V2 # أو HTML
        )
        logger.info(f"Sent poll: '{question_text[:30]}...' to chat_id: {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send poll to {chat_id} for question '{question_text[:30]}...': {e}")
        try:
            await context.bot.send_message(OWNER_ID, f"فشل إرسال استفتاء للسؤال: {question_text} إلى الدردشة {chat_id}. الخطأ: {e}")
        except Exception as notify_err:
            logger.error(f"Failed to send owner notification about failed poll: {notify_err}")


# --- معالج الأمر /start ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global user_counter, known_user_ids
    user = update.effective_user
    chat_id = update.effective_chat.id

    if not user:
        logger.warning("Received /start from update with no effective_user.")
        return

    is_owner = user.id == OWNER_ID
    is_new_user = user.id not in known_user_ids

    if is_new_user and not is_owner: # لا نعد المالك كمستخدم جديد في الإحصائيات العامة
        user_counter += 1
        known_user_ids.add(user.id)
        save_user_data(user.id) # حفظ المستخدم الجديد في الملف
        logger.info(f"New user started the bot: {user.id} (@{user.username}). Total users: {user_counter}")

        # إرسال إشعار للمالك بالمستخدم الجديد
        current_time = get_current_time_str()
        user_info_message = (
            f"🎉 مستخدم جديد بدأ استخدام البوت!\n\n"
            f"👤 المستخدم رقم: {user_counter}\n"
            f"الاسم: {user.first_name} {user.last_name or ''}\n"
            f"المعرف: @{user.username or 'لا يوجد'}\n"
            f"ID: `{user.id}`\n"
            f"🕒 الوقت: {current_time}\n\n"
            f"📊 إجمالي المستخدمين الآن: {len(known_user_ids)}"
        )
        try:
            await context.bot.send_message(chat_id=OWNER_ID, text=user_info_message, parse_mode=ParseMode.MARKDOWN)
        except Exception as e:
            logger.error(f"Failed to send new user notification to owner: {e}")

    # --- بناء الواجهة ---
    keyboard = []
    if not LOADED_QUESTIONS_BY_LECTURE:
         # رسالة إذا لم يتم تحميل أسئلة
         no_questions_text = "عذراً، لم يتم تحميل أي أسئلة بعد. يرجى المحاولة لاحقاً."
         if is_owner:
              no_questions_text += "\n\nتأكد من وجود ملف `questions.txt` وتنسيقه بشكل صحيح."
         await update.message.reply_text(no_questions_text)
         return
    else:
        # إنشاء أزرار للمحاضرات
        for lecture_name in sorted(LOADED_QUESTIONS_BY_LECTURE.keys()):
             # استخدام جزء آمن من اسم المحاضرة كـ callback_data
             # قد نحتاج إلى تقصير أو تشفير الأسماء الطويلة جدًا أو التي تحتوي رموزًا خاصة
             # هنا سنستخدم الاسم مباشرة، مع افتراض أنه بسيط بما فيه الكفاية
             callback_data = f"lecture:{lecture_name}"
             # التأكد من أن طول callback_data لا يتجاوز 64 بايت
             if len(callback_data.encode('utf-8')) > 64:
                  logger.warning(f"Lecture name '{lecture_name}' is too long for callback_data. Skipping button.")
                  # يمكن استخدام hash أو طريقة أخرى لتوليد معرف قصير وفريد
                  continue
             keyboard.append([InlineKeyboardButton(lecture_name, callback_data=callback_data)])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # --- تحديد رسالة الترحيب ---
    if is_owner:
        welcome_text = (
            f"أهلاً بك يا مالك البوت {user.first_name}!\n\n"
            f"تم تحميل {sum(len(qs) for qs in LOADED_QUESTIONS_BY_LECTURE.values())} سؤالاً من {len(LOADED_QUESTIONS_BY_LECTURE)} محاضرة.\n"
            f"عدد المستخدمين الكلي: {len(known_user_ids)}\n\n"
            "اختر محاضرة من الأسفل لإرسال أسئلتها لنفسك (أو للمجموعة إذا أضفت البوت إليها):\n"
            f"(المستخدم رقم {list(known_user_ids).index(user.id)+1 if user.id in known_user_ids else 'غير مسجل؟!'})" # عرض رقم المالك إذا كان مسجلاً
        )
    else:
        welcome_text = (
             f"أهلاً بك يا {user.first_name} في بوت الكويزات!\n\n"
             f"{DEVELOPER_INFO}\n\n"
             "اختر المحاضرة التي تريد اختبار نفسك فيها من القائمة أدناه:"
         )

    # إرسال الرسالة مع الأزرار
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)


# --- معالج ضغطات الأزرار ---
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user
    chat_id = update.effective_chat.id

    # يجب الإجابة على الـ callback query لإزالة علامة التحميل من الزر
    await query.answer()

    callback_data = query.data
    logger.info(f"Button pressed by {user.id} (@{user.username}) in chat {chat_id}. Data: {callback_data}")

    if callback_data.startswith("lecture:"):
        lecture_name = callback_data.split(":", 1)[1]

        if lecture_name in LOADED_QUESTIONS_BY_LECTURE:
            questions_to_send = LOADED_QUESTIONS_BY_LECTURE[lecture_name]
            if not questions_to_send:
                await query.edit_message_text(text=f"لا توجد أسئلة متاحة حالياً للمحاضرة: {lecture_name}")
                return

            # إعلام المستخدم بأنه سيتم إرسال الأسئلة
            # نستخدم query.message.reply_text للإرسال كرد على الرسالة الأصلية (أو في نفس الدردشة)
            await query.message.reply_text(
                f"👍 حسنًا! سأقوم الآن بإرسال أسئلة محاضرة '{lecture_name}' ({len(questions_to_send)} سؤال).",
                reply_to_message_id=query.message.message_id # الرد على رسالة الأزرار
            )
            # يمكن أيضاً تعديل رسالة الأزرار نفسها
            # await query.edit_message_text(text=f"جاري إرسال أسئلة محاضرة: {lecture_name}...")

            # إرسال جميع أسئلة المحاضرة المحددة
            send_delay = 0.5 # تأخير بسيط بين الأسئلة لتجنب مشاكل التقييد
            for i, question_data in enumerate(questions_to_send):
                logger.debug(f"Sending question {i+1}/{len(questions_to_send)} for '{lecture_name}' to chat {chat_id}")
                await send_quiz_poll(chat_id, context, question_data)
                await asyncio.sleep(send_delay) # انتظار قليل

            # (اختياري) إرسال رسالة اكتمال بعد إرسال جميع الأسئلة
            await context.bot.send_message(chat_id=chat_id, text=f"✅ تم إرسال جميع أسئلة محاضرة '{lecture_name}'. بالتوفيق!")
            # (اختياري) إزالة الأزرار من الرسالة الأصلية بعد الاختيار (إذا لم يتم تعديلها سابقاً)
            # try:
            #    await query.edit_message_reply_markup(reply_markup=None)
            # except Exception as e:
            #    logger.warning(f"Could not edit original message reply markup: {e}")


        else:
            logger.warning(f"Received callback for unknown lecture: {lecture_name}")
            await query.edit_message_text(text="عذراً، حدث خطأ ما أو أن هذه المحاضرة لم تعد متوفرة.")

    # يمكنك إضافة المزيد من الشروط هنا لمعالجة أنواع أخرى من الأزرار إذا أضفتها لاحقاً
    # elif callback_data == "show_help":
    #    await query.message.reply_text("هنا رسالة المساعدة...")
    # elif callback_data == "owner_stats" and user.id == OWNER_ID:
    #    # ... عرض إحصائيات للمالك ...


# --- الوظيفة الرئيسية ---
def main() -> None:
    global LOADED_QUESTIONS_BY_LECTURE
    # تحميل بيانات المستخدمين أولاً
    load_user_data()

    # تحميل الأسئلة
    LOADED_QUESTIONS_BY_LECTURE = parse_questions_file(QUESTIONS_FILE_PATH)

    if not LOADED_QUESTIONS_BY_LECTURE:
        logger.warning("No questions loaded. Bot might have limited functionality.")
    else:
        logger.info(f"Total {sum(len(qs) for qs in LOADED_QUESTIONS_BY_LECTURE.values())} questions loaded across {len(LOADED_QUESTIONS_BY_LECTURE)} lectures.")


    # إعداد التطبيق
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # إضافة المعالجات
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command)) # يمكن جعل /help يعرض نفس واجهة /start
    application.add_handler(CallbackQueryHandler(button_handler)) # معالج ضغطات الأزرار

    # إزالة المعالجات النصية القديمة التي تم استبدالها بالأزرار
    # application.add_handler(CommandHandler("listlectures", list_lectures_command)) # تم استبداله بأزرار start
    # application.add_handler(CommandHandler("quizlecture", quiz_lecture_command)) # تم استبداله بـ CallbackQueryHandler


    logger.info(f"Bot started. Owner: {OWNER_ID} ({OWNER_USERNAME}). Loaded users: {len(known_user_ids)}")
    # تشغيل البوت
    application.run_polling(allowed_updates=Update.ALL_TYPES)

    logger.info("Bot stopped.")

# --- نقطة الدخول ---
if __name__ == "__main__":
    main()

# --- END OF FILE my_telegram_bot_v2.py ---