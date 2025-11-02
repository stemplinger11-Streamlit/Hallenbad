"""
Wasserwacht Dienstplan+ v7.0 - Firebase Edition
Komplett neu entwickelt | Modern | Minimalistisch | Mobile-First
"""

import streamlit as st
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import smtplib
import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from twilio.rest import Client
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# Firebase
from google.cloud import firestore
from google.oauth2 import service_account

# ===== KONFIGURATION =====
VERSION = "7.0 - Wasserwacht Edition"
TIMEZONE_STR = "Europe/Berlin"
TZ = pytz.timezone(TIMEZONE_STR)

# Schicht-Slots
WEEKLY_SLOTS = [
    {"id": 1, "day": "tuesday", "day_name": "Dienstag", "start": "17:00", "end": "20:00"},
    {"id": 2, "day": "friday", "day_name": "Freitag", "start": "17:00", "end": "20:00"},
    {"id": 3, "day": "saturday", "day_name": "Samstag", "start": "14:00", "end": "17:00"},
]

# Feiertage Bayern
BAVARIA_HOLIDAYS = {
    "2025": ["2025-01-01", "2025-01-06", "2025-04-18", "2025-04-21", "2025-05-01", 
             "2025-05-29", "2025-06-09", "2025-06-19", "2025-08-15", "2025-10-03", 
             "2025-11-01", "2025-12-25", "2025-12-26"],
    "2026": ["2026-01-01", "2026-01-06", "2026-04-03", "2026-04-06", "2026-05-01", 
             "2026-05-14", "2026-05-25", "2026-06-04", "2026-08-15", "2026-10-03", 
             "2026-11-01", "2026-12-25", "2026-12-26"]
}

# Wasserwacht Farbschema
COLORS = {
    "rot": "#DC143C", "rot_dunkel": "#B22222", "rot_hell": "#FF6B6B",
    "blau": "#003087", "blau_hell": "#4A90E2",
    "weiss": "#FFFFFF", "grau_hell": "#F5F7FA", "grau_mittel": "#E1E8ED",
    "text": "#14171A", "erfolg": "#17BF63", "warnung": "#FFAD1F", "fehler": "#E0245E"
}

# ===== FIREBASE INIT =====
@st.cache_resource
def init_firestore():
    try:
        if not hasattr(st, 'secrets'):
            st.error("❌ Keine Secrets!")
            st.stop()
        
        key = st.secrets.get("firebase", {}).get("service_account_key")
        if not key:
            st.error("❌ Firebase Key fehlt! Siehe DEPLOYMENT_GUIDE.md")
            st.stop()
        
        key_dict = json.loads(key)
        creds = service_account.Credentials.from_service_account_info(key_dict)
        return firestore.Client(credentials=creds, project=key_dict["project_id"])
    except Exception as e:
        st.error(f"❌ Firebase-Fehler: {e}")
        st.stop()

db = init_firestore()

# ===== HELPER FUNCTIONS =====
def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def week_start(d=None):
    d = d or datetime.now().date()
    return d - timedelta(days=d.weekday())

def slot_date(ws, day):
    days = {"monday":0,"tuesday":1,"wednesday":2,"thursday":3,"friday":4,"saturday":5,"sunday":6}
    return (ws + timedelta(days=days.get(day,0))).strftime("%Y-%m-%d")

def fmt_de(d):
    try:
        return datetime.strptime(d, "%Y-%m-%d").strftime("%d.%m.%Y")
    except:
        return d

def is_holiday(d):
    return d in BAVARIA_HOLIDAYS.get(d[:4], [])

def is_summer(d):
    try:
        return 6 <= datetime.strptime(d, "%Y-%m-%d").month <= 9
    except:
        return False

def is_blocked(d):
    return is_holiday(d) or is_summer(d)

def block_reason(d):
    if is_holiday(d):
        return "🚫 Feiertag"
    elif is_summer(d):
        return "🏖️ Sommerpause"
    return None

# ===== CSS INJECTION =====
def inject_css(dark=False):
    bg = "#1A1D23" if dark else COLORS["weiss"]
    surface = "#2D3238" if dark else COLORS["grau_hell"]
    text = "#FFFFFF" if dark else COLORS["text"]
    primary = COLORS["rot_hell"] if dark else COLORS["rot"]
    
    st.markdown(f"""<style>
    .main {{background:{bg};color:{text};}}
    .stApp {{background:{bg};}}
    section[data-testid="stSidebar"] {{background:{surface};border-right:2px solid {primary};}}
    .stButton>button {{background:linear-gradient(135deg,{primary} 0%,{COLORS["rot_dunkel"]} 100%);
        color:white;border:none;border-radius:8px;padding:0.5rem 1.5rem;font-weight:600;
        transition:all 0.3s;box-shadow:0 2px 4px rgba(0,0,0,0.1);}}
    .stButton>button:hover {{transform:translateY(-2px);box-shadow:0 4px 8px rgba(220,20,60,0.3);}}
    h1,h2,h3 {{color:{primary};font-weight:700;}}
    h1 {{border-bottom:3px solid {primary};padding-bottom:0.5rem;}}
    .stTextInput input,.stTextArea textarea {{border:2px solid {COLORS["grau_mittel"]};
        border-radius:8px;background:{surface};color:{text};}}
    .stTextInput input:focus {{border-color:{primary};box-shadow:0 0 0 2px {primary}40;}}
    @media (max-width:768px) {{.stButton>button {{width:100%;margin:0.25rem 0;}}}}
    </style>""", unsafe_allow_html=True)

