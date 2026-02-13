import os
import sqlite3
import random
import string
import json
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from datetime import datetime
from groq import Groq
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'default_key')
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- إعداد قاعدة البيانات وتوليد الأكواد ---
def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS codes (code TEXT PRIMARY KEY, is_used INTEGER DEFAULT 0)')
    c.execute('SELECT COUNT(*) FROM codes')
    if c.fetchone()[0] == 0:
        print("جاري توليد 10,000 كود... يرجى الانتظار.")
        all_codes = set()
        chars = string.ascii_uppercase + string.digits
        while len(all_codes) < 10000:
            all_codes.add(''.join(random.choice(chars) for _ in range(4)))
        c.executemany('INSERT INTO codes (code, is_used) VALUES (?, 0)', [(code,) for code in all_codes])
        with open('my_student_codes.txt', 'w') as f:
            for code in sorted(list(all_codes)): f.write(f"{code}\n")
        print("تم حفظ الأكواد في ملف my_student_codes.txt")
    conn.commit()
    conn.close()

init_db()

def verify_code(user_code):
    user_code = user_code.strip().upper()
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('SELECT is_used FROM codes WHERE code = ?', (user_code,))
    res = c.fetchone()
    if res and res[0] == 0:
        c.execute('UPDATE codes SET is_used = 1 WHERE code = ?', (user_code,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

# --- المسارات ---
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        code = request.form.get('access_code', '')
        if verify_code(code):
            session['auth'] = True
            return redirect(url_for('register'))
        return render_template('index.html', error="الكود غير صحيح أو تم استخدامه!")
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if not session.get('auth'): return redirect(url_for('index'))
    if request.method == 'POST':
        session['user_data'] = request.form.to_dict()
        return redirect(url_for('schedule_info'))
    return render_template('register.html')

@app.route('/schedule_info', methods=['GET', 'POST'])
def schedule_info():
    if not session.get('auth'): return redirect(url_for('index'))
    if request.method == 'POST':
        session['routine'] = request.form.to_dict()
        return redirect(url_for('exam'))
    return render_template('schedule_info.html')

@app.route('/exam')
def exam():
    if not session.get('auth'): return redirect(url_for('index'))
    user = session.get('user_data', {})
    prompt = f"ولد 10 أسئلة MCQ متنوعة لمستوى {user.get('grade')} {user.get('stage')} منهج مصر. الرد JSON فقط يحتوي على 'questions' وبداخلها 'q', 'a', 'correct', 'subject'."
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        session['questions'] = json.loads(completion.choices[0].message.content).get('questions', [])
    except: session['questions'] = []
    return render_template('exam.html', questions=session['questions'])

@app.route('/analyze_results', methods=['POST'])
def analyze_results():
    if not session.get('auth'): return redirect(url_for('index'))
    answers = request.form.to_dict()
    questions = session.get('questions', [])
    score = 0
    weakness = []
    for i, q in enumerate(questions):
        if answers.get(f'q{i}') == q['correct']: score += 1
        else: weakness.append(q['subject'])
   
    time_taken = answers.get('time_taken', '0')
    rating = "ممتاز 🌟" if score >= 9 else "جيد جداً 👍" if score >= 7 else "يحتاج مجهود 💪"
   
    user = session.get('user_data', {})
    routine = session.get('routine', {})
    days = {"Saturday":"السبت","Sunday":"الأحد","Monday":"الاثنين","Tuesday":"الثلاثاء","Wednesday":"الأربعاء","Thursday":"الخميس","Friday":"الجمعة"}
    today = days.get(datetime.now().strftime("%A"), "اليوم")
    today_routine = routine.get(f'routine_{today}', 'لا يوجد التزامات مسجلة')

    prompt = f"""
    أنت مساعد تعليمي ذكي للمهندسة ملاك. الطالب: {user.get('name')} - {user.get('grade')}.
    نتيجة الاختبار: {score}/10 ({rating}). الوقت: {time_taken} ثانية. ضعف في: {set(weakness)}.
    روتين الطالب اليوم كما كتبه: "{today_routine}".
   
    المطلوب رد HTML فقط (بدون markdown) بتنسيق Bootstrap:
    1. بطاقة (Card) ملونة تعرض النتيجة والتقييم ونصيحة للمواد الضعيفة.
    2. جدول يومي ذكي:
       - حلل الروتين "{today_routine}". إذا ذكر مواعيد مدرسة أو دروس، ابنِ الجدول حولها.
       - ضع "مدرسة" و "دروس" في مواعيدها.
       - املأ أوقات الفراغ بـ (راحة، غداء، مذاكرة مادة، مهارة جديدة لمدة 30 دقيقة).
       - لا تضع أسئلة. فقط الجدول والتحليل.
    """
    try:
        completion = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": prompt}])
        session['plan'] = completion.choices[0].message.content.replace('```html', '').replace('```', '')
        return redirect(url_for('dashboard'))
    except: return "Error"

@app.route('/dashboard')
def dashboard():
    if not session.get('auth'): return redirect(url_for('index'))
    return render_template('dashboard.html', plan=session.get('plan', ''))

@app.route('/ask-bot', methods=['POST'])
def ask_bot():
    msg = request.json.get('message', '')
    completion = client.chat.completions.create(model="llama-3.3-70b-versatile", messages=[{"role": "user", "content": msg}])
    return jsonify({'reply': completion.choices[0].message.content})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)