# ===== DATABASE CLASS =====
class WasserwachtDB:
    def __init__(self):
        self.db = db
        self._init_admin()
    
    def _init_admin(self):
        if hasattr(st,'secrets'):
            email = st.secrets.get("ADMIN_EMAIL","admin@wasserwacht.de")
            pw = st.secrets.get("ADMIN_PASSWORD","admin123")
            if not self.get_user(email):
                self.db.collection('users').add({
                    'email':email,'name':'Admin','phone':'','password_hash':hash_pw(pw),
                    'role':'admin','active':True,'email_notifications':True,
                    'sms_notifications':False,'created_at':firestore.SERVER_TIMESTAMP
                })
    
    def get_user(self,email):
        try:
            for doc in self.db.collection('users').where('email','==',email).limit(1).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except:
            return None
    
    def create_user(self,email,name,phone,password,role='user'):
        try:
            if self.get_user(email):
                return False,"E-Mail bereits registriert"
            self.db.collection('users').add({
                'email':email,'name':name,'phone':phone,'password_hash':hash_pw(password),
                'role':role,'active':True,'email_notifications':True,'sms_notifications':False,
                'created_at':firestore.SERVER_TIMESTAMP
            })
            self.log('user_created',f"User {email} erstellt")
            return True,"User erstellt"
        except Exception as e:
            return False,str(e)
    
    def auth(self,email,password):
        u = self.get_user(email)
        if not u or not u.get('active',True):
            return False,None
        if u['password_hash'] == hash_pw(password):
            return True,u
        return False,None
    
    def get_all_users(self):
        try:
            users = []
            for doc in self.db.collection('users').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                users.append(data)
            return users
        except:
            return []
    
    def update_user(self,uid,**kwargs):
        try:
            self.db.collection('users').document(uid).update(kwargs)
            return True
        except:
            return False
    
    def delete_user(self,email):
        try:
            u = self.get_user(email)
            if u:
                self.db.collection('users').document(u['id']).delete()
                self.log('user_deleted',f"User {email} gelöscht")
                return True
            return False
        except:
            return False
    
    def create_booking(self,slot_date,slot_time,user_email,user_name,user_phone):
        try:
            if self.get_booking(slot_date,slot_time):
                return False,"Slot bereits gebucht"
            self.db.collection('bookings').add({
                'slot_date':slot_date,'slot_time':slot_time,'user_email':user_email,
                'user_name':user_name,'user_phone':user_phone,'status':'confirmed',
                'created_at':firestore.SERVER_TIMESTAMP
            })
            self.log('booking_created',f"{user_name} buchte {slot_date} {slot_time}")
            return True,"Buchung erfolgreich"
        except Exception as e:
            return False,str(e)
    
    def get_booking(self,slot_date,slot_time):
        try:
            for doc in self.db.collection('bookings').where('slot_date','==',slot_date)\
                    .where('slot_time','==',slot_time).where('status','==','confirmed').limit(1).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                return data
            return None
        except:
            return None
    
    def get_user_bookings(self,email,future_only=False):
        try:
            q = self.db.collection('bookings').where('user_email','==',email)\
                    .where('status','==','confirmed')
            if future_only:
                q = q.where('slot_date','>=',datetime.now().strftime("%Y-%m-%d"))
            bookings = []
            for doc in q.stream():
                data = doc.to_dict()
                data['id'] = doc.id
                bookings.append(data)
            return sorted(bookings,key=lambda x:x['slot_date'])
        except:
            return []
    
    def cancel_booking(self,bid,cancelled_by):
        try:
            self.db.collection('bookings').document(bid).update({
                'status':'cancelled','cancelled_by':cancelled_by,
                'cancelled_at':firestore.SERVER_TIMESTAMP
            })
            self.log('booking_cancelled',f"Buchung {bid} storniert")
            return True
        except:
            return False
    
    def get_week_bookings(self,ws):
        try:
            we = (datetime.strptime(ws,'%Y-%m-%d')+timedelta(days=6)).strftime('%Y-%m-%d')
            result = []
            for doc in self.db.collection('bookings').where('slot_date','>=',ws)\
                    .where('slot_date','<=',we).where('status','==','confirmed').stream():
                data = doc.to_dict()
                data['id'] = doc.id
                result.append(data)
            return result
        except:
            return []
    
    def get_setting(self,key,default=''):
        try:
            doc = self.db.collection('settings').document(key).get()
            return doc.to_dict().get('value',default) if doc.exists else default
        except:
            return default
    
    def set_setting(self,key,value):
        try:
            self.db.collection('settings').document(key).set({
                'value':value,'updated_at':firestore.SERVER_TIMESTAMP
            },merge=True)
            return True
        except:
            return False
    
    def log(self,action,details,user='system'):
        try:
            self.db.collection('audit_log').add({
                'action':action,'details':details,'user_email':user,
                'timestamp':firestore.SERVER_TIMESTAMP
            })
        except:
            pass
    
    def get_logs(self,limit=100):
        try:
            logs = []
            for doc in self.db.collection('audit_log')\
                    .order_by('timestamp',direction=firestore.Query.DESCENDING)\
                    .limit(limit).stream():
                data = doc.to_dict()
                data['id'] = doc.id
                logs.append(data)
            return logs
        except:
            return []
    
    def get_stats(self):
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            users = len(self.get_all_users())
            future = len(list(self.db.collection('bookings').where('slot_date','>=',today)\
                    .where('status','==','confirmed').stream()))
            month_start = datetime.now().replace(day=1).strftime("%Y-%m-%d")
            month = len(list(self.db.collection('bookings').where('slot_date','>=',month_start)\
                    .where('status','==','confirmed').stream()))
            return {'total_users':users,'future_bookings':future,'month_bookings':month}
        except:
            return {'total_users':0,'future_bookings':0,'month_bookings':0}
    
    def archive_old(self):
        try:
            archive_date = (datetime.now()-timedelta(days=365)).strftime("%Y-%m-%d")
            count = 0
            for doc in self.db.collection('bookings').where('slot_date','<',archive_date).stream():
                self.db.collection('archive').add(doc.to_dict())
                doc.reference.delete()
                count += 1
            if count > 0:
                self.log('archiving',f"{count} Buchungen archiviert")
            return count
        except:
            return 0

ww_db = WasserwachtDB()
# ===== EMAIL & SMS CLASSES =====
class Mailer:
    def __init__(self):
        if hasattr(st,'secrets'):
            self.server = st.secrets.get("SMTP_SERVER","smtp.gmail.com")
            self.port = int(st.secrets.get("SMTP_PORT",587))
            self.user = st.secrets.get("SMTP_USER","")
            self.pw = st.secrets.get("SMTP_PASSWORD","")
            self.admin_receiver = st.secrets.get("ADMIN_EMAIL_RECEIVER","")
        else:
            self.server = self.port = self.user = self.pw = self.admin_receiver = ""
    
    def send(self,to,subject,body,attachments=None):
        try:
            msg = MIMEMultipart()
            msg['From'] = self.user
            msg['To'] = to
            msg['Subject'] = subject
            msg.attach(MIMEText(body,'html'))
            
            if attachments:
                for filename,data in attachments:
                    part = MIMEBase('application','octet-stream')
                    part.set_payload(data)
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition',f'attachment; filename={filename}')
                    msg.attach(part)
            
            with smtplib.SMTP(self.server,self.port) as server:
                server.starttls()
                server.login(self.user,self.pw)
                server.send_message(msg)
            return True
        except:
            return False
    
    def booking_confirmation(self,user_email,user_name,slot_date,slot_time):
        subject = f"✅ Buchungsbestätigung {fmt_de(slot_date)}"
        body = f"""<html><body>
        <h2 style="color:{COLORS['rot']}">Wasserwacht Dienstplan+</h2>
        <p>Hallo {user_name},</p>
        <p>Deine Schicht wurde erfolgreich gebucht:</p>
        <ul><li><b>Datum:</b> {fmt_de(slot_date)}</li><li><b>Zeit:</b> {slot_time}</li></ul>
        <p>Du erhältst Erinnerungen 24h und 1h vor Schichtbeginn.</p>
        <p style="color:{COLORS['grau_mittel']}">Bei Fragen: {self.admin_receiver}</p>
        </body></html>"""
        return self.send(user_email,subject,body)
    
    def cancellation_confirmation(self,user_email,user_name,slot_date,slot_time):
        subject = f"🔴 Stornierungsbestätigung {fmt_de(slot_date)}"
        body = f"""<html><body>
        <h2 style="color:{COLORS['rot']}">Wasserwacht Dienstplan+</h2>
        <p>Hallo {user_name},</p>
        <p>Deine Schicht wurde storniert:</p>
        <ul><li><b>Datum:</b> {fmt_de(slot_date)}</li><li><b>Zeit:</b> {slot_time}</li></ul>
        </body></html>"""
        return self.send(user_email,subject,body)
    
    def backup_email(self,backup_zip):
        subject = f"📦 Dienstplan Backup {datetime.now().strftime('%d.%m.%Y')}"
        body = f"""<html><body>
        <h2>Automatisches Backup</h2>
        <p>Anbei das Backup der Dienstplan-Datenbank.</p>
        <p>Zeitpunkt: {datetime.now(TZ).strftime('%d.%m.%Y %H:%M')} Uhr</p>
        </body></html>"""
        filename = f"dienstplan_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.zip"
        
        backup_emails = []
        if hasattr(st,'secrets'):
            try:
                backup_emails = json.loads(st.secrets.get("BACKUP_EMAILS","[]"))
            except:
                backup_emails = []
        
        for email in backup_emails:
            self.send(email,subject,body,[(filename,backup_zip)])
        
        return len(backup_emails) > 0

class TwilioSMS:
    def __init__(self):
        if hasattr(st,'secrets'):
            self.sid = st.secrets.get("TWILIO_ACCOUNT_SID","")
            self.token = st.secrets.get("TWILIO_AUTH_TOKEN","")
            self.phone = st.secrets.get("TWILIO_PHONE_NUMBER","")
            self.enabled = st.secrets.get("ENABLE_SMS_REMINDER","false").lower() == "true"
        else:
            self.sid = self.token = self.phone = ""
            self.enabled = False
    
    def send(self,to,message):
        if not self.enabled or not self.sid:
            return False
        try:
            client = Client(self.sid,self.token)
            client.messages.create(to=to,from_=self.phone,body=message)
            return True
        except:
            return False
    
    def reminder_24h(self,user_phone,user_name,slot_date,slot_time):
        msg = f"Wasserwacht Reminder: Hallo {user_name}, Deine Schicht ist morgen {fmt_de(slot_date)} um {slot_time}. Viel Erfolg!"
        return self.send(user_phone,msg)
    
    def reminder_1h(self,user_phone,user_name,slot_time):
        msg = f"Wasserwacht: Deine Schicht beginnt in 1 Stunde ({slot_time}). Bis gleich!"
        return self.send(user_phone,msg)

mailer = Mailer()
sms = TwilioSMS()

# ===== SCHEDULER =====
def daily_tasks():
    ww_db.archive_old()
    if hasattr(st,'secrets') and st.secrets.get("ENABLE_DAILY_BACKUP","true").lower() == "true":
        try:
            data = ww_db.db.collection('bookings').stream()
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as zf:
                bookings_csv = "date,time,user,phone,status\n"
                for doc in data:
                    d = doc.to_dict()
                    bookings_csv += f"{d.get('slot_date','')},{d.get('slot_time','')},{d.get('user_name','')},{d.get('user_phone','')},{d.get('status','')}\n"
                zf.writestr('bookings.csv',bookings_csv)
            mailer.backup_email(buffer.getvalue())
        except:
            pass

def reminder_tasks():
    tomorrow = (datetime.now()+timedelta(days=1)).strftime("%Y-%m-%d")
    bookings = ww_db.db.collection('bookings').where('slot_date','==',tomorrow)\
            .where('status','==','confirmed').stream()
    for doc in bookings:
        b = doc.to_dict()
        if b.get('user_phone'):
            sms.reminder_24h(b['user_phone'],b['user_name'],b['slot_date'],b['slot_time'])

if 'scheduler_started' not in st.session_state:
    try:
        scheduler = BackgroundScheduler(timezone=TZ)
        backup_time = st.secrets.get("BACKUP_TIME","20:00") if hasattr(st,'secrets') else "20:00"
        h,m = backup_time.split(":")
        scheduler.add_job(daily_tasks,'cron',hour=int(h),minute=int(m))
        scheduler.add_job(reminder_tasks,'cron',hour=18,minute=0)
        scheduler.start()
        st.session_state.scheduler_started = True
    except:
        pass

# ===== MAIN APP =====
def main():
    st.set_page_config(page_title="Wasserwacht Dienstplan+",page_icon="🌊",layout="wide")
    
    if 'dark_mode' not in st.session_state:
        st.session_state.dark_mode = st.secrets.get("DARK_MODE_DEFAULT","false").lower()=="true" if hasattr(st,'secrets') else False
    
    inject_css(st.session_state.dark_mode)
    
    if 'user' not in st.session_state:
        st.session_state.user = None
    if 'page' not in st.session_state:
        st.session_state.page = 'home'
    
    with st.sidebar:
        st.markdown(f"<h1 style='color:{COLORS['rot']}'>🌊 Wasserwacht</h1>",unsafe_allow_html=True)
        st.markdown(f"<p style='color:{COLORS['grau_mittel']}'>Dienstplan+ v{VERSION}</p>",unsafe_allow_html=True)
        st.divider()
        
        if st.session_state.user:
            st.success(f"✅ {st.session_state.user['name']}")
            role = st.session_state.user.get('role','user')
            
            if st.button("🏠 Startseite",use_container_width=True):
                st.session_state.page = 'home'
                st.rerun()
            
            if st.button("📅 Meine Schichten",use_container_width=True):
                st.session_state.page = 'my_bookings'
                st.rerun()
            
            if st.button("👤 Profil",use_container_width=True):
                st.session_state.page = 'profile'
                st.rerun()
            
            if role == 'admin':
                st.divider()
                st.markdown("**🔧 Admin-Bereich**")
                if st.button("📊 Dashboard",use_container_width=True):
                    st.session_state.page = 'dashboard'
                    st.rerun()
                if st.button("👥 Benutzer",use_container_width=True):
                    st.session_state.page = 'users'
                    st.rerun()
                if st.button("📥 Export",use_container_width=True):
                    st.session_state.page = 'export'
                    st.rerun()
                if st.button("⚙️ Einstellungen",use_container_width=True):
                    st.session_state.page = 'settings'
                    st.rerun()
            
            st.divider()
            if st.button("📄 Impressum",use_container_width=True):
                st.session_state.page = 'impressum'
                st.rerun()
            
            if st.button("🚪 Logout",use_container_width=True):
                st.session_state.user = None
                st.session_state.page = 'home'
                st.rerun()
        else:
            if st.button("🔑 Login",use_container_width=True):
                st.session_state.page = 'login'
                st.rerun()
            if st.button("📄 Impressum",use_container_width=True):
                st.session_state.page = 'impressum'
                st.rerun()
        
        st.divider()
        if st.button("🌓" if st.session_state.dark_mode else "☀️",use_container_width=True,help="Dark Mode Toggle"):
            st.session_state.dark_mode = not st.session_state.dark_mode
            st.rerun()
    
    page = st.session_state.page
    
    if page == 'login':
        show_login()
    elif page == 'home':
        show_home()
    elif page == 'my_bookings':
        show_my_bookings()
    elif page == 'profile':
        show_profile()
    elif page == 'dashboard':
        show_dashboard()
    elif page == 'users':
        show_users()
    elif page == 'export':
        show_export()
    elif page == 'settings':
        show_settings()
    elif page == 'impressum':
        show_impressum()

def show_login():
    st.title("🔑 Login")
    email = st.text_input("E-Mail")
    pw = st.text_input("Passwort",type="password")
    
    if st.button("Login",type="primary"):
        success,user = ww_db.auth(email,pw)
        if success:
            st.session_state.user = user
            st.session_state.page = 'home'
            st.success("✅ Erfolgreich angemeldet!")
            st.rerun()
        else:
            st.error("❌ Falsche Login-Daten")

def show_home():
    if not st.session_state.user:
        st.title("🌊 Willkommen beim Wasserwacht Dienstplan+")
        st.info("Bitte melde dich an um Schichten zu buchen.")
        return
    
    st.title("📅 Schichtplan")
    user = st.session_state.user
    
    col1,col2 = st.columns([3,1])
    with col1:
        if 'current_week' not in st.session_state:
            st.session_state.current_week = week_start()
        
        cws = st.session_state.current_week
        
        c1,c2,c3 = st.columns([1,3,1])
        with c1:
            if st.button("◀️ Vorherige Woche"):
                st.session_state.current_week -= timedelta(days=7)
                st.rerun()
        with c2:
            st.markdown(f"<h3 style='text-align:center'>KW {cws.isocalendar()[1]}, {cws.year}</h3>",unsafe_allow_html=True)
        with c3:
            if st.button("Nächste Woche ▶️"):
                st.session_state.current_week += timedelta(days=7)
                st.rerun()
        
        bookings = ww_db.get_week_bookings(cws.strftime("%Y-%m-%d"))
        booking_map = {(b['slot_date'],b['slot_time']):b for b in bookings}
        
        for slot in WEEKLY_SLOTS:
            sd = slot_date(cws,slot['day'])
            st.markdown(f"### {slot['day_name']}, {fmt_de(sd)}")
            
            booking = booking_map.get((sd,f"{slot['start']}-{slot['end']}"))
            blocked = is_blocked(sd)
            
            if blocked:
                reason = block_reason(sd)
                st.warning(f"{reason} {slot['start']}-{slot['end']}")
            elif booking:
                st.success(f"✅ Gebucht: {booking['user_name']} | {slot['start']}-{slot['end']}")
                if user['role']=='admin' or booking['user_email']==user['email']:
                    if st.button(f"🔴 Stornieren",key=f"cancel_{slot['id']}_{sd}"):
                        ww_db.cancel_booking(booking['id'],user['email'])
                        mailer.cancellation_confirmation(booking['user_email'],booking['user_name'],sd,f"{slot['start']}-{slot['end']}")
                        st.success("Storniert!")
                        st.rerun()
            else:
                if st.button(f"✅ Buchen: {slot['start']}-{slot['end']}",key=f"book_{slot['id']}_{sd}"):
                    success,msg = ww_db.create_booking(sd,f"{slot['start']}-{slot['end']}",user['email'],user['name'],user.get('phone',''))
                    if success:
                        mailer.booking_confirmation(user['email'],user['name'],sd,f"{slot['start']}-{slot['end']}")
                        st.success(msg)
                        st.rerun()
                    else:
                        st.error(msg)
    
    with col2:
        st.markdown("### 📊 Deine Stats")
        my_bookings = ww_db.get_user_bookings(user['email'],future_only=True)
        st.metric("Kommende Schichten",len(my_bookings))

def show_my_bookings():
    st.title("📅 Meine Schichten")
    user = st.session_state.user
    bookings = ww_db.get_user_bookings(user['email'])
    
    if not bookings:
        st.info("Du hast noch keine Schichten gebucht.")
        return
    
    for b in bookings:
        col1,col2,col3 = st.columns([2,2,1])
        with col1:
            st.write(f"**{fmt_de(b['slot_date'])}**")
        with col2:
            st.write(b['slot_time'])
        with col3:
            if st.button("🔴 Stornieren",key=f"cancel_{b['id']}"):
                ww_db.cancel_booking(b['id'],user['email'])
                st.rerun()

def show_profile():
    st.title("👤 Profil")
    user = st.session_state.user
    
    name = st.text_input("Name",value=user.get('name',''))
    phone = st.text_input("Telefon",value=user.get('phone',''))
    email_notif = st.checkbox("E-Mail-Benachrichtigungen",value=user.get('email_notifications',True))
    sms_notif = st.checkbox("SMS-Benachrichtigungen",value=user.get('sms_notifications',False))
    
    if st.button("💾 Speichern",type="primary"):
        ww_db.update_user(user['id'],name=name,phone=phone,email_notifications=email_notif,sms_notifications=sms_notif)
        st.success("✅ Profil aktualisiert!")
        st.session_state.user = ww_db.get_user(user['email'])
    
    st.divider()
    st.subheader("🔒 Passwort ändern")
    new_pw = st.text_input("Neues Passwort",type="password")
    if st.button("Passwort ändern"):
        if new_pw:
            ww_db.update_user(user['id'],password_hash=hash_pw(new_pw))
            st.success("✅ Passwort geändert!")
def show_dashboard():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("📊 Dashboard")
    
    stats = ww_db.get_stats()
    
    col1,col2,col3 = st.columns(3)
    with col1:
        st.markdown(f"""<div style='background:linear-gradient(135deg,{COLORS['rot']} 0%,{COLORS['blau']} 100%);
            padding:1.5rem;border-radius:12px;text-align:center;color:white'>
            <h2 style='color:white;margin:0;font-size:2.5rem'>{stats['total_users']}</h2>
            <p style='margin:0;opacity:0.9'>Registrierte User</p></div>""",unsafe_allow_html=True)
    with col2:
        st.markdown(f"""<div style='background:linear-gradient(135deg,{COLORS['blau']} 0%,{COLORS['blau_hell']} 100%);
            padding:1.5rem;border-radius:12px;text-align:center;color:white'>
            <h2 style='color:white;margin:0;font-size:2.5rem'>{stats['future_bookings']}</h2>
            <p style='margin:0;opacity:0.9'>Kommende Schichten</p></div>""",unsafe_allow_html=True)
    with col3:
        st.markdown(f"""<div style='background:linear-gradient(135deg,{COLORS['rot_hell']} 0%,{COLORS['rot']} 100%);
            padding:1.5rem;border-radius:12px;text-align:center;color:white'>
            <h2 style='color:white;margin:0;font-size:2.5rem'>{stats['month_bookings']}</h2>
            <p style='margin:0;opacity:0.9'>Buchungen diesen Monat</p></div>""",unsafe_allow_html=True)
    
    st.divider()
    
    col1,col2 = st.columns(2)
    with col1:
        st.subheader("📈 Trend-Analyse")
        last_30_days = []
        for i in range(30):
            d = (datetime.now()-timedelta(days=i)).strftime("%Y-%m-%d")
            count = len(list(ww_db.db.collection('bookings').where('slot_date','==',d).where('status','==','confirmed').stream()))
            last_30_days.append({'Datum':d,'Buchungen':count})
        
        df = pd.DataFrame(last_30_days)
        fig = px.line(df,x='Datum',y='Buchungen',title='Buchungen letzte 30 Tage')
        fig.update_traces(line_color=COLORS['rot'])
        st.plotly_chart(fig,use_container_width=True)
    
    with col2:
        st.subheader("👥 User-Aktivität")
        users = ww_db.get_all_users()
        user_stats = []
        for u in users:
            bookings = len(ww_db.get_user_bookings(u['email']))
            user_stats.append({'Name':u['name'],'Buchungen':bookings})
        
        df = pd.DataFrame(user_stats).sort_values('Buchungen',ascending=False).head(10)
        fig = px.bar(df,x='Name',y='Buchungen',title='Top 10 Bucher')
        fig.update_traces(marker_color=COLORS['blau'])
        st.plotly_chart(fig,use_container_width=True)
    
    st.divider()
    st.subheader("📋 Audit Log (letzte 50 Einträge)")
    logs = ww_db.get_logs(50)
    if logs:
        for log in logs:
            ts = log.get('timestamp')
            ts_str = ts.strftime('%d.%m.%Y %H:%M') if hasattr(ts,'strftime') else 'N/A'
            st.text(f"{ts_str} | {log.get('action','')} | {log.get('details','')}")
    else:
        st.info("Noch keine Logs")

def show_users():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("👥 Benutzerverwaltung")
    
    tab1,tab2,tab3 = st.tabs(["User-Liste","Neuen User anlegen","Für User buchen"])
    
    with tab1:
        users = ww_db.get_all_users()
        for u in users:
            col1,col2,col3,col4,col5 = st.columns([2,2,1,1,1])
            with col1:
                st.write(f"**{u['name']}**")
            with col2:
                st.write(u['email'])
            with col3:
                st.write("🔧" if u['role']=='admin' else "👤")
            with col4:
                if u['email'] != st.session_state.user['email']:
                    active = u.get('active',True)
                    if st.button("✅" if active else "❌",key=f"toggle_{u['id']}"):
                        ww_db.update_user(u['id'],active=not active)
                        st.rerun()
            with col5:
                if u['email'] != st.session_state.user['email']:
                    if st.button("🗑️",key=f"del_{u['id']}"):
                        ww_db.delete_user(u['email'])
                        st.rerun()
    
    with tab2:
        with st.form("new_user"):
            email = st.text_input("E-Mail")
            name = st.text_input("Name")
            phone = st.text_input("Telefon")
            password = st.text_input("Passwort",type="password")
            role = st.selectbox("Rolle",["user","admin"])
            
            if st.form_submit_button("User anlegen",type="primary"):
                success,msg = ww_db.create_user(email,name,phone,password,role)
                if success:
                    st.success(f"✅ {msg}")
                else:
                    st.error(f"❌ {msg}")
    
    with tab3:
        st.subheader("Schicht für User buchen")
        users = ww_db.get_all_users()
        user_options = {u['name']:u for u in users}
        selected_user_name = st.selectbox("User auswählen",list(user_options.keys()))
        selected_user = user_options[selected_user_name]
        
        ws = st.date_input("Woche",value=week_start())
        ws = week_start(ws)
        
        slot = st.selectbox("Slot",[(s['day_name'],s['start'],s['end']) for s in WEEKLY_SLOTS])
        slot_day = [s for s in WEEKLY_SLOTS if s['day_name']==slot[0]][0]
        sd = slot_date(ws,slot_day['day'])
        
        if st.button("Für User buchen",type="primary"):
            success,msg = ww_db.create_booking(sd,f"{slot[1]}-{slot[2]}",selected_user['email'],selected_user['name'],selected_user.get('phone',''))
            if success:
                st.success(f"✅ {msg}")
                mailer.booking_confirmation(selected_user['email'],selected_user['name'],sd,f"{slot[1]}-{slot[2]}")
            else:
                st.error(f"❌ {msg}")

def show_export():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("📥 Datenexport")
    
    col1,col2 = st.columns(2)
    
    with col1:
        st.subheader("Excel Export")
        if st.button("📊 Excel herunterladen",type="primary"):
            bookings = []
            for doc in ww_db.db.collection('bookings').stream():
                b = doc.to_dict()
                bookings.append({
                    'Datum':b.get('slot_date',''),
                    'Zeit':b.get('slot_time',''),
                    'Name':b.get('user_name',''),
                    'E-Mail':b.get('user_email',''),
                    'Telefon':b.get('user_phone',''),
                    'Status':b.get('status','')
                })
            
            df = pd.DataFrame(bookings)
            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer,engine='openpyxl') as writer:
                df.to_excel(writer,index=False,sheet_name='Buchungen')
            
            st.download_button("⬇️ Excel herunterladen",buffer.getvalue(),
                f"dienstplan_export_{datetime.now().strftime('%Y%m%d')}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    
    with col2:
        st.subheader("Backup per E-Mail")
        if st.button("📧 Backup senden",type="primary"):
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer,'w') as zf:
                bookings_csv = "date,time,user,phone,status\n"
                for doc in ww_db.db.collection('bookings').stream():
                    d = doc.to_dict()
                    bookings_csv += f"{d.get('slot_date','')},{d.get('slot_time','')},{d.get('user_name','')},{d.get('user_phone','')},{d.get('status','')}\n"
                zf.writestr('bookings.csv',bookings_csv)
            
            if mailer.backup_email(buffer.getvalue()):
                st.success("✅ Backup per E-Mail versendet!")
            else:
                st.error("❌ E-Mail-Versand fehlgeschlagen")
    
    st.divider()
    st.subheader("🗄️ Archivierung")
    if st.button("Alte Buchungen archivieren (>12 Monate)"):
        count = ww_db.archive_old()
        st.success(f"✅ {count} Buchungen archiviert")

def show_settings():
    if st.session_state.user.get('role') != 'admin':
        st.error("❌ Nur für Admins")
        return
    
    st.title("⚙️ Einstellungen")
    
    tab1,tab2 = st.tabs(["E-Mail Templates","SMS Templates"])
    
    with tab1:
        st.subheader("📧 E-Mail-Vorlagen")
        
        booking_template = ww_db.get_setting('email_booking_template',
            'Hallo {name}, deine Schicht am {date} um {time} wurde gebucht.')
        
        cancellation_template = ww_db.get_setting('email_cancellation_template',
            'Hallo {name}, deine Schicht am {date} um {time} wurde storniert.')
        
        booking_tpl = st.text_area("Buchungsbestätigung",booking_template,height=100,
            help="Platzhalter: {name}, {date}, {time}")
        cancellation_tpl = st.text_area("Stornierungsbestätigung",cancellation_template,height=100,
            help="Platzhalter: {name}, {date}, {time}")
        
        if st.button("💾 Speichern",type="primary"):
            ww_db.set_setting('email_booking_template',booking_tpl)
            ww_db.set_setting('email_cancellation_template',cancellation_tpl)
            st.success("✅ Templates gespeichert!")
    
    with tab2:
        st.subheader("📱 SMS-Vorlagen")
        
        sms_24h = ww_db.get_setting('sms_24h_template',
            'Wasserwacht: Deine Schicht ist morgen {date} um {time}. Viel Erfolg!')
        
        sms_1h = ww_db.get_setting('sms_1h_template',
            'Wasserwacht: Deine Schicht beginnt in 1h ({time}). Bis gleich!')
        
        sms_24h_tpl = st.text_area("24h Reminder",sms_24h,height=100,
            help="Platzhalter: {name}, {date}, {time}")
        sms_1h_tpl = st.text_area("1h Reminder",sms_1h,height=100,
            help="Platzhalter: {name}, {time}")
        
        if st.button("💾 Speichern",type="primary",key="sms_save"):
            ww_db.set_setting('sms_24h_template',sms_24h_tpl)
            ww_db.set_setting('sms_1h_template',sms_1h_tpl)
            st.success("✅ Templates gespeichert!")

def show_impressum():
    st.title("📄 Impressum")
    
    default_impressum = """
# Impressum

## Angaben gemäß § 5 TMG

**Wasserwacht Hauzenberg e.V.**  
[Vereinsadresse]  
[PLZ] [Ort]

**Vertreten durch:**  
[Name des 1. Vorsitzenden]  
[Name des 2. Vorsitzenden]

**Kontakt:**  
Telefon: [Vereins-Telefonnummer]  
E-Mail: [Vereins-E-Mail]

**Registereintrag:**  
Eingetragen im Vereinsregister  
Registergericht: [z.B. Amtsgericht Passau]  
Registernummer: [VR-Nummer]

---

## Datenschutz

### Verantwortliche Stelle
Wasserwacht Hauzenberg e.V., [Adresse]

### Gespeicherte Daten
- E-Mail-Adressen der Mitglieder
- Telefonnummern (für SMS-Erinnerungen)
- Dienstplan-Buchungen (Datum, Uhrzeit, Schicht)
- Passwörter (verschlüsselt als SHA256-Hash)

### Rechtsgrundlage
Art. 6 Abs. 1 lit. b DSGVO (Vertragsdurchführung / Vereinsmitgliedschaft)

### Datenübermittlung
- Firebase Firestore (Google Cloud, Standort: Frankfurt, Deutschland)
- Streamlit Hosting (Streamlit Inc., USA)

### Ihre Rechte
- Auskunft über gespeicherte Daten (Art. 15 DSGVO)
- Berichtigung unrichtiger Daten (Art. 16 DSGVO)
- Löschung Ihrer Daten (Art. 17 DSGVO)
- Widerspruch gegen Verarbeitung (Art. 21 DSGVO)

Kontakt: [Vereins-E-Mail]

---

**Stand:** November 2025
"""
    
    impressum = ww_db.get_setting('impressum',default_impressum)
    st.markdown(impressum)
    
    if st.session_state.user and st.session_state.user.get('role')=='admin':
        with st.expander("✏️ Impressum bearbeiten"):
            new_impressum = st.text_area("Impressum (Markdown)",impressum,height=400)
            if st.button("💾 Speichern",type="primary"):
                ww_db.set_setting('impressum',new_impressum)
                st.success("✅ Impressum aktualisiert!")
                st.rerun()

if __name__ == "__main__":
    main()
